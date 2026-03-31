#!/usr/bin/env python3
"""
Cone Chaser v2 — lock-on, commit, blind straight approach, EV3 pickup.

Behaviour
---------
  SCANNING       Rotate in place. Build confirmed cone list. Pick nearest.
  LOCKED         Visual servo toward locked cone while it's visible.
                 Update bearing/distance each frame. No target-switching.
  BLIND_APPROACH Cone disappeared or we're very close — drive straight
                 at last heading for BLIND_DURATION seconds (no correction).
  PICKUP         Stop, call EV3 /pickup, wait, then scan for next cone.
  COMPLETE       All done, sit still.

Live camera feed (always on):
    http://<turtlebot-ip>:9090/         ← browser view
    http://<turtlebot-ip>:9090/stream   ← raw MJPEG

Usage:
    python3 cone_chaser_v2.py
    python3 cone_chaser_v2.py --max-cones 3
    python3 cone_chaser_v2.py --no-display          # headless, stream only
    python3 cone_chaser_v2.py --ev3 172.20.10.2:8080
"""
import argparse
import json
import math
import os
import threading
import time
import urllib.request
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

# ── Speeds ────────────────────────────────────────────────────────────
LINEAR_SPEED      = 0.15   # m/s normal approach
SLOW_SPEED        = 0.07   # m/s close approach
SCAN_ANGULAR      = 0.30   # rad/s scan rotation speed
ANGULAR_SPEED_MAX = 0.80   # rad/s hard cap on turns
BEARING_GAIN      = 2.0    # proportional gain on camera bearing error
CENTRE_THRESH     = math.radians(10)  # bearing below this → stop centering, start driving

# ── Approach thresholds ───────────────────────────────────────────────
ARRIVE_DIST       = 0.30   # m — safety: start blind even if cone still visible
SLOW_DIST         = 0.60   # m — within this → use SLOW_SPEED

# ── Blind approach ────────────────────────────────────────────────────
BLIND_DURATION    = 3.0    # s — drive straight after cone disappears
BLIND_SPEED       = 0.10   # m/s during blind run

# ── Cone tracker ──────────────────────────────────────────────────────
CONFIRM_FRAMES    = 4      # consecutive hits needed to confirm a cone
EXPIRE_FRAMES     = 6      # misses before a track is dropped
MATCH_BRG_DEG     = 12.0   # max bearing delta (°) to match a track
MATCH_DIST_RATIO  = 0.40   # max relative distance delta to match a track

# Loss threshold: frames without matching the locked cone → go blind
LOCK_LOST_FRAMES  = 3

# ── Detection filters ─────────────────────────────────────────────────
MIN_DIST_M        = 0.05
MAX_DIST_M        = 4.0
MIN_ASPECT        = 0.3
MAX_ASPECT        = 12.0
CROSS_LO          = 0.25   # predicted/actual pixel-width ratio bounds
CROSS_HI          = 3.50

# ── Visited dedup ─────────────────────────────────────────────────────
VISITED_RADIUS    = 0.50   # m — same-cone threshold

# ── MJPEG stream ──────────────────────────────────────────────────────
MJPEG_PORT        = 9090

# ── EV3 default ───────────────────────────────────────────────────────
EV3_DEFAULT       = '172.20.10.2:8080'


# ═════════════════════════════════════════════════════════════════════
# MJPEG streamer (runs in its own daemon thread)
# ═════════════════════════════════════════════════════════════════════

class MJPEGStreamer:
    """Push annotated frames here; any browser can watch the stream."""

    def __init__(self, port: int = MJPEG_PORT):
        self._lock = threading.Lock()
        self._jpg: bytes | None = None
        self._port = port
        self._serve()
        print(f'[MJPEG] stream → http://0.0.0.0:{port}/')

    def push(self, frame):
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with self._lock:
            self._jpg = buf.tobytes()

    def _latest(self):
        with self._lock:
            return self._jpg

    def _serve(self):
        s = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

            def do_GET(self):
                if self.path == '/stream':
                    self._mjpeg()
                elif self.path in ('/', '/view'):
                    self._page()
                else:
                    self.send_response(404); self.end_headers()

            def _page(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(
                    b'<html><body style="background:#000;margin:0">'
                    b'<img src="/stream" style="width:100%;display:block">'
                    b'</body></html>'
                )

            def _mjpeg(self):
                self.send_response(200)
                self.send_header('Content-Type',
                                 'multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                try:
                    while True:
                        jpg = s._latest()
                        if jpg:
                            self.wfile.write(
                                b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                                + jpg + b'\r\n'
                            )
                        time.sleep(0.05)
                except Exception:
                    pass

        srv = HTTPServer(('0.0.0.0', self._port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()


# ═════════════════════════════════════════════════════════════════════
# Temporal cone tracker
# ═════════════════════════════════════════════════════════════════════

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
        self.tracks: list[TrackedCone] = []

    def update(self, detections):
        """detections: list of (bearing_rad, dist_m)"""
        matched_t, matched_d = set(), set()
        pairs = []
        for di, (db, dd) in enumerate(detections):
            for ti, tr in enumerate(self.tracks):
                bd  = abs(math.degrees(db - tr.bearing))
                avg = (dd + tr.distance) / 2.0
                dr  = abs(dd - tr.distance) / avg if avg > 0 else 999
                pairs.append((bd + dr * 30, di, ti, db, dd, bd, dr))
        pairs.sort()
        for _, di, ti, db, dd, bd, dr in pairs:
            if di in matched_d or ti in matched_t:
                continue
            if bd < MATCH_BRG_DEG and dr < MATCH_DIST_RATIO:
                self.tracks[ti].update(db, dd)
                matched_t.add(ti)
                matched_d.add(di)
        for ti, tr in enumerate(self.tracks):
            if ti not in matched_t:
                tr.miss()
        for di, det in enumerate(detections):
            if di not in matched_d:
                self.tracks.append(TrackedCone(*det))
        self.tracks = [t for t in self.tracks if not t.expired]

    def confirmed(self) -> list[TrackedCone]:
        return [t for t in self.tracks if t.confirmed]


# ═════════════════════════════════════════════════════════════════════
# State machine
# ═════════════════════════════════════════════════════════════════════

class State(Enum):
    SCANNING       = auto()
    LOCKED         = auto()
    BLIND_APPROACH = auto()
    PICKUP         = auto()
    COMPLETE       = auto()


# ═════════════════════════════════════════════════════════════════════
# ROS2 node
# ═════════════════════════════════════════════════════════════════════

class ConeChaserNode(Node):

    def __init__(self, camera_index, no_display, max_cones, ev3_host,
                 status_file=None):
        super().__init__(f'cone_chaser_v2_{os.getpid()}')
        self.no_display  = no_display
        self.max_cones   = max_cones
        self.ev3_host    = ev3_host
        self.status_file = status_file

        # ── Camera ────────────────────────────────────────────────────
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
        self.get_logger().info(f'Camera {self.frame_w}×{self.frame_h}  '
                               f'focal={self.focal:.1f}px')

        # ── ROS2 ──────────────────────────────────────────────────────
        self.cmd_pub = self.create_publisher(TwistStamped, '/cmd_vel', 10)
        self.create_subscription(Odometry, '/odom', self._odom_cb, 10)

        # ── Robot pose ────────────────────────────────────────────────
        self.robot_x     = 0.0
        self.robot_y     = 0.0
        self.robot_theta = 0.0

        # ── State ─────────────────────────────────────────────────────
        self.state         = State.SCANNING
        self.tracker       = ConeTracker()
        self.visited: list[tuple[float, float]] = []
        self.cones_reached = 0

        # Results list for status file (grows as cones are collected)
        total = max_cones if max_cones > 0 else 0
        self._results = [{'cone_id': f'cone-{i}', 'status': 'pending'}
                         for i in range(total)]

        # Scanning
        self._scan_theta_start = None
        self._scan_theta_last  = None
        self._scan_total_rot   = 0.0

        # Locked
        self._locked_bearing  = 0.0
        self._locked_distance = 0.0
        self._locked_driving  = False  # False=centering, True=driving straight
        self._lock_lost_count = 0

        # Blind approach
        self._blind_start: float | None = None

        # Pickup (async)
        self._pickup_done   = False
        self._pickup_thread = None

        # ── MJPEG stream (always on) ───────────────────────────────────
        self.streamer = MJPEGStreamer(MJPEG_PORT)

        # ── Timers ────────────────────────────────────────────────────
        self._last_loop_t = time.time()
        self.create_timer(0.5, self._watchdog)
        self.create_timer(0.1, self._loop)

        self.get_logger().info('ConeChaserV2 ready — SCANNING')

    # ── ROS callbacks ─────────────────────────────────────────────────

    def _odom_cb(self, msg):
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        siny = 2.0 * (o.w * o.z + o.x * o.y)
        cosy = 1.0 - 2.0 * (o.y * o.y + o.z * o.z)
        self.robot_x     = p.x
        self.robot_y     = p.y
        self.robot_theta = math.atan2(siny, cosy)

    # ── Motion helpers ────────────────────────────────────────────────

    def _send(self, linear: float, angular: float):
        msg = TwistStamped()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = 'base_link'
        msg.twist.linear.x  = float(linear)
        msg.twist.angular.z = float(
            max(-ANGULAR_SPEED_MAX, min(ANGULAR_SPEED_MAX, angular)))
        self.cmd_pub.publish(msg)

    def _stop(self):
        self._send(0.0, 0.0)

    def _watchdog(self):
        if time.time() - self._last_loop_t > 0.5:
            self._stop()

    @staticmethod
    def _norm(a):
        while a >  math.pi: a -= 2 * math.pi
        while a < -math.pi: a += 2 * math.pi
        return a

    # ── Detection helpers ─────────────────────────────────────────────

    def _bearing(self, x, w):
        return math.atan2(x + w / 2.0 - self.frame_w / 2.0, self.focal)

    def _filter(self, x, y, w, h, area):
        if h <= 0:
            return None
        if not (MIN_ASPECT <= w / h <= MAX_ASPECT):
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

    # ── Visited dedup ─────────────────────────────────────────────────

    def _is_visited(self, bearing, distance):
        cx = self.robot_x + distance * math.cos(self.robot_theta + bearing)
        cy = self.robot_y + distance * math.sin(self.robot_theta + bearing)
        return any(math.hypot(cx - vx, cy - vy) < VISITED_RADIUS
                   for vx, vy in self.visited)

    def _mark_visited(self):
        self.visited.append((self.robot_x, self.robot_y))
        self.get_logger().info(
            f'Cone collected at ({self.robot_x:.2f},{self.robot_y:.2f}) '
            f'[{len(self.visited)} total]')

    def _pick_nearest(self, confirmed):
        candidates = [c for c in confirmed
                      if not self._is_visited(c.bearing, c.distance)]
        return min(candidates, key=lambda c: c.distance) if candidates else None

    # ── State handlers ────────────────────────────────────────────────

    def _do_scanning(self, confirmed):
        """Rotate until we see a confirmed cone, then lock on."""
        if self._scan_theta_start is None:
            self._scan_theta_start = self.robot_theta
            self._scan_theta_last  = self.robot_theta
            self._scan_total_rot   = 0.0

        delta = self._norm(self.robot_theta - self._scan_theta_last)
        self._scan_total_rot  += abs(delta)
        self._scan_theta_last  = self.robot_theta

        target = self._pick_nearest(confirmed)
        if target is not None:
            self._locked_bearing  = target.bearing
            self._locked_distance = target.distance
            self._locked_driving  = False
            self._lock_lost_count = 0
            self.state = State.LOCKED
            self._scan_theta_start = None
            self.get_logger().info(
                f'LOCKED on cone  brg={math.degrees(target.bearing):.1f}°'
                f'  dist={target.distance:.2f}m')
            return

        if self._scan_total_rot > 2 * math.pi:
            self.get_logger().info('Full scan — no cones found → COMPLETE')
            self.state = State.COMPLETE
            self._stop()
            return

        self._send(0.0, SCAN_ANGULAR)

    def _do_locked(self, confirmed):
        """
        Phase 1 — CENTERING:  stop, turn in place until cone is centred (bearing < CENTRE_THRESH).
        Phase 2 — DRIVING:    drive straight forward (angular=0) until cone disappears.
        → BLIND_APPROACH once cone is gone (or safety distance reached).
        """
        # Re-acquire locked cone from current confirmed list
        best_match = None
        best_bd    = MATCH_BRG_DEG * 2
        for cone in confirmed:
            bd = abs(math.degrees(cone.bearing - self._locked_bearing))
            if bd < best_bd:
                best_bd    = bd
                best_match = cone

        if not self._locked_driving:
            # ── Phase 1: CENTERING — update bearing, turn only ─────────
            if best_match is not None:
                self._locked_bearing  = best_match.bearing
                self._locked_distance = best_match.distance
                self._lock_lost_count = 0
            else:
                self._lock_lost_count += 1

            if self._lock_lost_count >= LOCK_LOST_FRAMES:
                self.get_logger().info('Lost cone while centering → SCANNING')
                self.tracker           = ConeTracker()
                self._scan_theta_start = None
                self.state             = State.SCANNING
                return

            angular = max(-ANGULAR_SPEED_MAX,
                          min(ANGULAR_SPEED_MAX, -BEARING_GAIN * self._locked_bearing))
            self._send(0.0, angular)  # stop, turn only

            if abs(self._locked_bearing) < CENTRE_THRESH:
                self._locked_driving = True
                self.get_logger().info(
                    f'Centred — driving straight  dist={self._locked_distance:.2f}m')
        else:
            # ── Phase 2: DRIVING STRAIGHT — go blind after a few frames of loss
            if best_match is not None:
                # Only update distance, NOT bearing (we're committed to straight)
                self._locked_distance = best_match.distance
                self._lock_lost_count = 0
            else:
                self._lock_lost_count += 1
                if self._lock_lost_count >= LOCK_LOST_FRAMES:
                    self.get_logger().info(
                        f'→ BLIND_APPROACH (cone gone  dist={self._locked_distance:.2f}m)')
                    self.state        = State.BLIND_APPROACH
                self._blind_start = time.time()
                return

            if self._locked_distance < ARRIVE_DIST:
                self.get_logger().info(
                    f'→ BLIND_APPROACH (arrived  dist={self._locked_distance:.2f}m)')
                self.state        = State.BLIND_APPROACH
                self._blind_start = time.time()
                return

            speed = SLOW_SPEED if self._locked_distance < SLOW_DIST else LINEAR_SPEED
            self._send(speed, 0.0)  # straight, no angular correction

    def _do_blind_approach(self):
        """
        Drive straight (angular=0) for BLIND_DURATION seconds.
        No camera correction — cone is under us or occluded.
        """
        elapsed = time.time() - self._blind_start
        remaining = BLIND_DURATION - elapsed

        if remaining > 0:
            self._send(BLIND_SPEED, 0.0)
        else:
            self._stop()
            self.get_logger().info('Blind run done → PICKUP')
            self.state          = State.PICKUP
            self._pickup_done   = False
            self._pickup_thread = threading.Thread(
                target=self._call_ev3_pickup, daemon=True)
            self._pickup_thread.start()

    def _do_pickup(self):
        """Wait for EV3 pickup to complete, then go find next cone."""
        self._stop()
        if not self._pickup_done:
            return

        self._mark_visited()
        idx = self.cones_reached
        if idx < len(self._results):
            self._results[idx]['status'] = 'collected'
        elif self.max_cones == 0:
            self._results.append({'cone_id': f'cone-{idx}', 'status': 'collected'})
        self.cones_reached += 1
        self.get_logger().info(
            f'Pickup complete. cones={self.cones_reached}')

        if self.max_cones > 0 and self.cones_reached >= self.max_cones:
            self.get_logger().info('Target count reached → COMPLETE')
            self.state = State.COMPLETE
        else:
            # Fresh tracker so old detections don't immediately re-lock
            self.tracker          = ConeTracker()
            self._scan_theta_start = None
            self.state            = State.SCANNING
            self.get_logger().info('Scanning for next cone…')

    def _call_ev3_pickup(self):
        """
        Runs in background thread.
        1. POST /pickup  → EV3 starts the motion (returns immediately).
        2. Poll GET /status until busy=False (motion complete) or timeout.
        """
        try:
            url_pickup = f'http://{self.ev3_host}/pickup'
            url_status = f'http://{self.ev3_host}/status'
            req = urllib.request.Request(url_pickup, method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                self.get_logger().info(f'EV3 pickup started: {data}')

            # Wait for the EV3 to finish (busy → False), timeout 30 s
            deadline = time.time() + 30.0
            while time.time() < deadline:
                time.sleep(0.5)
                try:
                    with urllib.request.urlopen(url_status, timeout=5) as sr:
                        st = json.loads(sr.read())
                        if not st.get('busy', True):
                            self.get_logger().info('EV3 pickup complete')
                            break
                except Exception:
                    pass  # keep polling on transient errors
            else:
                self.get_logger().warn('EV3 pickup timed out (30 s)')
        except Exception as e:
            self.get_logger().warn(f'EV3 pickup call failed: {e}')
        finally:
            self._pickup_done = True

    def _write_status(self, confirmed):
        """Write collection-compatible JSON status file for cone_bridge to read."""
        if not self.status_file:
            return
        try:
            STATE_PHASE = {
                State.SCANNING:       ('scanning',    f'Scanning for cone {self.cones_reached + 1}…'),
                State.LOCKED:         ('visual_servo', f'Locked · {self._locked_distance:.2f}m'),
                State.BLIND_APPROACH: ('visual_servo', 'Final approach…'),
                State.PICKUP:         ('picking_up',  f'Picking up cone {self.cones_reached + 1}'),
                State.COMPLETE:       ('done',         'All cones collected'),
            }
            phase, detail = STATE_PHASE.get(self.state, ('scanning', ''))
            total = self.max_cones if self.max_cones > 0 else max(
                len(self.visited) + (1 if self.state != State.COMPLETE else 0),
                len(self._results))
            status = {
                'active':       self.state != State.COMPLETE,
                'state':        self.state.name,
                'cone_index':   self.cones_reached,
                'cone_total':   total,
                'cone_id':      f'cone-{self.cones_reached}',
                'phase':        phase,
                'phase_detail': detail,
                'tracks':       len(self.tracker.tracks),
                'confirmed':    len(confirmed),
                'results':      self._results,
            }
            tmp = self.status_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(status, f)
            os.replace(tmp, self.status_file)
        except Exception:
            pass

    # ── 10 Hz main loop ───────────────────────────────────────────────

    def _loop(self):
        self._last_loop_t = time.time()

        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().warn('Camera read failed')
            return

        # Detect → filter → track
        detections, rejected, _mask = detect_red_cones(frame)
        filtered = []
        for (x, y, w, h, area, _ellipse) in detections:
            r = self._filter(x, y, w, h, area)
            if r:
                filtered.append(r)
        self.tracker.update(filtered)
        confirmed = self.tracker.confirmed()

        # State dispatch
        if   self.state == State.SCANNING:       self._do_scanning(confirmed)
        elif self.state == State.LOCKED:         self._do_locked(confirmed)
        elif self.state == State.BLIND_APPROACH: self._do_blind_approach()
        elif self.state == State.PICKUP:         self._do_pickup()
        elif self.state == State.COMPLETE:       self._stop()

        # Status file for cone_bridge
        self._write_status(confirmed)

        # Annotate + stream
        self._draw(frame, detections, rejected, confirmed)
        self.streamer.push(frame)

        if not self.no_display:
            cv2.imshow('Cone Chaser v2', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                raise SystemExit(0)

    # ── Frame annotation ─────────────────────────────────────────────

    def _draw(self, frame, detections, rejected, confirmed):
        draw_detections(frame, detections, rejected, self.focal)

        h, w = frame.shape[:2]
        cx = w // 2

        STATE_COLORS = {
            State.SCANNING:       (180, 180,   0),
            State.LOCKED:         (  0, 200, 255),
            State.BLIND_APPROACH: (  0, 100, 255),
            State.PICKUP:         (200,   0, 200),
            State.COMPLETE:       (  0, 220,   0),
        }
        sc = STATE_COLORS.get(self.state, (255, 255, 255))

        # Confirmed track lines
        for cone in confirmed:
            px = int(cx + self.focal * math.tan(cone.bearing))
            px = max(0, min(w - 1, px))
            is_target = (
                self.state in (State.LOCKED, State.BLIND_APPROACH) and
                abs(math.degrees(cone.bearing - self._locked_bearing)) < 20
            )
            color     = (0, 0, 255) if is_target else (0, 220, 0)
            thickness = 2 if is_target else 1
            cv2.line(frame, (px, 0), (px, h - 40), color, thickness)
            label = f'{cone.distance:.2f}m'
            if is_target:
                label += ' ◄ TARGET'
            cv2.putText(frame, label, (px + 4, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)

        # Blind approach progress bar (bottom strip)
        if self.state == State.BLIND_APPROACH and self._blind_start:
            pct = min(1.0, (time.time() - self._blind_start) / BLIND_DURATION)
            cv2.rectangle(frame, (0, h - 6), (int(w * pct), h),
                          (0, 100, 255), -1)

        # Status bar
        max_str = str(self.max_cones) if self.max_cones > 0 else '∞'
        parts = [
            f'{self.state.name}',
            f'cones {self.cones_reached}/{max_str}',
            f'tracks {len(self.tracker.tracks)}  confirmed {len(confirmed)}',
        ]
        if self.state == State.LOCKED:
            parts.append(
                f'brg {math.degrees(self._locked_bearing):+.1f}°'
                f'  dist {self._locked_distance:.2f}m')
        if self.state == State.BLIND_APPROACH and self._blind_start:
            elapsed = time.time() - self._blind_start
            parts.append(f'blind {elapsed:.1f}/{BLIND_DURATION:.0f}s')
        if self.state == State.PICKUP:
            parts.append('waiting for EV3…')

        cv2.rectangle(frame, (0, h - 36), (w, h - 6), (0, 0, 0), -1)
        cv2.putText(frame, '  |  '.join(parts), (8, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, sc, 1)

    # ── Cleanup ───────────────────────────────────────────────────────

    def destroy_node(self):
        try:
            self._stop()
        except Exception:
            pass
        if self.cap.isOpened():
            self.cap.release()
        if not self.no_display:
            cv2.destroyAllWindows()
        if self.status_file:
            try:
                os.remove(self.status_file)
            except FileNotFoundError:
                pass
        super().destroy_node()


# ═════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser('Cone Chaser v2')
    parser.add_argument('--no-display', action='store_true',
                        help='Headless — use MJPEG stream instead of cv2.imshow')
    parser.add_argument('--max-cones', type=int, default=0,
                        help='Stop after N cones (0 = unlimited)')
    parser.add_argument('--camera', type=int, default=0,
                        help='Camera device index')
    parser.add_argument('--ev3', default=EV3_DEFAULT,
                        help=f'EV3 host:port  (default: {EV3_DEFAULT})')
    parser.add_argument('--stream-port', type=int, default=MJPEG_PORT,
                        help=f'MJPEG server port  (default: {MJPEG_PORT})')
    parser.add_argument('--status-file', type=str, default=None,
                        help='Path to write JSON status (for cone_bridge)')
    args = parser.parse_args()

    rclpy.init()
    node = ConeChaserNode(
        camera_index=args.camera,
        no_display=args.no_display,
        max_cones=args.max_cones,
        ev3_host=args.ev3,
        status_file=args.status_file,
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
