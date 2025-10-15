import time

from machine import I2C, Pin

from weight import WeightUnit
from flash_light import FlashLightUnit
from buzzer import BuzzerUnit


# Init buzzer
buzzer = BuzzerUnit((6, 5))
buzzer.once(freq=4000, duty=50, duration=100)

# Init flashlight
ligth = FlashLightUnit((8, 7))
ligth.flash(ligth.BRIGHTNESS_100, ligth.TIME_1300MS, True)

# Init scale
scale = WeightUnit(
    (39, 38)
)  # scale.get_scale_weight returns the current detected wight in grams (float)
scale.zero_value = 0
scale._scale = 1.0

# Check zero weight and place known weight on scale to calibrate
raw_weights = []
processed_weights = []
iters = 0
while True:
    raw_weight = scale.get_raw_weight
    print(f"Raw weight reading: {raw_weight} g")
    test_weight = scale.get_scale_weight
    print(f"Processed weight reading: {test_weight} g")
    time.sleep(1)
    raw_weights.append(raw_weight)
    processed_weights.append(test_weight)
    iters += 1
    if iters == 10:
        break

print("Average raw weight:", sum(raw_weights) / len(raw_weights))
print("Average processed weight:", sum(processed_weights) / len(processed_weights))
print("Use these values to update the TARE and SCALE constants")