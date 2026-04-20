import math
level = 50
max_lvl = 50
div_low = 4.0
div_high = 100.0

progress = min(1.0, max(0.0, (level - 1) / (max_lvl - 1)))
divisor = div_low + (progress * (div_high - div_low))

threshold = int(100 * (1.25 ** (level - 1)))
base_xp = threshold / divisor

print(f"Level: {level}")
print(f"Progress: {progress}")
print(f"Divisor: {divisor}")
print(f"Threshold: {threshold}")
print(f"BaseXP: {base_xp}")
print(f"1.25^49: {1.25 ** 49}")
print(f"1.25^48: {1.25 ** 48}")
