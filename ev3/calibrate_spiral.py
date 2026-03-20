#!/usr/bin/env python3
"""
Calibrate the spiral motor (cone release/pickup).
Usage: python3 calibrate_spiral.py
"""
from ev3dev2.motor import LargeMotor

PORT = 'outC'
SPEED = 720

motor = LargeMotor(PORT)
if not motor.connected:
    print("No motor on " + PORT)
    exit(1)

motor.position = 0
cone_degrees = 360
cones_dropped = 0

print("=" * 45)
print("  Spiral Calibration")
print("  Port: %s  Speed: %d" % (PORT, SPEED))
print("=" * 45)
print("")
print("Commands:")
print("  d [deg]  - DROP: spin forward (default: current setting)")
print("  p [deg]  - PICKUP: spin reverse")
print("  s <deg>  - Set degrees-per-cone")
print("  f <deg>  - Free spin forward")
print("  r <deg>  - Reverse spin")
print("  zero     - Reset position to 0")
print("  q        - Quit")
print("")

while True:
    cmd = input("[%ddeg/cone, pos=%d] > " % (cone_degrees, motor.position)).strip()
    if not cmd:
        continue
    if cmd == 'q':
        break

    parts = cmd.split()
    action = parts[0]

    if action == 'd':
        deg = int(parts[1]) if len(parts) > 1 else cone_degrees
        cones_dropped += 1
        print("  DROP #%d: spinning +%d deg..." % (cones_dropped, deg))
        motor.run_to_rel_pos(speed_sp=SPEED, position_sp=deg, stop_action='hold')
        motor.wait_until_not_moving(timeout=10000)
        print("  Done. Position: %d" % motor.position)

    elif action == 'p':
        deg = int(parts[1]) if len(parts) > 1 else cone_degrees
        cones_dropped = max(0, cones_dropped - 1)
        print("  PICKUP: spinning -%d deg..." % deg)
        motor.run_to_rel_pos(speed_sp=SPEED, position_sp=-deg, stop_action='hold')
        motor.wait_until_not_moving(timeout=10000)
        print("  Done. Position: %d" % motor.position)

    elif action == 's':
        if len(parts) > 1:
            cone_degrees = int(parts[1])
            print("  Set degrees-per-cone = %d" % cone_degrees)
        else:
            print("  Current: %d deg/cone" % cone_degrees)

    elif action == 'f':
        deg = int(parts[1]) if len(parts) > 1 else 90
        print("  Free spin +%d deg..." % deg)
        motor.run_to_rel_pos(speed_sp=SPEED, position_sp=deg, stop_action='hold')
        motor.wait_until_not_moving(timeout=10000)
        print("  Position: %d" % motor.position)

    elif action == 'r':
        deg = int(parts[1]) if len(parts) > 1 else 90
        print("  Reverse spin -%d deg..." % deg)
        motor.run_to_rel_pos(speed_sp=SPEED, position_sp=-deg, stop_action='hold')
        motor.wait_until_not_moving(timeout=10000)
        print("  Position: %d" % motor.position)

    elif action == 'zero':
        motor.position = 0
        cones_dropped = 0
        print("  Position reset to 0")

    else:
        print("  Unknown command.")
