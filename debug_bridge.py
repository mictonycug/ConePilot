#!/usr/bin/env python3
"""
ConePilot Debug Tool - Validates the TurtleBot connection and tests each subsystem.
Run from any machine on the same network as the TurtleBot.

Usage:
    python3 debug_bridge.py                          # auto-detect at default IP
    python3 debug_bridge.py http://172.20.10.3:8888  # specify URL
    python3 debug_bridge.py --wasd                   # jump straight to WASD control
"""

import json
import sys
import time
import urllib.request
import urllib.error

DEFAULT_URL = "http://172.20.10.3:8888"
LINEAR_SPEED = 0.10   # m/s - gentle test speed
ANGULAR_SPEED = 0.4   # rad/s - gentle test turn
TEST_DURATION = 0.3    # seconds - how long to pulse a test command
ODOM_SETTLE = 0.5      # seconds - wait for odom to update after movement


# ── helpers ─────────────────────────────────────────────────────────────────

def http_get(url):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.URLError as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def http_post(url, body=None):
    data = json.dumps(body or {}).encode()
    try:
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.URLError as e:
        return None, str(e)
    except Exception as e:
        return None, str(e)


def ok(msg):
    print(f"  [PASS] {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")


def info(msg):
    print(f"  [INFO] {msg}")


def header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ── checks ──────────────────────────────────────────────────────────────────

def check_bridge_reachable(base):
    header("1. Bridge Reachable")
    data, status = http_get(f"{base}/status")
    if data is None:
        fail(f"Cannot reach {base}/status  ->  {status}")
        fail("Is cone_bridge.py running? Is the IP correct?")
        return False
    if data.get("connected"):
        ok(f"Bridge is up at {base}")
    else:
        fail("Bridge responded but reports not connected")
        return False
    return True


def check_odom_alive(base):
    header("2. Odometry Feed")
    pose1, _ = http_get(f"{base}/odom")
    if pose1 is None:
        fail("Could not read /odom")
        return False
    info(f"Pose now: x={pose1['x']:.4f}  y={pose1['y']:.4f}  θ={pose1['theta']:.4f}")

    # Wait a moment and read again to see if odom is actually updating
    time.sleep(0.5)
    pose2, _ = http_get(f"{base}/odom")
    if pose2 is None:
        fail("Second /odom read failed")
        return False

    if pose1 == pose2:
        info("Odom values identical (robot may be stationary — that's OK)")
    else:
        ok("Odom is updating in real-time")
    ok(f"Odom endpoint working")
    return True


def check_cmd_vel(base):
    header("3. Velocity Command (cmd_vel)")
    info("Sending tiny forward pulse for 0.3s...")

    # Record pose before
    pose_before, _ = http_get(f"{base}/odom")
    if pose_before is None:
        fail("Cannot read odom before test")
        return False

    # Send forward velocity
    resp, status = http_post(f"{base}/cmd_vel", {"linear": LINEAR_SPEED, "angular": 0.0})
    if resp is None or not resp.get("ok"):
        fail(f"cmd_vel POST failed: {status}")
        return False
    ok("cmd_vel accepted by bridge")

    time.sleep(TEST_DURATION)

    # Stop
    resp, _ = http_post(f"{base}/stop")
    if resp and resp.get("ok"):
        ok("Stop command accepted")
    else:
        fail("Stop command failed — robot may still be moving!")

    time.sleep(ODOM_SETTLE)

    # Record pose after
    pose_after, _ = http_get(f"{base}/odom")
    if pose_after is None:
        fail("Cannot read odom after test")
        return False

    dx = pose_after['x'] - pose_before['x']
    dy = pose_after['y'] - pose_before['y']
    dist = (dx**2 + dy**2) ** 0.5

    info(f"Before: x={pose_before['x']:.4f}  y={pose_before['y']:.4f}")
    info(f"After:  x={pose_after['x']:.4f}  y={pose_after['y']:.4f}")
    info(f"Moved:  {dist:.4f} m")

    if dist > 0.005:
        ok(f"Robot physically moved {dist:.4f}m — motors confirmed working")
        return True
    else:
        fail("Robot did NOT move. Check:")
        fail("  - Is the robot on the ground (not lifted)?")
        fail("  - Is robot.launch.py running in another terminal?")
        fail("  - Does `ros2 topic list` show /cmd_vel?")
        return False


def check_navigate(base):
    header("4. Navigate Endpoint")
    # Just check the endpoint accepts a request (don't actually navigate far)
    pose, _ = http_get(f"{base}/odom")
    if pose is None:
        fail("Cannot read odom")
        return False

    # Navigate to current position (should instantly succeed)
    resp, _ = http_post(f"{base}/navigate", {"x": pose['x'], "y": pose['y']})
    if resp and resp.get("ok"):
        ok("Navigate endpoint responding")
    else:
        fail("Navigate endpoint failed")
        return False

    time.sleep(0.5)
    status, _ = http_get(f"{base}/status")
    if status and not status.get("navigating"):
        ok("Navigation to current pose completed immediately (as expected)")
    else:
        info("Navigation still in progress (may be fine if odom is noisy)")
    return True


# ── WASD interactive control ────────────────────────────────────────────────

def wasd_control(base):
    header("WASD Manual Control")
    print("""
  Controls:
    W = forward    S = backward
    A = turn left  D = turn right
    Q = quit

  Each keypress sends a short velocity pulse.
  Robot pose is printed after each command.
""")

    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    keymap = {
        'w': (LINEAR_SPEED, 0.0),
        's': (-LINEAR_SPEED, 0.0),
        'a': (0.0, ANGULAR_SPEED),
        'd': (0.0, -ANGULAR_SPEED),
    }

    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1).lower()
            if ch == 'q':
                http_post(f"{base}/stop")
                print("\r\nStopped. Exiting WASD mode.\r\n")
                break

            if ch in keymap:
                lin, ang = keymap[ch]
                label = {'w': 'FWD', 's': 'REV', 'a': 'LEFT', 'd': 'RIGHT'}[ch]

                # Send velocity
                resp, _ = http_post(f"{base}/cmd_vel", {"linear": lin, "angular": ang})
                if resp is None or not resp.get("ok"):
                    print(f"\r  [{label}] SEND FAILED\r\n")
                    continue

                time.sleep(TEST_DURATION)
                http_post(f"{base}/stop")

                # Read pose
                pose, _ = http_get(f"{base}/odom")
                if pose:
                    print(
                        f"\r  [{label}]  x={pose['x']:.3f}  y={pose['y']:.3f}  "
                        f"θ={pose['theta']:.3f}\r\n",
                        end="",
                    )
                else:
                    print(f"\r  [{label}]  sent ok, odom read failed\r\n", end="")
    except KeyboardInterrupt:
        http_post(f"{base}/stop")
        print("\r\nInterrupted. Stopped.\r\n")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# ── main ────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    base = DEFAULT_URL
    wasd_only = False

    for arg in args:
        if arg.startswith("http"):
            base = arg.rstrip("/")
        elif arg == "--wasd":
            wasd_only = True

    if wasd_only:
        if not check_bridge_reachable(base):
            sys.exit(1)
        wasd_control(base)
        return

    print(f"\nConePilot Debug Tool")
    print(f"Target: {base}\n")

    results = {}
    results['bridge'] = check_bridge_reachable(base)
    if not results['bridge']:
        print("\n[ABORT] Bridge not reachable. Fix this first.\n")
        sys.exit(1)

    results['odom'] = check_odom_alive(base)
    results['cmd_vel'] = check_cmd_vel(base)
    results['navigate'] = check_navigate(base)

    # Summary
    header("Summary")
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name:12s}  [{status}]")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n  All checks passed! Robot is ready.")
        print("  Run with --wasd to test manual control.\n")
    else:
        print("\n  Some checks failed. See details above.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
