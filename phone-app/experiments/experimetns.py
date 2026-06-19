from time import sleep

from find_device.PLCLight import PLCLight
light = PLCLight('5.168.214.75.1.1', '192.168.0.161')
with light:
    light.set_brightness(5)
with light:
    light.set_brightness(100)
with light:
    light.set_brightness(5)
with light:
    light.set_brightness(50)
with light:
    light.set_brightness(0)