#!/usr/bin/env python3
"""
Spiral position calibrator.

Moves the spiral motor slowly so you can dial in the exact home position.
When you confirm, it writes the value directly into cone_mechanism.py.

Usage: python3 calibrate_spirals.py

Controls:
  f        run forward slowly (keep typing f or hold it)
  b        run backward slowly
  s        stop motor
  Enter    confirm current position → saves to cone_mechanism.py
  q        quit without saving
"""
import os
import re
import sys
import time
import ev3dev.ev3 as ev3

SPIRALS_PORT = 'outB'
CALIB_SPEED  = 80   # very slow for precise positioning

# Path to the config file we'll patch
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cone_mechanism.py')


def save_position(pos):
    """Patch SPIRALS_ABS_POS in cone_mechanism.py with the new value."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            src = f.read()
        new_src = re.sub(
            r'(SPIRALS_ABS_POS\s*=\s*)-?\d+',
            r'\g<1>%d' % pos,
            src
        )
        if new_src == src:
            print("  WARNING: SPIRALS_ABS_POS not found in %s" % CONFIG_FILE)
            return False
        with open(CONFIG_FILE, 'w') as f:
            f.write(new_src)
        return True
    except Exception as e:
        print("  ERROR saving: %s" % e)
        return False


def main():
    print("Connecting to spiral motor on %s..." % SPIRALS_PORT)
    motor = ev3.LargeMotor(SPIRALS_PORT)
    motor.stop_action = 'hold'

    if not motor.connected:
        print("ERROR: Motor not connected on %s" % SPIRALS_PORT)
        sys.exit(1)

    print()
    print("================================")
    print("   SPIRAL CALIBRATION TOOL")
    print("================================")
    print("  f        run forward slowly")
    print("  b        run backward slowly")
    print("  s        stop")
    print("  Enter    save position as home")
    print("  q        quit without saving")
    print()
    print("  Will save to: %s" % CONFIG_FILE)
    print()

    while True:
        try:
            cmd = input("pos=%-6d > " % motor.position).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            motor.stop()
            print("Aborted. Position not saved.")
            break

        if cmd in ('q', 'quit'):
            motor.stop()
            print("Quit. Position not saved. Final position: %d" % motor.position)
            break

        elif cmd in ('f', 'forward'):
            motor.run_forever(speed_sp=CALIB_SPEED)
            print("  running forward... (type s to stop)")

        elif cmd in ('b', 'backward', 'back'):
            motor.run_forever(speed_sp=-CALIB_SPEED)
            print("  running backward... (type s to stop)")

        elif cmd in ('s', 'stop'):
            motor.stop()
            print("  stopped at position %d" % motor.position)

        elif cmd == '':
            # Enter = confirm and save
            motor.stop()
            pos = motor.position
            print()
            print("  Saving SPIRALS_ABS_POS = %d ..." % pos)
            if save_position(pos):
                print("  Saved to %s" % CONFIG_FILE)
                print("  Restart cone_mechanism.py to apply.")
            else:
                print("  Save failed — update SPIRALS_ABS_POS manually to %d" % pos)
            break

        else:
            print("  unknown — try f, b, s, Enter, or q")


if __name__ == '__main__':
    main()
