#!/usr/bin/env python3
"""
Calibrate the column/lift motor.
Usage: python3 calibrate_column.py
"""
import ev3dev.ev3 as ev3

PORT = 'outA'
SPEED = 12

motor = ev3.LargeMotor(PORT)
if not motor.connected:
    print("No motor on " + PORT)
    exit(1)

motor.position = 0
up_pos = 0
down_pos = 100

print("=" * 45)
print("  Column/Lift Calibration")
print("  Port: %s  Speed: %d" % (PORT, SPEED))
print("=" * 45)
print("")
print("Commands:")
print("  u        - Go to UP position")
print("  d        - Go to DOWN position")
print("  g <pos>  - Go to absolute position")
print("  n <deg>  - Nudge relative degrees")
print("  su <pos> - Set UP pos (default: current)")
print("  sd <pos> - Set DOWN pos (default: current)")
print("  zero     - Reset position to 0")
print("  off      - Release motor")
print("  show     - Show saved positions")
print("  q        - Quit")
print("")

while True:
    cmd = input("[pos=%d] > " % motor.position).strip()
    if not cmd:
        continue
    if cmd == 'q':
        motor.stop(stop_action='coast')
        break

    parts = cmd.split()
    action = parts[0]

    if action == 'u':
        print("  Moving to UP (%d)..." % up_pos)
        motor.run_to_abs_pos(speed_sp=SPEED, position_sp=up_pos, stop_action='hold')
        motor.wait_while('running', timeout=10000)
        print("  Position: %d" % motor.position)

    elif action == 'd':
        print("  Moving to DOWN (%d)..." % down_pos)
        motor.run_to_abs_pos(speed_sp=SPEED, position_sp=down_pos, stop_action='hold')
        motor.wait_while('running', timeout=10000)
        print("  Position: %d" % motor.position)

    elif action == 'g':
        pos = int(parts[1]) if len(parts) > 1 else 0
        print("  Going to %d..." % pos)
        motor.run_to_abs_pos(speed_sp=SPEED, position_sp=pos, stop_action='hold')
        motor.wait_while('running', timeout=10000)
        print("  Position: %d" % motor.position)

    elif action == 'n':
        deg = int(parts[1]) if len(parts) > 1 else 10
        print("  Nudging %d deg..." % deg)
        motor.run_to_rel_pos(speed_sp=SPEED, position_sp=deg, stop_action='hold')
        motor.wait_while('running', timeout=10000)
        print("  Position: %d" % motor.position)

    elif action == 'su':
        up_pos = int(parts[1]) if len(parts) > 1 else motor.position
        print("  UP position set to %d" % up_pos)

    elif action == 'sd':
        down_pos = int(parts[1]) if len(parts) > 1 else motor.position
        print("  DOWN position set to %d" % down_pos)

    elif action == 'zero':
        motor.position = 0
        print("  Position reset to 0")

    elif action == 'off':
        motor.stop(stop_action='coast')
        print("  Motor released")

    elif action == 'show':
        print("  UP:   %d" % up_pos)
        print("  DOWN: %d" % down_pos)
        print("  Current: %d" % motor.position)

    else:
        print("  Unknown command.")
