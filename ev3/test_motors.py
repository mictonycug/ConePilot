#!/usr/bin/env python3
"""
Test which motors are connected and run them individually.
Usage: python3 test_motors.py
"""
import ev3dev.ev3 as ev3

LargeMotor = ev3.LargeMotor
MediumMotor = ev3.MediumMotor

PORTS = {
    'outA': 'outA',
    'outB': 'outB',
    'outC': 'outC',
    'outD': 'outD',
}

print("=" * 40)
print("  EV3 Motor Test")
print("=" * 40)

found = {}
for name, port in PORTS.items():
    for MotorClass in [LargeMotor, MediumMotor]:
        try:
            m = MotorClass(port)
            if m.connected:
                kind = "Large" if MotorClass == LargeMotor else "Medium"
                found[name] = (m, kind)
                print("  [OK]  %s: %sMotor  (position=%d)" % (name, kind, m.position))
                break
        except Exception:
            pass
    else:
        print("  [--]  %s: not connected" % name)

if not found:
    print("\nNo motors found!")
    exit(1)

print("\nFound %d motor(s).\n" % len(found))

while True:
    cmd = input("Command (port speed degrees | r port | q): ").strip()
    if cmd == 'q':
        break

    parts = cmd.split()

    # Reset position: r outA
    if parts[0] == 'r' and len(parts) == 2:
        port = parts[1]
        if port in found:
            found[port][0].position = 0
            print("  Reset %s position to 0" % port)
        else:
            print("  %s not connected" % port)
        continue

    if len(parts) < 3:
        print("  Usage: outA 200 360   (port speed degrees)")
        print("         r outA         (reset position)")
        print("         q              (quit)")
        continue

    port, speed, degrees = parts[0], int(parts[1]), int(parts[2])
    if port not in found:
        print("  %s not connected" % port)
        continue

    motor, kind = found[port]
    print("  Running %s (%s) at speed=%d for %d degrees..." % (port, kind, speed, degrees))
    motor.run_to_rel_pos(speed_sp=speed, position_sp=degrees, stop_action='hold')
    motor.wait_until_not_moving(timeout=10000)
    print("  Done. Position: %d" % motor.position)
