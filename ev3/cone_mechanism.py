#!/usr/bin/env python3
"""
EV3 Cone Mechanism HTTP Server.

Uses the working motor functions from test2.py.
Exposes HTTP endpoints for the TurtleBot's cone_bridge to call.

Endpoints:
  GET  /status     - mechanism state
  POST /place      - drop cone(s)
  POST /pickup     - pick up a cone (lower + reverse spiral + raise)
  POST /calibrate  - reset motors to home position

Usage: python3 cone_mechanism.py [--port 8080]
"""
import json
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import ev3dev.ev3 as ev3

# ── Motor config (from test2.py) ──────────────────────────
COLUMN_PORT = 'outA'
COLUMN_DIRECTION = 1
COLUMN_SPEED = 200
COLUMN_POS_TOP = 200
COLUMN_POS_TOP_PICKUP = 260  # raised pickup height, used during pickup
COLUMN_POS_BOTTOM = -200

SPIRALS_PORT = 'outB'
SPIRALS_DIRECTION = -1
SPIRALS_ABS_POS = 180
SPIRALS_SPEED = 720
SPIRALS_STEP = SPIRALS_DIRECTION * 360
SPIRALS_DROP_OFFSET = 30
SPIRALS_PICKUP_OFFSET = 0

# ── Motor functions (from test2.py) ───────────────────────
column = None
spirals = None
cones = 0
spirals_abs_pos = 0
busy = False
last_action = None
last_error = None


def run_column(pos):
    column.run_to_abs_pos(speed_sp=COLUMN_SPEED, position_sp=(COLUMN_DIRECTION * pos))


def column_reset():
    run_column(COLUMN_POS_TOP)
    time.sleep(3)


def column_down():
    run_column(COLUMN_POS_BOTTOM)
    time.sleep(3)


def column_up():
    run_column(COLUMN_POS_TOP)
    time.sleep(3)


def run_spirals_drop(cone_no):
    """Move spiral one step for dropping (with base offset)."""
    if cone_no == 0:
        spirals_reset()
    else:
        spirals.run_to_abs_pos(speed_sp=SPIRALS_SPEED,
                           position_sp=(SPIRALS_ABS_POS + SPIRALS_DROP_OFFSET + cone_no * SPIRALS_STEP))


def run_spirals_pickup(cone_no):
    """Move spiral one step for picking up (with base offset)."""
    spirals.run_to_abs_pos(speed_sp=SPIRALS_SPEED,
                           position_sp=(SPIRALS_ABS_POS + SPIRALS_PICKUP_OFFSET + cone_no * SPIRALS_STEP))


def spirals_reset():
    spirals.run_to_abs_pos(speed_sp=SPIRALS_SPEED, position_sp=SPIRALS_ABS_POS)


def do_place():
    """Drop a cone: column stays up, spin spiral one step to release cone."""
    global cones, spirals_abs_pos, busy, last_action, last_error
    if busy:
        return False, 'mechanism busy'
    busy = True
    last_error = None
    try:
        cones = max(0, cones - 1)
        print("[PLACE] cones=%d  spinning spiral (dropping cone)..." % cones)
        run_spirals_drop(cones)
        time.sleep(3)
        spirals_abs_pos = spirals.position
        last_action = 'placed cone (remaining: %d)' % cones
        print("[PLACE] done. spiral abs_pos=%d actual=%d" % (spirals_abs_pos, spirals.position))
        return True, last_action
    except Exception as e:
        last_error = str(e)
        return False, str(e)
    finally:
        busy = False


def do_pickup():
    """Pick up a cone: lower column + spin spiral one step (screw on) + raise."""
    global cones, spirals_abs_pos, busy, last_action, last_error
    if busy:
        return False, 'mechanism busy'
    busy = True
    last_error = None
    try:
        cones += 1
        print("[PICKUP] cones=%d  lowering..." % cones)
        column_down()
        print("[PICKUP] spinning spiral forward (screwing on)...")
        run_spirals_pickup(cones)
        time.sleep(3)
        spirals_abs_pos = spirals.position
        print("[PICKUP] raising (pickup height)...")
        run_column(COLUMN_POS_TOP_PICKUP)
        time.sleep(3)
        last_action = 'picked up cone (total: %d)' % cones
        print("[PICKUP] done.")
        return True, last_action
    except Exception as e:
        last_error = str(e)
        return False, str(e)
    finally:
        busy = False


def do_calibrate():
    """Reset motors to home position."""
    global cones, spirals_abs_pos, busy, last_action
    if busy:
        return False, 'mechanism busy'
    busy = True
    try:
        print("[CALIBRATE] resetting...")
        column_reset()
        spirals_reset()
        cones = 0
        spirals_abs_pos = 0
        last_action = 'calibrated'
        print("[CALIBRATE] done.")
        return True, 'motors reset'
    finally:
        busy = False


def get_status():
    return {
        'ready': not busy,
        'busy': busy,
        'cones': cones,
        'spirals_abs_pos': spirals_abs_pos,
        'spiral_position': spirals.position if spirals else None,
        'column_position': column.position if column else None,
        'last_action': last_action,
        'last_error': last_error,
    }


# ── HTTP Server ───────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print("  [%s] %s" % (self.client_address[0], args[0]))

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/status':
            self._json(get_status())
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        if self.path == '/place':
            # Run in thread so HTTP responds quickly
            def run():
                ok, msg = do_place()
            if busy:
                self._json({'ok': False, 'msg': 'mechanism busy'}, 409)
            else:
                threading.Thread(target=run, daemon=True).start()
                time.sleep(0.1)
                self._json({'ok': True, 'msg': 'placing cone'})

        elif self.path == '/pickup':
            def run():
                ok, msg = do_pickup()
            if busy:
                self._json({'ok': False, 'msg': 'mechanism busy'}, 409)
            else:
                threading.Thread(target=run, daemon=True).start()
                time.sleep(0.1)
                self._json({'ok': True, 'msg': 'picking up cone'})

        elif self.path == '/calibrate':
            def run():
                ok, msg = do_calibrate()
            if busy:
                self._json({'ok': False, 'msg': 'mechanism busy'}, 409)
            else:
                threading.Thread(target=run, daemon=True).start()
                time.sleep(0.1)
                self._json({'ok': True, 'msg': 'calibrating'})

        else:
            self._json({'error': 'not found'}, 404)


# ── Main ──────────────────────────────────────────────────
def main():
    global column, spirals

    port = 8080
    if '--port' in sys.argv:
        idx = sys.argv.index('--port')
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    print("Initializing motors...")
    column = ev3.LargeMotor(COLUMN_PORT)
    spirals = ev3.LargeMotor(SPIRALS_PORT)
    column.stop_action = 'brake'
    spirals.stop_action = 'brake'

    if not column.connected:
        print("Column not connected on " + COLUMN_PORT)
        sys.exit(1)
    if not spirals.connected:
        print("Spirals not connected on " + SPIRALS_PORT)
        sys.exit(1)

    print("Column:  %s (pos=%d)" % (COLUMN_PORT, column.position))
    print("Spirals: %s (pos=%d)" % (SPIRALS_PORT, spirals.position))

    print("Calibrating...")
    column_reset()
    spirals_reset()
    print("Ready!")
    print("")

    server = HTTPServer(('0.0.0.0', port), Handler)
    print("EV3 Cone Mechanism server on port %d" % port)
    print("  GET  /status")
    print("  POST /place")
    print("  POST /pickup")
    print("  POST /calibrate")
    print("")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        column.stop()
        spirals.stop()


if __name__ == '__main__':
    main()
