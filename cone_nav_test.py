#!/usr/bin/env python3
"""
Cone Navigation Test — no EV3, no pickup.

Drives to cones one by one, stops when it reaches each one, logs results.
Use this to tune/validate navigation before involving the arm.

States: SCANNING → LOCKED (centre) → DRIVING (straight) → BLIND_APPROACH → REACHED → SCANNING

Live camera:  http://<turtlebot-ip>:9091/
Results printed to terminal and saved to /tmp/cone_nav_results.json

Usage:
    python3 cone_nav_test.py
    python3 cone_nav_test.py --max-cones 3
    python3 cone_nav_test.py --no-display
"""
import argparse
import json
import math
import os
import threading
import time
from enum import Enum, auto
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import rclpy
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node

from cone_detector import (
    CAMERA_DFOV_DEG,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    KNOWN_WIDTH_MM,
    compute_focal_length_px,
    detect_red_cones,
    draw_detections,
    estimate_distance,
    load_calibration,
)

# ── Speeds ─────────────────────────────────────────────────────────────
LINEAR_SPEED      = 0.15
SLOW_SPEED        = 0.07
SCAN_ANGULAR      = 0.30
ANGULAR_SPEED_MAX = 0.80
BEARING_GAIN      = 2.0
CENTRE_THRESH     = math.radians(10)

# ── Thresholds ─────────────────────────────────────────────────────────
ARRIVE_DIST       = 0.30   # safety: go blind even if still visible
SLOW_DIST         = 0.60

# ── Blind approach ─────────────────────────────────────────────────────
BLIND_DURATION    = 3.0
BLIND_SPEED       = 0.10

# ── Tracker ────────────────────────────────────────────────────────────
CONFIRM_FRAMES    = 4
EXPIRE_FRAMES     = 6
MATCH_BRG_DEG     = 12.0
MATCH_DIST_RATIO  = 0.40
LOCK_LOST_FRAMES  = 3

# ── Detection filters ──────────────────────────────────────────────────
MIN_DIST_M        = 0.05
MAX_DIST_M        = 4.0
MIN_ASPECT        = 0.3
MAX_ASPECT        = 12.0
CROSS_LO          = 0.25
CROSS_HI          = 3.50

VISITED_RADIUS    = 0.50

MJPEG_PORT        = 9091   # different port so it doesn't clash with cone_chaser_v2
RESULTS_FILE      = '/tmp/cone_nav_results.json'


# ═══════════════════════════════════════════════════════════════════════
# MJPEG streamer
# ═══════════════════════════════════════════════════════════════════════

class MJPEGStreamer:
    def __init__(self, port):
        self._lock = threading.Lock()
        self._jpg  = None
        self._port = port
        self._start()
        print(f'[MJPEG] http://0.0.0.0:{port}/')

    def push(self, frame):
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with self._lock:
            self._jpg = buf.tobytes()

    def _latest(self):
        with self._lock:
            return self._jpg

    def _start(self):
        s = self
        class H(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                if self.path == '/stream':
                    self._stream()
                elif self.path in ('/', '/view'):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    self.wfile.write(
                        b'<html><body style="background:#000;margin:0">'
                        b'<img src="/stream" style="width:100%;display:block">'
                        b'</body></html>')
                else:
                    self.send_response(404); self.end_headers()

            def _stream(self):
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                try:
                    while True:
                        jpg = s._latest()
                        if jpg:
                            self.wfile.write(
                                b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                                + jpg + b'\r\n')
                        time.sleep(0.05)
                except Exception:
                    pass

        threading.Thread(target=HTTPServer(('0.0.0.0', self._port), H).serve_forever,
                         daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
# Cone tracker
# ═══════════════════════════════════════════════════════════════════════

class TrackedCone:
    def __init__(self, bearing, distance):
        self.bearing   = bearing
        self.distance  = distance
        self.hits      = 1
        self.misses    = 0
        self.confirmed = False

    def update(self, bearing, distance):
        self.bearing  = bearing
        self.distance = distance
        self.hits    += 1
        self.misses   = 0
        if self.hits >= CONFIRM_FRAMES:
            self.confirmed = True

    def miss(self):
        self.misses += 1

    @property
    def expired(self):
        return self.misses >= EXPIRE_FRAMES


class ConeTracker:
    def __init__(self):
        self.tracks = []

    def update(self, detections):
        matched_t, matched_d = set(), set()
        pairs = []
        for di, (db, dd) in enumerate(detections):
            for ti, tr in enumerate(self.tracks):
                bd  = abs(math.degrees(db - tr.bearing))
                avg = (dd + tr.distance) / 2.0
                dr  = abs(dd - tr.distance) / avg if avg > 0 else 999
                pairs.append((bd + dr * 30, di, ti, db, dd))
        pairs.sort()
        for score, di, ti, db, dd in pairs:
            if di in matched_d or ti in matched_t:
                continue
            bd  = abs(math.degrees(db - self.tracks[ti].bearing))
            avg = (dd + self.tracks[ti].distance) / 2.0
            dr  = abs(dd - self.tracks[ti].distance) / avg if avg > 0 else 999
            if bd < MATCH_BRG_DEG and dr < MATCH_DIST_RATIO:
                self.tracks[ti].update(db, dd)
                matched_t.add(ti); matched_d.add(di)
        for ti, tr in enumerate(self.tracks):
            if ti not in matched_t:
                tr.miss()
        for di, det in enumerate(detections):
            if di not in matched_d:
                self.tracks.append(TrackedCone(*det))
        self.tracks = [t for t in self.tracks if not t.expired]

    def confirmed_list(self):
        return [t for t in self.tracks if t.confirmed]


# ═══════════════════════════════════════════════════════════════════════
# State machine
# ═══════════════════════════════════════════════════════════════════════

class State(Enum):
    SCANNING       = auto()
    LOCKED         = auto()
    BLIND_APPROACH = auto()
    REACHED        = auto()   # stopped at cone — log result, short pause, next
    COMPLETE       = auto()


# ═══════════════════════════════════════════════════════════════════════
# ROS2 node
# ═══════════════════════════════════════════════════════════════════════

class ConeNavTestNode(Node):

    def __init__(self, camera_index, no_display, max_cones):
        super().__init__(f'cone_nav_test_{os.getpid()}')
        self.no_display = no_display
        self.max_cones  = max_cones

        # Camera
        self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            raise SystemExit('Could not open camera')
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        self.frame_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cal = load_calibration()
        self.focal = cal if cal else compute_focal_length_px(
            self.frame_w, self.frame_h, CAMERA_DFOV_DEG)
        self.get_logger().info(f'Camera {self.frame_w}×{self.frame_h}  focal={self.focal:.1f}px')

        # ROS2
        self.cmd_pub = self.create_publisher(TwistStamped, '/cmd_vel', 10)
        self.create_subscription(Odometry, '/odom', self._odom_cb, 10)

        # Pose
        self.robot_x = self.robot_y = self.robot_theta = 0.0

        # State
        self.state        = State.SCANNING
        self.tracker      = ConeTracker()
        self.visited      = []
        self.cones_done   = 0
        self.results      = []   # list of dicts, one per cone attempt

        # Scanning
        self._scan_start = None
        self._scan_last  = None
        self._scan_rot   = 0.0

        # Locked
        self._locked_bearing  = 0.0
        self._locked_distance = 0.0
        self._locked_driving  = False
        self._lock_lost_count = 0

        # Blind
        self._blind_start = None

        # Reached — short pause before scanning again
        self._reached_time = None

        # MJPEG
        self.streamer = MJPEGStreamer(MJPEG_PORT)

        self._last_loop = time.time()
        self.create_timer(0.5, self._watchdog)
        self.create_timer(0.1, self._loop)
        self.get_logger().info('ConeNavTest ready — SCANNING')

    # ── Odometry ───────────────────────────────────────────────────────

    def _odom_cb(self, msg):
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        siny = 2.0 * (o.w * o.z + o.x * o.y)
        cosy = 1.0 - 2.0 * (o.y * o.y + o.z * o.z)
        self.robot_x     = p.x
        self.robot_y     = p.y
        self.robot_theta = math.atan2(siny, cosy)

    # ── Motion ─────────────────────────────────────────────────────────

    def _send(self, linear, angular):
        msg = TwistStamped()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = 'base_link'
        msg.twist.linear.x  = float(linear)
        msg.twist.angular.z = float(max(-ANGULAR_SPEED_MAX,
                                        min(ANGULAR_SPEED_MAX, angular)))
        self.cmd_pub.publish(msg)

    def _stop(self):
        self._send(0.0, 0.0)

    def _watchdog(self):
        if time.time() - self._last_loop > 0.5:
            self._stop()

    # ── Detection helpers ──────────────────────────────────────────────

    def _bearing(self, x, w):
        return math.atan2(x + w / 2.0 - self.frame_w / 2.0, self.focal)

    def _filter(self, x, y, w, h, area):
        if h <= 0 or not (MIN_ASPECT <= w / h <= MAX_ASPECT):
            return None
        dist_mm, _ = estimate_distance(x, y, w, h, self.focal, self.frame_w)
        dist_m = dist_mm / 1000.0
        if not (MIN_DIST_M <= dist_m <= MAX_DIST_M):
            return None
        if dist_mm > 0 and w > 0:
            ratio = (KNOWN_WIDTH_MM * self.focal) / dist_mm / w
            if not (CROSS_LO <= ratio <= CROSS_HI):
                return None
        return (self._bearing(x, w), dist_m)

    # ── Visited dedup ──────────────────────────────────────────────────

    def _is_visited(self, bearing, distance):
        cx = self.robot_x + distance * math.cos(self.robot_theta + bearing)
        cy = self.robot_y + distance * math.sin(self.robot_theta + bearing)
        return any(math.hypot(cx - vx, cy - vy) < VISITED_RADIUS
                   for vx, vy in self.visited)

    def _pick_nearest(self, confirmed):
        candidates = [c for c in confirmed
                      if not self._is_visited(c.bearing, c.distance)]
        return min(candidates, key=lambda c: c.distance) if candidates else None

    # ── State handlers ─────────────────────────────────────────────────

    def _do_scanning(self, confirmed):
        if self._scan_start is None:
            self._scan_start = self.robot_theta
            self._scan_last  = self.robot_theta
            self._scan_rot   = 0.0

        delta = self._norm(self.robot_theta - self._scan_last)
        self._scan_rot  += abs(delta)
        self._scan_last  = self.robot_theta

        target = self._pick_nearest(confirmed)
        if target is not None:
            self._locked_bearing  = target.bearing
            self._locked_distance = target.distance
            self._locked_driving  = False
            self._lock_lost_count = 0
            self.state       = State.LOCKED
            self._scan_start = None
            self.get_logger().info(
                f'LOCKED  brg={math.degrees(target.bearing):+.1f}°  dist={target.distance:.2f}m')
            return

        if self._scan_rot > 2 * math.pi:
            self.get_logger().info('Full scan — no cones → COMPLETE')
            self.state = State.COMPLETE
            self._stop()
            return

        self._send(0.0, SCAN_ANGULAR)

    def _do_locked(self, confirmed):
        # Re-acquire
        best_match = None
        best_bd    = MATCH_BRG_DEG * 2
        for cone in confirmed:
            bd = abs(math.degrees(cone.bearing - self._locked_bearing))
            if bd < best_bd:
                best_bd    = bd
                best_match = cone

        if not self._locked_driving:
            # Phase 1: CENTERING — turn only
            if best_match is not None:
                self._locked_bearing  = best_match.bearing
                self._locked_distance = best_match.distance
                self._lock_lost_count = 0
            else:
                self._lock_lost_count += 1

            if self._lock_lost_count >= LOCK_LOST_FRAMES:
                self.get_logger().info('Lost cone while centering → SCANNING')
                self.tracker     = ConeTracker()
                self._scan_start = None
                self.state       = State.SCANNING
                return

            angular = max(-ANGULAR_SPEED_MAX,
                          min(ANGULAR_SPEED_MAX, -BEARING_GAIN * self._locked_bearing))
            self._send(0.0, angular)

            if abs(self._locked_bearing) < CENTRE_THRESH:
                self._locked_driving = True
                self.get_logger().info(
                    f'Centred — driving straight  dist={self._locked_distance:.2f}m')

        else:
            # Phase 2: DRIVING STRAIGHT — go blind once cone is gone for a few frames
            if best_match is not None:
                self._locked_distance = best_match.distance  # update distance only
                self._lock_lost_count = 0
            else:
                self._lock_lost_count += 1
                if self._lock_lost_count >= LOCK_LOST_FRAMES:
                    self.get_logger().info(
                        f'→ BLIND_APPROACH (cone gone  dist={self._locked_distance:.2f}m)')
                    self._go_blind()
                    return

            if self._locked_distance < ARRIVE_DIST:
                self.get_logger().info(
                    f'→ BLIND_APPROACH (arrived  dist={self._locked_distance:.2f}m)')
                self._go_blind()
                return

            speed = SLOW_SPEED if self._locked_distance < SLOW_DIST else LINEAR_SPEED
            self._send(speed, 0.0)

    def _go_blind(self):
        self.state        = State.BLIND_APPROACH
        self._blind_start = time.time()

    def _do_blind(self):
        elapsed = time.time() - self._blind_start
        if elapsed < BLIND_DURATION:
            self._send(BLIND_SPEED, 0.0)
        else:
            self._stop()
            self._on_reached()

    def _on_reached(self):
        """Called when we've reached a cone position. Log result."""
        self.cones_done += 1
        self.visited.append((self.robot_x, self.robot_y))

        result = {
            'cone': self.cones_done,
            'x': round(self.robot_x, 3),
            'y': round(self.robot_y, 3),
            'time': time.strftime('%H:%M:%S'),
            'status': 'reached',
        }
        self.results.append(result)

        print(f'\n{"─"*50}')
        print(f'  ✓ CONE {self.cones_done} REACHED')
        print(f'    position: ({self.robot_x:.2f}, {self.robot_y:.2f})')
        print(f'{"─"*50}\n')

        self._save_results()

        self.state         = State.REACHED
        self._reached_time = time.time()

    def _do_reached(self):
        """Sit still for 1.5s so it's clear we stopped, then scan for next."""
        self._stop()
        if time.time() - self._reached_time < 1.5:
            return

        if self.max_cones > 0 and self.cones_done >= self.max_cones:
            self.get_logger().info('Target count reached → COMPLETE')
            self.state = State.COMPLETE
        else:
            self.tracker     = ConeTracker()
            self._scan_start = None
            self.state       = State.SCANNING
            self.get_logger().info('Scanning for next cone…')

    def _save_results(self):
        try:
            with open(RESULTS_FILE, 'w') as f:
                json.dump({
                    'cones_reached': self.cones_done,
                    'max_cones':     self.max_cones,
                    'results':       self.results,
                }, f, indent=2)
        except Exception:
            pass

    # ── Main loop ──────────────────────────────────────────────────────

    @staticmethod
    def _norm(a):
        while a >  math.pi: a -= 2 * math.pi
        while a < -math.pi: a += 2 * math.pi
        return a

    def _loop(self):
        self._last_loop = time.time()

        ret, frame = self.cap.read()
        if not ret:
            return

        detections, rejected, _ = detect_red_cones(frame)
        filtered = []
        for (x, y, w, h, area, _e) in detections:
            r = self._filter(x, y, w, h, area)
            if r:
                filtered.append(r)
        self.tracker.update(filtered)
        confirmed = self.tracker.confirmed_list()

        if   self.state == State.SCANNING:       self._do_scanning(confirmed)
        elif self.state == State.LOCKED:         self._do_locked(confirmed)
        elif self.state == State.BLIND_APPROACH: self._do_blind()
        elif self.state == State.REACHED:        self._do_reached()
        elif self.state == State.COMPLETE:       self._stop()

        self._draw(frame, detections, rejected, confirmed)
        self.streamer.push(frame)

        if not self.no_display:
            cv2.imshow('Cone Nav Test', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                raise SystemExit(0)

    # ── Annotation ─────────────────────────────────────────────────────

    def _draw(self, frame, detections, rejected, confirmed):
        draw_detections(frame, detections, rejected, self.focal)

        h, w = frame.shape[:2]
        cx   = w // 2

        STATE_COL = {
            State.SCANNING:       (180, 180,   0),
            State.LOCKED:         (  0, 200, 255),
            State.BLIND_APPROACH: (  0, 100, 255),
            State.REACHED:        (  0, 220,   0),
            State.COMPLETE:       (  0, 220,   0),
        }
        sc = STATE_COL.get(self.state, (255, 255, 255))

        for cone in confirmed:
            px = int(cx + self.focal * math.tan(cone.bearing))
            px = max(0, min(w - 1, px))
            is_target = (self.state in (State.LOCKED, State.BLIND_APPROACH) and
                         abs(math.degrees(cone.bearing - self._locked_bearing)) < 20)
            col = (0, 0, 255) if is_target else (0, 220, 0)
            cv2.line(frame, (px, 0), (px, h - 40), col, 2 if is_target else 1)
            label = f'{cone.distance:.2f}m'
            if is_target:
                label += ' ◄'
            cv2.putText(frame, label, (px + 4, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, col, 1)

        if self.state == State.BLIND_APPROACH and self._blind_start:
            pct = min(1.0, (time.time() - self._blind_start) / BLIND_DURATION)
            cv2.rectangle(frame, (0, h - 6), (int(w * pct), h), (0, 100, 255), -1)

        max_str = str(self.max_cones) if self.max_cones > 0 else '∞'
        parts = [
            f'[TEST] {self.state.name}',
            f'cones {self.cones_done}/{max_str}',
            f'tracks {len(self.tracker.tracks)}  confirmed {len(confirmed)}',
        ]
        if self.state == State.LOCKED:
            phase = 'CENTERING' if not self._locked_driving else 'DRIVING'
            parts.append(f'{phase}  brg {math.degrees(self._locked_bearing):+.1f}°'
                         f'  dist {self._locked_distance:.2f}m')
        if self.state == State.BLIND_APPROACH and self._blind_start:
            parts.append(f'blind {time.time()-self._blind_start:.1f}/{BLIND_DURATION:.0f}s')

        cv2.rectangle(frame, (0, h - 36), (w, h - 6), (0, 0, 0), -1)
        cv2.putText(frame, '  |  '.join(parts), (8, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, sc, 1)

    # ── Cleanup ────────────────────────────────────────────────────────

    def destroy_node(self):
        try:
            self._stop()
        except Exception:
            pass
        self.cap.release()
        if not self.no_display:
            cv2.destroyAllWindows()

        # Final summary
        print(f'\n{"═"*50}')
        print(f'  CONE NAV TEST — RESULTS')
        print(f'{"═"*50}')
        print(f'  Cones reached: {self.cones_done}' +
              (f'/{self.max_cones}' if self.max_cones > 0 else ''))
        for r in self.results:
            print(f'  #{r["cone"]}  ({r["x"]:.2f}, {r["y"]:.2f})  {r["time"]}  {r["status"]}')
        print(f'  Results saved → {RESULTS_FILE}')
        print(f'{"═"*50}\n')
        self._save_results()
        super().destroy_node()


# ═══════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser('Cone Navigation Test (no EV3)')
    parser.add_argument('--no-display', action='store_true',
                        help='Headless — MJPEG stream only')
    parser.add_argument('--max-cones', type=int, default=0,
                        help='Stop after N cones (0 = unlimited)')
    parser.add_argument('--camera', type=int, default=0,
                        help='Camera device index')
    args = parser.parse_args()

    print(f'\nCone Nav Test')
    print(f'  Camera feed : http://<robot-ip>:{MJPEG_PORT}/')
    print(f'  Results file: {RESULTS_FILE}')
    print(f'  Max cones   : {args.max_cones or "unlimited"}')
    print()

    rclpy.init()
    node = ConeNavTestNode(
        camera_index=args.camera,
        no_display=args.no_display,
        max_cones=args.max_cones,
    )
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
