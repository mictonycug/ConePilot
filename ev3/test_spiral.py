#!/usr/bin/env python3
import ev3dev.ev3 as ev3
import time

motor = ev3.LargeMotor('outB')
if not motor.connected:
    print("No motor on outB")
    exit(1)

print("Running spiral motor for 60 seconds...")
motor.run_forever(speed_sp=720)
time.sleep(60)
motor.stop(stop_action='brake')
print("Done.")
