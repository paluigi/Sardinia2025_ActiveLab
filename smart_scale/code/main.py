import os
import ujson
import gc
import time
import network
import binascii
import ntptime
from machine import I2C, Pin
from umqtt.robust import MQTTClient

from camera import Camera, FrameSize, PixelFormat

from weight import WeightUnit
from flash_light import FlashLightUnit
from buzzer import BuzzerUnit

import secrets as s


# Init MQTT
c = MQTTClient(
    client_id=s.MQTT_CLIENT,
    server=s.MQTT_SERVER,
    port=s.MQTT_PORT,
    user=s.MQTT_USER,
    password=s.MWTT_PWD,
)


def sub_cb(topic, msg):
    print((topic, msg))
    if topic == b"ping_alive":
        c.publish(topic="ack_alive", msg=msg, retain=True, qos=0)


c.set_callback(sub_cb)

# Camera init
p18 = Pin(18, Pin.OUT)  # Pin 18 need to be set to 0
p18.value(0)
time.sleep(0.5)  # Sleep needed before instantiating the Camera object
cam = Camera(
    frame_size=FrameSize.VGA,
    pixel_format=PixelFormat.JPEG,
    init=False,
    powerdown_pin=-1,
)

# Init scale
scale = WeightUnit(
    (39, 38)
)  # scale.get_scale_weight returns the current detected wight in grams (float)
scale.zero_value = s.TARE
scale._scale = s.SCALE
TOLERANCE_MIN = 100.0  # Minimum weight detectable
TOLERANCE_DYN = 20.0  # Maximum weight change to asses stability

# Init buzzer
buzzer = BuzzerUnit((6, 5))
# buzzer.once(freq=4000, duty=50, duration=100)

# Init flashlight
ligth = FlashLightUnit((8, 7))
# ligth.flash(ligth.BRIGHTNESS_100, ligth.TIME_1300MS, True)


# Wifi connection
def connect_wifi(ssid, password):
    sta_if = network.WLAN(network.STA_IF)
    if not sta_if.isconnected():
        print("Connecting to WiFi...")
        sta_if.active(True)
        sta_if.connect(ssid, password)
        while not sta_if.isconnected():
            time.sleep(1)
    print("Network Config:", sta_if.ifconfig())
    # Subscribe to MQTT topics
    if not c.connect(clean_session=False):
        print("New session being set up")
        c.subscribe(b"ping_alive")
    # Sync time via NTP
    try:
        ntptime.settime()
        print("System time synchronized via NTP")
    except Exception as e:
        print(f"Error synchronizing time: {e}")
    return sta_if


# Check WiFi connection and reconnect if necessary
def check_wifi_connection(sta_if, ssid, password):
    if not sta_if.isconnected():
        print("WiFi connection lost. Reconnecting...")
        sta_if.active(True)
        sta_if.connect(ssid, password)
        attempt = 0
        while not sta_if.isconnected() and attempt < 10:
            time.sleep(1)
            attempt += 1
            print(f"Reconnection attempt {attempt}/10")

        if sta_if.isconnected():
            print("WiFi reconnected successfully")
            print("Network Config:", sta_if.ifconfig())
            # Subscribe to MQTT topics
            if not c.connect(clean_session=False):
                print("New session being set up")
                c.subscribe(b"ping_alive")
            # Sync time via NTP
            try:    
                ntptime.settime()
                print("System time synchronized via NTP")
            except Exception as e:
                print(f"Error synchronizing time: {e}")
            return True
        else:
            print("Failed to reconnect to WiFi")
            return False
    return True


# Function to capture and save image with timestamp
def capture_image():
    # Generate timestamp for filename
    year, month, day, hour, minute, second, _, _ = time.localtime()
    timestamp = f"{year:04d}{month:02d}{day:02d}_{hour:02d}{minute:02d}{second:02d}"
    filename = f"{s.MQTT_CLIENT}_{timestamp}.jpg"

    try:
        # Initialize camera
        print("Initializing camera...")
        cam.init()
        # flashing light
        ligth.flash(ligth.BRIGHTNESS_100, ligth.TIME_1300MS, True)
        # Capture image
        print("Capturing image...")
        buffer = cam.capture()

        # Save image to file
        with open(filename, "wb") as f:
            f.write(buffer)
        # Remove image from memory and collect garbage
        cam.free_buffer()
        gc.collect()
        print(f"Image saved as {filename}")
        return filename
    except Exception as e:
        print(f"Error capturing image: {e}")
        buzzer.once(freq=4000, duty=50, duration=300)
        return None
    finally:
        # Always deinitialize camera
        try:
            print("Deinitializing camera...")
            cam.deinit()
        except Exception as e:
            print(f"Error deinitializing camera: {e}")



def send_mqtt_message(filename, weight, raw_weight):
    try:
        # Subscribe to MQTT topics
        if not c.connect(clean_session=False):
            print("New session being set up")
            c.subscribe(b"ping_alive")
        # Read image file and encode to base64
        with open(filename, "rb") as f:
            image_data = f.read()
        image_64 = binascii.b2a_base64(image_data).strip()
        c.publish(
            topic="image_upload",
            msg=ujson.dumps(
                {
                    "filename": filename,
                    "client": s.MQTT_CLIENT,
                    "weight": weight,
                    "raw_weight": raw_weight,
                    "tare": s.TARE,
                    "image": image_64
                }
            ),
            retain=True,
            qos=0,
        )
        print(f"MQTT message sent for {filename} with weight {weight}g")
        # Remove image file after successful MQTT send
        os.remove(filename)
        buzzer.once(freq=4000, duty=50, duration=50)
    except Exception as e:
        # save the data as json file if MQTT fails
        error_data = {
            "filename": filename,
            "weight": weight,
        }
        json_filename = f"{filename[:-4]}.json"
        with open(json_filename, "w") as f:
            ujson.dump(error_data, f)
        print(f"Error sending MQTT message: {e}")


# Main function to monitor weight and capture images
def monitor_weight_and_capture(sta_if, ssid, password):
    # Initialize variables
    weight_history = []
    history_length = 10  # Number of stable readings before capturing
    start_time = time.ticks_ms()

    print("Starting weight monitoring...")

    while True:
        # Check WiFi connection every loop
        check_wifi_connection(sta_if, ssid, password)

        # Check MQTT messages every minute
        if time.ticks_diff(time.ticks_ms(), start_time) > 60000:
            c.check_msg()
            start_time = time.ticks_ms()

        # Get current weight
        current_weight = scale.get_scale_weight
        current_raw_weight = scale.get_raw_weight

        # Check if an object is placed on the scale
        if current_weight > TOLERANCE_MIN:
            # Add current weight to history
            weight_history.append(current_weight)

            if len(weight_history) > history_length:
                weight_history.pop(0)

            # Check stability once we have enough samples
            if len(weight_history) == 10:
                weight_range = max(weight_history) - min(weight_history)
                if weight_range <= TOLERANCE_DYN:
                    print(f"Weight stable ({current_weight:.1f}g). Capturing image...")
                    filename = capture_image()

                    if filename:
                        print(f"Image captured and saved as {filename}")                        
                        send_mqtt_message(filename, current_weight, current_raw_weight)
                        weight_history = []  # reset the weight history
                        time.sleep(2)  # Wait a bit before next capture
                    else:
                        print("Failed to capture image")
        # Small delay between readings
        time.sleep(0.2)


# Main program
def main():
    # Connect to WiFi
    sta_if = connect_wifi(s.WIFI_SSID, s.WIFI_PASSWORD)

    # Start monitoring weight and capturing images
    try:
        monitor_weight_and_capture(sta_if, s.WIFI_SSID, s.WIFI_PASSWORD)
    except KeyboardInterrupt:
        print("Program stopped by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up resources if needed
        c.disconnect()
        print("Exiting program")


if __name__ == "__main__":
    main()
