#!/usr/bin/env python3
"""
Autonomous Cone Chaser — visual servoing node for TurtleBot.

Drives the robot to each visible red cone (nearest first) using the onboard
camera.  Steers directly on camera-relative bearing + distance (no world-
coordinate conversion needed for navigation).

Mutually exclusive with cone_bridge.py (both publish to /cmd_vel).

Usage:
    source /opt/ros/jazzy/setup.bash
    python3 cone_chaser.py [--no-display] [--max-cones N] [--camera 0]
"""

import argparse
import json
import math
import os
import time
from enum import Enum, auto

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TwistStamped, PoseStamped
from nav_msgs.msg import Odometry

from cone_detector import (
    detect_red_cones,
    estimate_distance,
    compute_focal_length_px,
    load_calibration,
    draw_detections,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    CAMERA_DFOV_DEG,
    KNOWN_WIDTH_MM,
)

# ── Speed limits (match cone_bridge.py) ──────────────────────────────
LINEAR_SPEED = 0.15       # m/s max forward speed
ANGULAR_SPEED = 0.8       # rad/s max turning speed
SCAN_ANGULAR = 0.3        # rad/s rotation during SCANNING

# ── Visual servo tuning ──────────────────────────────────────────────
BEARING_GAIN = 2.0        # proportional gain for angular correction
TURN_ONLY_THRESH = math.radians(30)   # |bearing| > this → turn in place
ARRIVE_DIST = 0.15        # meters — stop when this close
SLOW_DIST = 0.40          # meters — slow approach zone
SLOW_SPEED = 0.08         # m/s in slow zone
NORMAL_SPEED = 0.15       # m/s in normal zone

# ── False-positive rejection ─────────────────────────────────────────
MIN_ASPECT = 0.8          # minimum w/h ratio
MAX_ASPECT = 10.0         # maximum w/h ratio
MIN_DIST_M = 0.05         # ignore closer than 5cm
MAX_DIST_M = 3.0          # ignore further than 3m
CROSS_CHECK_LO = 0.40     # predicted/actual pixel width ratio low bound
CROSS_CHECK_HI = 2.50     # predicted/actual pixel width ratio high bound

# ── Temporal tracker ─────────────────────────────────────────────────
CONFIRM_FRAMES = 5        # consecutive hits to confirm (~0.5s at 10Hz)
EXPIRE_FRAMES = 10        # frames without a match to expire (~1s)
MATCH_BEARING_DEG = 8.0   # max bearing difference for matching (degrees)
MATCH_DIST_RATIO = 0.30   # max relative distance difference for matching

# ── Visited deduplication ────────────────────────────────────────────
VISITED_RADIUS = 0.30     # meters — same cone if closer than this

# ── Searching state ──────────────────────────────────────────────────
SEARCH_COAST_FRAMES = 5   # keep heading before sweeping
SEARCH_SWEEP_RAD = math.radians(45)  # ±45 deg sweep


# ═════════════════════════════════════════════════════════════════════
# State machine
# ═════════════════════════════════════════════════════════════════════

class State(Enum):
    SCANNING = auto()
    APPROACHING = auto()
    REACHED = auto()
    SEARCHING = auto()
    COMPLETE = auto()


# ═════════════════════════════════════════════════════════════════════
# Temporal tracker
# ═════════════════════════════════════════════════════════════════════

class TrackedCone:
    """A single tracked cone across frames."""

    def __init__(self, bearing, distance):
        self.bearing = bearing
        self.distance = distance
        self.hits = 1
        self.misses = 0
        self.confirmed = False

    def update(self, bearing, distance):
        self.bearing = bearing
        self.distance = distance
        self.hits += 1
        self.misses = 0
        if self.hits >= CONFIRM_FRAMES:
            self.confirmed = True

    def tick_miss(self):
        self.misses += 1

    @property
    def expired(self):
        return self.misses >= EXPIRE_FRAMES


class ConeTracker:
    """Maintains tracked cones across frames with confirmation logic."""

    def __init__(self):
        self.tracks: list[TrackedCone] = []

    def update(self, detections):
        """Update tracks with new detections.  detections: list of (bearing_rad, dist_m)."""
        matched_track = set()
        matched_det = set()

        # Build all possible (cost, det_index, track_index) pairs
        pairs = []
        for di, (db, dd) in enumerate(detections):
            for ti, track in enumerate(self.tracks):
                bearing_diff = abs(math.degrees(db - track.bearing))
                dist_avg = (dd + track.distance) / 2.0
                dist_diff = abs(dd - track.distance) / dist_avg if dist_avg > 0 else 999
                cost = bearing_diff + dist_diff * 30
                pairs.append((cost, di, ti, db, dd, bearing_diff, dist_diff))

        # Greedy nearest match
        pairs.sort()
        for cost, di, ti, db, dd, bdiff, ddiff in pairs:
            if di in matched_det or ti in matched_track:
                continue
            if bdiff < MATCH_BEARING_DEG and ddiff < MATCH_DIST_RATIO:
                self.tracks[ti].update(db, dd)
                matched_track.add(ti)
                matched_det.add(di)

        # Tick misses for unmatched tracks
        for ti, track in enumerate(self.tracks):
            if ti not in matched_track:
                track.tick_miss()

        # Create new tracks for unmatched detections
        for di, (db, dd) in enumerate(detections):
            if di not in matched_det:
                self.tracks.append(TrackedCone(db, dd))

        # Purge expired
        self.tracks = [t for t in self.tracks if not t.expired]

    def confirmed_cones(self):
        return [t for t in self.tracks if t.confirmed]


# ═════════════════════════════════════════════════════════════════════
# ROS2 node
# ═════════════════════════════════════════════════════════════════════

class ConeChaserNode(Node):
    def __init__(self, camera_index, no_display, max_cones, status_file=None):
        super().__init__('cone_chaser')
        self.no_display = no_display
        self.max_cones = max_cones
        self.status_file = status_file

        # ── Camera ───────────────────────────────────────────────────
        self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            self.get_logger().fatal('Could not open camera')
            raise SystemExit(1)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.get_logger().info(f'Camera opened at {actual_w}x{actual_h}')

        # ── Focal length ─────────────────────────────────────────────
        custom_focal = load_calibration()
        if custom_focal:
            self.focal_length = custom_focal
            self.get_logger().info(f'Using custom calibration: {self.focal_length:.1f}px')
        else:
            self.focal_length = compute_focal_length_px(actual_w, actual_h, CAMERA_DFOV_DEG)
            self.get_logger().info(f'Using auto focal length: {self.focal_length:.1f}px')

        self.frame_w = actual_w
        self.frame_h = actual_h

        # ── ROS2 pub/sub ─────────────────────────────────────────────
        self.cmd_vel_pub = self.create_publisher(TwistStamped, '/cmd_vel', 10)
        self.odom_sub = self.create_subscription(
            Odometry, '/odom', self.odom_callback, 10
        )
        self.uwb_sub = self.create_subscription(
            PoseStamped, '/uwb/pose', self.uwb_callback, 10
        )

        # ── Robot pose (from odom) ───────────────────────────────────
        self.robot_x = 0.0
        self.robot_y = 0.0
        self.robot_theta = 0.0

        # ── UWB position (optional, preferred for world coords) ──────
        self.uwb_x = 0.0
        self.uwb_y = 0.0
        self.uwb_stamp = 0.0

        # ── State machine ────────────────────────────────────────────
        self.state = State.SCANNING
        self.tracker = ConeTracker()
        self.visited = []          # list of (world_x, world_y)
        self.target = None         # active TrackedCone
        self.cones_reached = 0

        # Scanning bookkeeping
        self.scan_start_theta = None
        self.scan_total_rotation = 0.0
        self.scan_last_theta = None

        # Searching bookkeeping
        self.search_coast_count = 0
        self.search_sweep_start = None
        self.search_sweep_dir = 1
        self.search_sweep_origin = 0.0

        # Reached bookkeeping
        self.reached_time = 0.0

        # ── Safety watchdog ──────────────────────────────────────────
        self.last_loop_time = time.time()
        self.create_timer(0.5, self.watchdog)

        # ── Main loop at 10 Hz ───────────────────────────────────────
        self.create_timer(0.1, self.main_loop)
        self.get_logger().info('Cone Chaser started — state: SCANNING')

    # ── ROS2 callbacks ───────────────────────────────────────────────

    def odom_callback(self, msg):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        siny = 2.0 * (ori.w * ori.z + ori.x * ori.y)
        cosy = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
        self.robot_x = pos.x
        self.robot_y = pos.y
        self.robot_theta = math.atan2(siny, cosy)

    def uwb_callback(self, msg):
        self.uwb_x = msg.pose.position.x
        self.uwb_y = msg.pose.position.y
        self.uwb_stamp = time.time()

    # ── Helpers ──────────────────────────────────────────────────────

    def send_velocity(self, linear, angular):
        msg = TwistStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'base_link'
        msg.twist.linear.x = float(linear)
        msg.twist.angular.z = float(max(-ANGULAR_SPEED, min(ANGULAR_SPEED, angular)))
        self.cmd_vel_pub.publish(msg)

    def stop(self):
        self.send_velocity(0.0, 0.0)

    def watchdog(self):
        if time.time() - self.last_loop_time > 0.5:
            self.stop()

    @staticmethod
    def normalize_angle(angle):
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle

    def _world_pos(self):
        """Best-available (x, y) for world-coordinate calculations.
        Prefer UWB if fresh (<1 s), otherwise fall back to odom."""
        if (time.time() - self.uwb_stamp) < 1.0:
            return self.uwb_x, self.uwb_y
        return self.robot_x, self.robot_y

    def compute_bearing(self, x, w):
        """Camera bearing from pixel bbox.  + = right of center."""
        cx = self.frame_w / 2.0
        center_x = x + w / 2.0
        return math.atan2(center_x - cx, self.focal_length)

    # ── False-positive rejection ─────────────────────────────────────

    def filter_detection(self, x, y, w, h, area):
        """Extra rejection beyond cone_detector's shape filters.
        Returns (bearing_rad, dist_m) or None."""
        if h <= 0:
            return None

        # Aspect ratio
        aspect = w / h
        if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
            return None

        # Distance
        dist_mm, mode = estimate_distance(x, y, w, h, self.focal_length, self.frame_w)
        dist_m = dist_mm / 1000.0
        if dist_m < MIN_DIST_M or dist_m > MAX_DIST_M:
            return None

        # Cross-check: predicted pixel width vs actual
        if dist_mm > 0 and w > 0:
            predicted_w = (KNOWN_WIDTH_MM * self.focal_length) / dist_mm
            ratio = predicted_w / w
            if ratio < CROSS_CHECK_LO or ratio > CROSS_CHECK_HI:
                return None

        bearing = self.compute_bearing(x, w)
        return (bearing, dist_m)

    # ── Visited-cone deduplication ───────────────────────────────────

    def is_visited(self, bearing, distance):
        wx, wy = self._world_pos()
        cone_x = wx + distance * math.cos(self.robot_theta + bearing)
        cone_y = wy + distance * math.sin(self.robot_theta + bearing)
        for vx, vy in self.visited:
            if math.hypot(cone_x - vx, cone_y - vy) < VISITED_RADIUS:
                return True
        return False

    def mark_visited(self, bearing, distance):
        wx, wy = self._world_pos()
        cone_x = wx + distance * math.cos(self.robot_theta + bearing)
        cone_y = wy + distance * math.sin(self.robot_theta + bearing)
        self.visited.append((cone_x, cone_y))
        self.get_logger().info(
            f'Marked cone at ({cone_x:.2f}, {cone_y:.2f}) as visited '
            f'[{len(self.visited)} total]'
        )

    def pick_target(self, confirmed):
        """Nearest confirmed cone that hasn't been visited."""
        candidates = [c for c in confirmed
                      if not self.is_visited(c.bearing, c.distance)]
        if not candidates:
            return None
        candidates.sort(key=lambda c: c.distance)
        return candidates[0]

    # ── 10 Hz main loop ─────────────────────────────────────────────

    def main_loop(self):
        self.last_loop_time = time.time()

        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().warn('Failed to read camera frame')
            return

        # Detect → filter → track
        detections, rejected, mask = detect_red_cones(frame)

        filtered = []
        for (x, y, w, h, area, ellipse) in detections:
            result = self.filter_detection(x, y, w, h, area)
            if result:
                filtered.append(result)

        self.tracker.update(filtered)
        confirmed = self.tracker.confirmed_cones()

        # Dispatch to current state
        if self.state == State.SCANNING:
            self._do_scanning(confirmed)
        elif self.state == State.APPROACHING:
            self._do_approaching(confirmed)
        elif self.state == State.REACHED:
            self._do_reached()
        elif self.state == State.SEARCHING:
            self._do_searching(confirmed)
        elif self.state == State.COMPLETE:
            self.stop()

        # Write status file for cone_bridge.py to read
        if self.status_file:
            try:
                status = {
                    'state': self.state.name,
                    'cones_reached': self.cones_reached,
                    'max_cones': self.max_cones,
                    'tracks': len(self.tracker.tracks),
                    'confirmed': len(confirmed),
                    'visited': len(self.visited),
                }
                tmp = self.status_file + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(status, f)
                os.replace(tmp, self.status_file)
            except Exception:
                pass

        # Debug window
        if not self.no_display:
            self._draw_debug(frame, detections, rejected, confirmed)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                self.get_logger().info('Quit requested')
                self.stop()
                raise SystemExit(0)

    # ── State handlers ───────────────────────────────────────────────

    def _do_scanning(self, confirmed):
        """Rotate in place, looking for confirmed cones."""
        if self.scan_start_theta is None:
            self.scan_start_theta = self.robot_theta
            self.scan_last_theta = self.robot_theta
            self.scan_total_rotation = 0.0

        # Accumulate rotation
        delta = self.normalize_angle(self.robot_theta - self.scan_last_theta)
        self.scan_total_rotation += abs(delta)
        self.scan_last_theta = self.robot_theta

        # Pick target any time one appears
        target = self.pick_target(confirmed)
        if target is not None:
            self.target = target
            self.state = State.APPROACHING
            self.scan_start_theta = None
            self.get_logger().info(
                f'Cone acquired: bearing={math.degrees(target.bearing):.1f}° '
                f'dist={target.distance:.2f}m → APPROACHING'
            )
            return

        # Full 360° with nothing new → done
        if self.scan_total_rotation > 2 * math.pi:
            self.get_logger().info('Full scan — no unvisited cones found → COMPLETE')
            self.state = State.COMPLETE
            self.stop()
            return

        self.send_velocity(0.0, SCAN_ANGULAR)

    def _do_approaching(self, confirmed):
        """Visual servo toward the target cone."""
        if self.target is None or self.target.expired:
            self.get_logger().warn('Target lost → SEARCHING')
            self.state = State.SEARCHING
            self.search_coast_count = 0
            self.search_sweep_start = None
            return

        # Switch to a closer unvisited cone if one appears much nearer
        better = self.pick_target(confirmed)
        if better is not None and better is not self.target:
            if better.distance < self.target.distance * 0.7:
                self.target = better

        bearing = self.target.bearing
        distance = self.target.distance

        # Arrived
        if distance < ARRIVE_DIST:
            self.get_logger().info(f'Cone reached at {distance:.2f}m')
            self.stop()
            self.mark_visited(bearing, distance)
            self.cones_reached += 1
            self.reached_time = time.time()
            self.state = State.REACHED
            return

        # Visual servo controller
        angular = -BEARING_GAIN * bearing

        if abs(bearing) > TURN_ONLY_THRESH:
            self.send_velocity(0.0, angular)
        elif distance < SLOW_DIST:
            linear = min(SLOW_SPEED, distance * 0.3)
            self.send_velocity(linear, angular)
        else:
            linear = min(NORMAL_SPEED, distance * 0.3)
            self.send_velocity(linear, angular)

    def _do_reached(self):
        """Pause 1 s at cone, then decide what's next."""
        self.stop()
        if time.time() - self.reached_time < 1.0:
            return

        if self.max_cones > 0 and self.cones_reached >= self.max_cones:
            self.get_logger().info(
                f'Reached {self.cones_reached}/{self.max_cones} cones → COMPLETE'
            )
            self.state = State.COMPLETE
            return

        self.get_logger().info('Re-scanning for next cone…')
        self.state = State.SCANNING
        self.target = None
        self.scan_start_theta = None

    def _do_searching(self, confirmed):
        """Target lost — coast briefly, then sweep ±45° to re-find."""
        # Re-acquire?
        target = self.pick_target(confirmed)
        if target is not None:
            self.target = target
            self.state = State.APPROACHING
            self.get_logger().info('Target re-acquired → APPROACHING')
            return

        # Coast forward for a few frames
        if self.search_coast_count < SEARCH_COAST_FRAMES:
            self.search_coast_count += 1
            self.send_velocity(0.05, 0.0)
            return

        # Sweep ±45°
        if self.search_sweep_start is None:
            self.search_sweep_start = self.robot_theta
            self.search_sweep_origin = self.robot_theta
            self.search_sweep_dir = 1

        delta = self.normalize_angle(self.robot_theta - self.search_sweep_origin)

        if self.search_sweep_dir == 1 and delta > SEARCH_SWEEP_RAD:
            self.search_sweep_dir = -1
        elif self.search_sweep_dir == -1 and delta < -SEARCH_SWEEP_RAD:
            self.get_logger().info('Search sweep done — back to SCANNING')
            self.state = State.SCANNING
            self.target = None
            self.scan_start_theta = None
            return

        self.send_velocity(0.0, SCAN_ANGULAR * self.search_sweep_dir)

    # ── Debug display ────────────────────────────────────────────────

    def _draw_debug(self, frame, detections, rejected, confirmed):
        draw_detections(frame, detections, rejected, self.focal_length)

        # Confirmed-track indicators
        for cone in confirmed:
            px = int(self.frame_w / 2.0 + self.focal_length * math.tan(cone.bearing))
            px = max(0, min(self.frame_w - 1, px))
            color = (0, 255, 255) if cone is self.target else (0, 255, 0)
            cv2.line(frame, (px, 0), (px, self.frame_h), color, 1)
            label = f'{cone.distance:.2f}m'
            if cone is self.target:
                label += ' [TGT]'
            cv2.putText(frame, label, (px + 5, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # Bottom status bar
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, h - 40), (w, h), (0, 0, 0), -1)
        max_str = str(self.max_cones) if self.max_cones > 0 else 'inf'
        status = (
            f'{self.state.name} | '
            f'reached: {self.cones_reached}/{max_str} | '
            f'tracks: {len(self.tracker.tracks)} '
            f'confirmed: {len(confirmed)} | '
            f'visited: {len(self.visited)}'
        )
        cv2.putText(frame, status, (10, h - 15),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

        cv2.imshow('Cone Chaser', frame)

    # ── Cleanup ──────────────────────────────────────────────────────

    def destroy_node(self):
        self.stop()
        if self.status_file:
            try:
                os.remove(self.status_file)
            except FileNotFoundError:
                pass
        if self.cap and self.cap.isOpened():
            self.cap.release()
        if not self.no_display:
            cv2.destroyAllWindows()
        super().destroy_node()


# ═════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Autonomous Cone Chaser')
    parser.add_argument('--no-display', action='store_true',
                        help='Headless mode (no CV2 window)')
    parser.add_argument('--max-cones', type=int, default=0,
                        help='Stop after visiting N cones (0 = unlimited)')
    parser.add_argument('--camera', type=int, default=0,
                        help='Camera device index')
    parser.add_argument('--status-file', type=str, default=None,
                        help='Path to write JSON status for external monitoring')
    args = parser.parse_args()

    rclpy.init()
    node = ConeChaserNode(args.camera, args.no_display, args.max_cones,
                          status_file=args.status_file)

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
