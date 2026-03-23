#!/usr/bin/env python3
"""
Test the PLACE (drop) sequence.
Spiral spins forward, column stays at top.
Usage: python3 test_place.py
"""
import time
from ev3dev2.motor import LargeMotor

SPIRAL_PORT = 'outB'
SPIRAL_DEG = 360
SPIRAL_SPEED = 720

spiral = LargeMotor(SPIRAL_PORT)
if not spiral.connected:
    print("Spiral motor not found on " + SPIRAL_PORT)
    exit(1)

print("Spiral on %s (pos=%d)" % (SPIRAL_PORT, spiral.position))
print("Press ENTER to drop a cone, q to quit\n")

count = 0
while True:
    cmd = input("> ").strip()
    if cmd == 'q':
        break
    count += 1
    print("  DROP #%d: spinning +%d deg..." % (count, SPIRAL_DEG))
    spiral.run_to_rel_pos(speed_sp=SPIRAL_SPEED, position_sp=SPIRAL_DEG, stop_action='hold')
    spiral.wait_until_not_moving(timeout=10000)
    print("  Done. Position: %d" % spiral.position)
    time.sleep(0.5)

print("Dropped %d cone(s)." % count)
