#!/usr/bin/env python3
"""
ConePilot Bridge - Lightweight HTTP server that bridges ConePilot to ROS2.
Run on the TurtleBot alongside robot.launch.py.
Uses only basic ROS2 packages (no Nav2 required).

Navigation uses UWB+odom fusion: UWB provides absolute position anchoring,
odom provides smooth relative motion between anchor points.

Usage:
    source /opt/ros/jazzy/setup.bash
    python3 cone_bridge.py
"""

import json
import math
import os
import signal
import socketserver
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import cv2
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TwistStamped, PoseStamped
from nav_msgs.msg import Odometry

from cone_detector import (
    detect_red_cones, draw_detections, estimate_distance,
    compute_focal_length_px, DetectionSmoother,
    FRAME_WIDTH, FRAME_HEIGHT, CAMERA_DFOV_DEG,
)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True

PORT = 8888

# Tuning parameters
LINEAR_SPEED = 0.15       # m/s max forward speed
ANGULAR_SPEED = 0.8       # rad/s max turning speed
GOAL_TOLERANCE = 0.08     # meters - how close is "arrived" (fused)
UWB_VERIFY_TOLERANCE = 0.10  # meters - UWB verification after reaching goal
UWB_VERIFY_MAX_RETRIES = 2   # max re-navigation attempts for UWB verification
ANGLE_TOLERANCE = 0.1     # radians - how aligned before driving forward
CALIBRATION_DRIVE_DIST = 0.5  # meters to drive during calibration

# Obstacle avoidance parameters (distances in cm)
OA_HARD_STOP_CM = 15       # full stop — collision imminent
OA_SLOW_START_CM = 40      # begin proportional slowdown
OA_SIDE_BIAS_CM = 60       # side sensors bias steering at this range

# Field boundary enforcement (meters) — robot must stay inside
FIELD_MIN_X = 0.10         # 10cm margin from edge
FIELD_MIN_Y = 0.10
FIELD_MAX_X = 3.40         # 3.5m field - 10cm margin
FIELD_MAX_Y = 2.90         # 3.0m field - 10cm margin
BOUNDARY_SLOW_MARGIN = 0.20  # start slowing 20cm from boundary

# EV3 cone mechanism server
EV3_MECHANISM_URL = os.environ.get('EV3_URL', 'http://172.20.10.2:8080')


class ConeBridgeNode(Node):
    def __init__(self):
        super().__init__('cone_bridge')
        self.cmd_vel_pub = self.create_publisher(TwistStamped, '/cmd_vel', 10)

        # Raw odom state
        self.odom_x = 0.0
        self.odom_y = 0.0
        self.odom_yaw = 0.0
        self.odom_received = False
        self.odom_count = 0

        # UWB state
        self.uwb_x = None
        self.uwb_y = None
        self.uwb_stamp = 0.0
        self.uwb_received = False
        self.uwb_count = 0

        # Navigation debug state
        self.nav_debug = {}

        # Fusion anchors (reset before each waypoint)
        self.anchor_x = None        # UWB world-frame anchor
        self.anchor_y = None
        self.odom_anchor_x = None   # odom snapshot at anchor time
        self.odom_anchor_y = None

        # Calibration state
        self.calibrated = False
        self.calibrating = False
        self.yaw_offset = None      # rotation from odom frame to world frame

        # Navigation state
        self.navigating = False
        self.cancel_nav = False
        self.waypoint_index = -1
        self.waypoint_total = 0
        self.waypoint_state = 'idle'      # idle | calibrating | navigating | dwelling | completed
        self.dwell_remaining = 0.0

        # Cone chase subprocess state
        self.cone_chase_process = None
        self.cone_chase_status_file = '/tmp/cone_chaser_status.json'
        self.ultrasonic_status_file = '/tmp/ultrasonic_status.json'

        # Camera stream state
        self.camera_streaming = False
        self.camera_stop = False

        # Lock-on mode state
        self.lock_on_running = False
        self.lock_on_info = {}       # {locked, distance_m, bearing_deg}
        self.lock_on_frame = None    # latest JPEG bytes for /camera

        # Collection mode state
        self.collecting = False
        self.collection_cancel = False
        self.collection_status = {}    # exposed via /status
        self.collection_frame = None   # annotated JPEG for /camera

        self.odom_sub = self.create_subscription(
            Odometry, '/odom', self.odom_callback, 10
        )
        self.uwb_sub = self.create_subscription(
            PoseStamped, '/uwb/pose', self.uwb_callback, 10
        )
        self.get_logger().info(f'ConeBridge running on port {PORT}')

    def odom_callback(self, msg):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        siny = 2.0 * (ori.w * ori.z + ori.x * ori.y)
        cosy = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
        prev_x, prev_y = self.odom_x, self.odom_y
        self.odom_x = pos.x
        self.odom_y = pos.y
        self.odom_yaw = math.atan2(siny, cosy)
        self.odom_count += 1
        if not self.odom_received:
            self.odom_received = True
            self.get_logger().info(
                f'[ODOM] First odom: ({self.odom_x:.4f}, {self.odom_y:.4f}), '
                f'yaw={math.degrees(self.odom_yaw):.1f}°'
            )
        # Log when odom changes significantly (every ~1s during nav)
        elif self.navigating and self.odom_count % 20 == 0:
            dx = self.odom_x - prev_x
            dy = self.odom_y - prev_y
            self.get_logger().info(
                f'[ODOM] #{self.odom_count} pos=({self.odom_x:.4f}, {self.odom_y:.4f}) '
                f'yaw={math.degrees(self.odom_yaw):.1f}° '
                f'delta=({dx:.4f}, {dy:.4f})'
            )

    def uwb_callback(self, msg):
        self.uwb_x = msg.pose.position.x
        self.uwb_y = msg.pose.position.y
        self.uwb_stamp = time.time()
        self.uwb_count += 1
        if not self.uwb_received:
            self.uwb_received = True
            self.get_logger().info(
                f'[UWB] First UWB: ({self.uwb_x:.4f}, {self.uwb_y:.4f})'
            )

    # ── Fusion methods ────────────────────────────────────────────

    def get_fused_position(self):
        """UWB anchor + rotated odom delta = fused world position."""
        if self.anchor_x is None or self.odom_anchor_x is None:
            # Not yet anchored — fall back to raw UWB or odom
            if self.uwb_x is not None:
                return self.uwb_x, self.uwb_y
            return self.odom_x, self.odom_y

        dx = self.odom_x - self.odom_anchor_x
        dy = self.odom_y - self.odom_anchor_y

        if self.yaw_offset is not None:
            cos_y = math.cos(self.yaw_offset)
            sin_y = math.sin(self.yaw_offset)
            rx = dx * cos_y - dy * sin_y
            ry = dx * sin_y + dy * cos_y
            return self.anchor_x + rx, self.anchor_y + ry

        return self.anchor_x + dx, self.anchor_y + dy

    def get_fused_heading(self):
        """Odom yaw rotated by calibrated yaw_offset."""
        if self.yaw_offset is not None:
            return self.normalize_angle(self.odom_yaw + self.yaw_offset)
        return self.odom_yaw

    def re_anchor(self):
        """Snapshot current UWB + odom as new fusion anchor.
        Call between waypoints to reset drift accumulation."""
        if self.uwb_x is None:
            self.get_logger().warn('re_anchor: no UWB data, skipping')
            return
        self.anchor_x = self.uwb_x
        self.anchor_y = self.uwb_y
        self.odom_anchor_x = self.odom_x
        self.odom_anchor_y = self.odom_y
        self.get_logger().info(
            f'Re-anchored: UWB=({self.anchor_x:.2f}, {self.anchor_y:.2f}), '
            f'odom=({self.odom_anchor_x:.2f}, {self.odom_anchor_y:.2f})'
        )

    # ── Calibration ───────────────────────────────────────────────

    def calibrate(self):
        """Drive 50cm forward, compute yaw_offset from UWB heading vs odom yaw.
        Blocks until complete or cancelled."""
        self.calibrating = True
        self.waypoint_state = 'calibrating'
        self.get_logger().info('Starting calibration drive...')

        # Wait for both sensors
        timeout = time.time() + 5.0
        while (not self.odom_received or not self.uwb_received) and time.time() < timeout:
            if self.cancel_nav:
                self.calibrating = False
                return False
            time.sleep(0.1)

        if not self.odom_received or not self.uwb_received:
            self.get_logger().error('Calibration failed: sensors not ready')
            self.calibrating = False
            return False

        # Record start positions
        start_uwb_x = self.uwb_x
        start_uwb_y = self.uwb_y
        start_odom_yaw = self.odom_yaw

        # Set initial anchor
        self.anchor_x = self.uwb_x
        self.anchor_y = self.uwb_y
        self.odom_anchor_x = self.odom_x
        self.odom_anchor_y = self.odom_y

        # Drive forward until UWB shows we've moved enough
        while not self.cancel_nav:
            dx = self.uwb_x - start_uwb_x
            dy = self.uwb_y - start_uwb_y
            dist = math.sqrt(dx * dx + dy * dy)

            if dist >= CALIBRATION_DRIVE_DIST:
                self.send_velocity(0.0, 0.0)
                time.sleep(0.3)  # let UWB settle

                uwb_heading = math.atan2(dy, dx)
                self.yaw_offset = self.normalize_angle(
                    uwb_heading - start_odom_yaw
                )
                self.calibrated = True
                self.get_logger().info(
                    f'Calibrated! yaw_offset={math.degrees(self.yaw_offset):.1f} deg'
                )

                # Re-anchor after calibration so the cal drive distance
                # doesn't count as position error
                self.re_anchor()
                self.calibrating = False
                return True

            self.send_velocity(0.10, 0.0)
            time.sleep(0.05)

        self.send_velocity(0.0, 0.0)
        self.calibrating = False
        return False

    # ── Motion primitives ─────────────────────────────────────────

    def send_velocity(self, linear, angular):
        msg = TwistStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'base_link'
        msg.twist.linear.x = float(linear)
        msg.twist.angular.z = float(angular)
        self.cmd_vel_pub.publish(msg)

    def stop(self):
        self.cancel_nav = True
        self.collection_cancel = True
        self.collecting = False
        self.send_velocity(0.0, 0.0)
        self.navigating = False
        self.calibrating = False
        self.waypoint_state = 'idle'
        self.dwell_remaining = 0.0

    def normalize_angle(self, angle):
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle

    # ── Navigation (uses fused position) ──────────────────────────

    def navigate_to(self, goal_x, goal_y, reverse=False, obstacle_avoidance=True):
        """Proportional go-to-point using UWB+odom fused position.
        If reverse=True, robot backs into the goal (front faces away).
        If obstacle_avoidance=False, skip ultrasonic avoidance (still respects boundaries)."""
        self.navigating = True
        self.cancel_nav = False
        rate = 0.05  # 20Hz
        loop_count = 0
        start_time = time.time()

        nav_mode = 'REVERSE' if reverse else 'FORWARD'
        self.get_logger().info(
            f'[NAV] ── Starting {nav_mode} navigation to ({goal_x:.3f}, {goal_y:.3f}) ──'
        )
        self.get_logger().info(
            f'[NAV] Sensors: odom_received={self.odom_received} (count={self.odom_count}), '
            f'uwb_received={self.uwb_received} (count={self.uwb_count}), '
            f'calibrated={self.calibrated}, yaw_offset={math.degrees(self.yaw_offset) if self.yaw_offset is not None else "None"}°'
        )
        self.get_logger().info(
            f'[NAV] Anchors: anchor=({self.anchor_x}, {self.anchor_y}), '
            f'odom_anchor=({self.odom_anchor_x}, {self.odom_anchor_y})'
        )
        self.get_logger().info(
            f'[NAV] Raw odom now: ({self.odom_x:.4f}, {self.odom_y:.4f}), '
            f'yaw={math.degrees(self.odom_yaw):.1f}°'
        )
        if self.uwb_x is not None:
            self.get_logger().info(
                f'[NAV] Raw UWB now: ({self.uwb_x:.4f}, {self.uwb_y:.4f}), '
                f'age={time.time() - self.uwb_stamp:.1f}s'
            )

        # Diagnose which fusion path will be used
        if self.anchor_x is None or self.odom_anchor_x is None:
            if self.uwb_x is not None:
                self.get_logger().warn('[NAV] Fusion: NOT ANCHORED → falling back to raw UWB')
            else:
                self.get_logger().warn('[NAV] Fusion: NOT ANCHORED, no UWB → falling back to raw odom')
        elif self.yaw_offset is not None:
            self.get_logger().info('[NAV] Fusion: anchored + yaw-rotated odom delta (best)')
        else:
            self.get_logger().warn('[NAV] Fusion: anchored but NO yaw_offset → unrotated odom delta')

        fx_init, fy_init = self.get_fused_position()
        init_dist = math.sqrt((goal_x - fx_init) ** 2 + (goal_y - fy_init) ** 2)
        self.get_logger().info(
            f'[NAV] Initial fused pos: ({fx_init:.4f}, {fy_init:.4f}), '
            f'initial dist to goal: {init_dist:.3f}m'
        )

        odom_at_start = (self.odom_x, self.odom_y, self.odom_count)

        while not self.cancel_nav:
            fx, fy = self.get_fused_position()
            heading = self.get_fused_heading()

            dx = goal_x - fx
            dy = goal_y - fy
            dist = math.sqrt(dx * dx + dy * dy)

            target_angle = math.atan2(dy, dx)
            if reverse:
                # Face AWAY from goal — back of robot points at target
                steer_angle = self.normalize_angle(target_angle + math.pi)
            else:
                steer_angle = target_angle
            angle_error = self.normalize_angle(steer_angle - heading)

            # Obstacle avoidance + boundary enforcement
            target_angle = math.atan2(dy, dx)
            if obstacle_avoidance:
                oa_speed, oa_steer, oa_state = self.get_obstacle_avoidance(heading, target_angle)
            else:
                oa_speed, oa_steer, oa_state = 1.0, 0.0, 'clear'
            boundary_speed = self.get_boundary_speed_scale(fx, fy, heading)

            # Update debug state (visible via /status → nav_debug)
            self.nav_debug = {
                'goal': [round(goal_x, 3), round(goal_y, 3)],
                'fused': [round(fx, 4), round(fy, 4)],
                'odom_raw': [round(self.odom_x, 4), round(self.odom_y, 4)],
                'heading_deg': round(math.degrees(heading), 1),
                'dist': round(dist, 4),
                'angle_err_deg': round(math.degrees(angle_error), 1),
                'odom_count': self.odom_count,
                'loop': loop_count,
                'elapsed': round(time.time() - start_time, 1),
                'reverse': reverse,
                'oa_state': oa_state,
                'oa_speed': round(oa_speed, 2),
                'oa_steer': round(oa_steer, 2),
                'boundary_speed': round(boundary_speed, 2),
            }

            if dist < GOAL_TOLERANCE:
                self.send_velocity(0.0, 0.0)
                self.get_logger().info(
                    f'[NAV] ✓ Reached ({goal_x:.2f}, {goal_y:.2f}) via {nav_mode}, '
                    f'error: {dist:.3f}m, loops: {loop_count}, '
                    f'time: {time.time() - start_time:.1f}s'
                )
                self.nav_debug = {}
                self.navigating = False
                return True

            if abs(angle_error) > ANGLE_TOLERANCE and oa_state == 'clear':
                # Normal turning toward goal — no obstacle interference
                angular = max(-ANGULAR_SPEED,
                              min(ANGULAR_SPEED, angle_error * 2.0))
                self.send_velocity(0.0, angular)
                mode = 'TURNING'
            else:
                linear = min(LINEAR_SPEED, dist * 0.5)
                # Apply obstacle + boundary speed scaling
                linear *= oa_speed * boundary_speed
                if reverse:
                    linear = -linear

                if oa_state != 'clear':
                    # Blend: avoidance steer + strong goal attraction
                    angular = oa_steer + angle_error * 0.8
                else:
                    angular = angle_error * 1.5

                angular = max(-ANGULAR_SPEED, min(ANGULAR_SPEED, angular))
                self.send_velocity(linear, angular)

                if oa_state == 'hard_avoid':
                    mode = 'HARD_AVOID'
                elif oa_state == 'steering_around':
                    mode = 'STEERING_AROUND'
                elif oa_state == 'adjusting':
                    mode = 'ADJUSTING'
                elif boundary_speed < 0.5:
                    mode = 'BOUNDARY'
                else:
                    mode = 'REVERSING' if reverse else 'DRIVING'

            # Log every ~1 second (every 20 loops at 20Hz)
            if loop_count % 20 == 0:
                odom_delta = math.sqrt(
                    (self.odom_x - odom_at_start[0]) ** 2 +
                    (self.odom_y - odom_at_start[1]) ** 2
                )
                self.get_logger().info(
                    f'[NAV] {mode} | fused=({fx:.3f},{fy:.3f}) '
                    f'dist={dist:.3f}m angle_err={math.degrees(angle_error):.1f}° '
                    f'heading={math.degrees(heading):.1f}° | '
                    f'odom_raw=({self.odom_x:.4f},{self.odom_y:.4f}) '
                    f'odom_msgs={self.odom_count - odom_at_start[2]} '
                    f'odom_moved={odom_delta:.4f}m'
                )

            loop_count += 1
            time.sleep(rate)

        self.send_velocity(0.0, 0.0)
        self.get_logger().info(
            f'[NAV] ✗ Cancelled after {loop_count} loops, {time.time() - start_time:.1f}s'
        )
        self.nav_debug = {}
        self.navigating = False
        return False

    # ── Cone chase helpers ──────────────────────────────────────────

    @property
    def cone_chase_active(self):
        return self.cone_chase_process is not None and self.cone_chase_process.poll() is None

    def read_cone_chase_status(self):
        try:
            with open(self.cone_chase_status_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def read_ultrasonic_status(self):
        try:
            with open(self.ultrasonic_status_file, 'r') as f:
                data = json.load(f)
            if time.time() - data.get('timestamp', 0) > 2.0:
                return None  # stale
            return data.get('readings')
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    # ── EV3 cone mechanism helpers ─────────────────────────────────

    def ev3_place_cone(self):
        """Tell the EV3 to drop a cone. Blocks until done."""
        import urllib.request
        self.get_logger().info(f'[EV3] Sending POST {EV3_MECHANISM_URL}/place ...')
        try:
            req = urllib.request.Request(EV3_MECHANISM_URL + '/place', method='POST')
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            self.get_logger().info(f'[EV3] Place response: {data}')
            # Wait for mechanism to finish
            for i in range(60):  # max 30s
                time.sleep(0.5)
                status = self.ev3_status()
                if status and not status.get('busy', True):
                    self.get_logger().info(f'[EV3] Place done after {(i+1)*0.5:.1f}s')
                    return True
                if i % 4 == 0:
                    self.get_logger().info(f'[EV3] Waiting for place... busy={status.get("busy") if status else "no response"}')
            self.get_logger().warn('[EV3] Place timed out after 30s')
            return True
        except Exception as e:
            self.get_logger().error(f'[EV3] Place FAILED: {e}')
            return False

    def ev3_pickup_cone(self):
        """Tell the EV3 to pick up a cone. Blocks until done."""
        import urllib.request
        self.get_logger().info(f'[EV3] Sending POST {EV3_MECHANISM_URL}/pickup ...')
        try:
            req = urllib.request.Request(EV3_MECHANISM_URL + '/pickup', method='POST')
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            self.get_logger().info(f'[EV3] Pickup response: {data}')
            # Wait for mechanism to finish
            for i in range(60):  # max 30s
                time.sleep(0.5)
                status = self.ev3_status()
                if status and not status.get('busy', True):
                    self.get_logger().info(f'[EV3] Pickup done after {(i+1)*0.5:.1f}s')
                    return True
                if i % 4 == 0:
                    self.get_logger().info(f'[EV3] Waiting for pickup... busy={status.get("busy") if status else "no response"}')
            self.get_logger().warn('[EV3] Pickup timed out after 30s')
            return True
        except Exception as e:
            self.get_logger().error(f'[EV3] Pickup FAILED: {e}')
            return False

    def ev3_status(self):
        """Get EV3 mechanism status."""
        import urllib.request
        try:
            resp = urllib.request.urlopen(EV3_MECHANISM_URL + '/status', timeout=2)
            return json.loads(resp.read())
        except Exception as e:
            self.get_logger().warn(f'[EV3] Status check failed: {e}')
            return None

    def get_obstacle_avoidance(self, heading, goal_angle):
        """Reactive obstacle avoidance — steers AROUND obstacles, never just stops.
        Only reacts to sensors that are relevant to the current direction of travel.

        Returns (speed_scale: 0.0-1.0, steer_override: rad/s or 0, state: str).
        state is one of: 'clear', 'adjusting', 'steering_around', 'hard_avoid'."""
        us = self.read_ultrasonic_status()
        if not us:
            return 1.0, 0.0, 'clear'

        fc = us.get('FC', 999)
        fl = us.get('FL', 999)
        fr = us.get('FR', 999)
        l  = us.get('L',  999)
        r  = us.get('R',  999)

        steer = 0.0
        speed = 1.0
        state = 'clear'

        # ── CASE 1: Front center blocked — must steer around ──
        if fc < OA_SLOW_START_CM:
            # Pick the clearer side to steer toward
            left_space = max(fl, l)    # how open is the left?
            right_space = max(fr, r)   # how open is the right?

            if fc <= OA_HARD_STOP_CM:
                # Very close — hard steer, slow crawl (don't full-stop)
                speed = 0.15  # crawl speed, not zero
                turn_strength = 0.8
                state = 'hard_avoid'
            else:
                # Approaching — proportional slowdown + moderate steer
                speed = 0.4 + 0.6 * (fc - OA_HARD_STOP_CM) / (OA_SLOW_START_CM - OA_HARD_STOP_CM)
                turn_strength = 0.5 * (1.0 - (fc - OA_HARD_STOP_CM) / (OA_SLOW_START_CM - OA_HARD_STOP_CM))
                state = 'steering_around'

            if left_space >= right_space:
                steer = turn_strength   # positive = turn left (CCW)
            else:
                steer = -turn_strength  # negative = turn right (CW)

        # ── CASE 2: Front-left or front-right blocked (asymmetric obstacle) ──
        elif fl < OA_SLOW_START_CM or fr < OA_SLOW_START_CM:
            if fl < fr and fl < OA_SLOW_START_CM:
                # Obstacle on front-left — steer right
                strength = 1.0 - (fl / OA_SLOW_START_CM)
                steer = -strength * 0.5
                speed = 0.6 + 0.4 * (fl / OA_SLOW_START_CM)
                state = 'adjusting'
            elif fr < fl and fr < OA_SLOW_START_CM:
                # Obstacle on front-right — steer left
                strength = 1.0 - (fr / OA_SLOW_START_CM)
                steer = strength * 0.5
                speed = 0.6 + 0.4 * (fr / OA_SLOW_START_CM)
                state = 'adjusting'

        # ── CASE 3: Side sensors — only matter if close AND heading toward them ──
        # (pure side obstacles don't need speed change, just gentle nudge)
        if l < OA_SIDE_BIAS_CM and state == 'clear':
            nudge = 0.2 * (1.0 - l / OA_SIDE_BIAS_CM)
            steer -= nudge  # nudge right (away from left)
            if l < OA_HARD_STOP_CM:
                state = 'adjusting'
        if r < OA_SIDE_BIAS_CM and state == 'clear':
            nudge = 0.2 * (1.0 - r / OA_SIDE_BIAS_CM)
            steer += nudge  # nudge left (away from right)
            if r < OA_HARD_STOP_CM:
                state = 'adjusting'

        return speed, steer, state

    def get_boundary_speed_scale(self, fx, fy, heading):
        """Slow down near field boundaries to prevent going out of bounds.
        Returns speed_scale 0.0-1.0."""
        scale = 1.0

        # Check how close we are to each boundary IN THE DIRECTION WE'RE HEADING
        cos_h = math.cos(heading)
        sin_h = math.sin(heading)

        # Only apply if heading toward a nearby boundary
        if cos_h > 0.1:  # heading toward +X
            margin = FIELD_MAX_X - fx
            if margin < BOUNDARY_SLOW_MARGIN:
                scale = min(scale, max(0.0, margin / BOUNDARY_SLOW_MARGIN))
        elif cos_h < -0.1:  # heading toward -X
            margin = fx - FIELD_MIN_X
            if margin < BOUNDARY_SLOW_MARGIN:
                scale = min(scale, max(0.0, margin / BOUNDARY_SLOW_MARGIN))

        if sin_h > 0.1:  # heading toward +Y
            margin = FIELD_MAX_Y - fy
            if margin < BOUNDARY_SLOW_MARGIN:
                scale = min(scale, max(0.0, margin / BOUNDARY_SLOW_MARGIN))
        elif sin_h < -0.1:  # heading toward -Y
            margin = fy - FIELD_MIN_Y
            if margin < BOUNDARY_SLOW_MARGIN:
                scale = min(scale, max(0.0, margin / BOUNDARY_SLOW_MARGIN))

        return scale

    def start_cone_chase(self, max_cones=0, camera=0):
        if self.cone_chase_active:
            return False, 'cone chase already active'
        if self.navigating:
            return False, 'mission is running'

        # Release camera stream if active so cone_chaser can use it
        if self.camera_streaming:
            self.camera_stop = True
            for _ in range(20):  # wait up to 1s
                if not self.camera_streaming:
                    break
                time.sleep(0.05)

        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cone_chaser.py')
        cmd = [
            sys.executable, script,
            '--no-display',
            '--status-file', self.cone_chase_status_file,
        ]
        if max_cones > 0:
            cmd += ['--max-cones', str(max_cones)]
        if camera != 0:
            cmd += ['--camera', str(camera)]

        self.cone_chase_process = subprocess.Popen(cmd)
        self.get_logger().info(f'Cone chase started (PID {self.cone_chase_process.pid})')
        return True, None

    def stop_cone_chase(self):
        if self.cone_chase_process is not None:
            try:
                self.cone_chase_process.send_signal(signal.SIGINT)
                self.cone_chase_process.wait(timeout=5)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                self.cone_chase_process.kill()
            self.cone_chase_process = None
        # Clean up status file
        try:
            os.remove(self.cone_chase_status_file)
        except FileNotFoundError:
            pass
        # Stop the robot
        self.send_velocity(0.0, 0.0)
        self.get_logger().info('Cone chase stopped')

    # ── Lock-on mode ─────────────────────────────────────────────

    def start_lock_on(self):
        if self.lock_on_running:
            return False, 'lock-on already active'
        if self.cone_chase_active:
            return False, 'cone chase active'
        if self.navigating:
            return False, 'mission is running'
        # Release camera stream if active
        if self.camera_streaming:
            self.camera_stop = True
            for _ in range(20):
                if not self.camera_streaming:
                    break
                time.sleep(0.05)
        self.lock_on_running = True
        threading.Thread(target=self._lock_on_loop, daemon=True).start()
        self.get_logger().info('Lock-on mode started')
        return True, None

    def stop_lock_on(self):
        self.lock_on_running = False
        # Loop thread will clean up; send stop immediately
        self.send_velocity(0.0, 0.0)
        self.lock_on_info = {}
        self.lock_on_frame = None
        self.get_logger().info('Lock-on mode stopped')

    def _lock_on_loop(self):
        ANGULAR_GAIN = 1.8
        TURN_THRESH = 0.25       # bearing fraction — turn in place above this
        ARRIVE_DIST = 0.15       # meters
        SLOW_DIST = 0.40
        MAX_SPEED = 0.15
        SLOW_SPEED = 0.08

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.get_logger().error('[LOCK-ON] Cannot open camera')
            self.lock_on_running = False
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        focal = compute_focal_length_px(actual_w, actual_h, CAMERA_DFOV_DEG)
        smoother = DetectionSmoother(hold_frames=10, match_distance=80, smooth=0.5)

        try:
            while self.lock_on_running:
                ret, frame = cap.read()
                if not ret:
                    continue

                raw_dets, rejected, _ = detect_red_cones(frame)
                detections = smoother.update(raw_dets)
                draw_detections(frame, detections, rejected, focal)

                if detections:
                    # Pick the largest (closest) cone
                    target = max(detections, key=lambda d: d[4])
                    tx, ty, tw, th, tarea, tellipse = target

                    # Bearing: -1 (left) to +1 (right)
                    cone_cx = tx + tw / 2.0
                    frame_cx = actual_w / 2.0
                    bearing = (cone_cx - frame_cx) / frame_cx

                    # Distance
                    dist_mm, mode = estimate_distance(tx, ty, tw, th, focal, actual_w)
                    dist_m = dist_mm / 1000.0

                    # Draw targeting overlay
                    center = (int(cone_cx), int(ty + th / 2))
                    cv2.circle(frame, center, 20, (0, 255, 255), 2)
                    cv2.line(frame, (center[0] - 25, center[1]), (center[0] + 25, center[1]), (0, 255, 255), 1)
                    cv2.line(frame, (center[0], center[1] - 25), (center[0], center[1] + 25), (0, 255, 255), 1)
                    cv2.putText(frame, f'LOCKED {dist_m:.2f}m', (10, actual_h - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                    # Proportional control
                    angular = -bearing * ANGULAR_GAIN

                    if dist_m <= ARRIVE_DIST:
                        self.send_velocity(0.0, 0.0)
                    elif abs(bearing) > TURN_THRESH:
                        self.send_velocity(0.0, angular)
                    elif dist_m < SLOW_DIST:
                        self.send_velocity(min(SLOW_SPEED, dist_m * 0.3), angular)
                    else:
                        self.send_velocity(min(MAX_SPEED, dist_m * 0.3), angular)

                    self.lock_on_info = {
                        'locked': True,
                        'distance_m': round(dist_m, 2),
                        'bearing_deg': round(bearing * 45, 1),
                    }
                else:
                    # No cone — stop
                    self.send_velocity(0.0, 0.0)
                    cv2.putText(frame, 'SEARCHING...', (10, actual_h - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    self.lock_on_info = {'locked': False}

                # Store frame for /camera
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                self.lock_on_frame = jpeg.tobytes()

                time.sleep(0.05)  # ~20Hz

        except Exception as e:
            self.get_logger().error(f'[LOCK-ON] Error: {e}')
        finally:
            cap.release()
            self.send_velocity(0.0, 0.0)
            self.lock_on_running = False
            self.lock_on_frame = None
            self.lock_on_info = {}

    # ── Cone collection ────────────────────────────────────────────

    def _compute_staging_point(self, cone_x, cone_y, from_x, from_y, offset=0.10):
        """Compute a point `offset` meters before the cone along the approach line."""
        dx = cone_x - from_x
        dy = cone_y - from_y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.01:
            # Same position — stage directly behind the cone (from origin direction)
            return cone_x - offset, cone_y
        # Point on approach line, `offset` meters before the cone
        return cone_x - (dx / dist) * offset, cone_y - (dy / dist) * offset

    def _visual_servo_collect(self, cap, focal, smoother, timeout=8.0):
        """Camera-based final approach to a cone. Returns 'collected' or 'missing'."""
        ANGULAR_GAIN = 1.8
        TURN_THRESH = 0.25
        SLOW_SPEED = 0.08
        RAM_SPEED = 0.06
        RAM_DURATION = 1.5
        ARRIVE_DIST_MM = 120
        MISSING_TIMEOUT = 2.0

        start_time = time.time()
        last_cone_seen = time.time()

        while time.time() - start_time < timeout and not self.collection_cancel:
            ret, frame = cap.read()
            if not ret:
                continue

            actual_w = frame.shape[1]
            actual_h = frame.shape[0]

            raw_dets, rejected, _ = detect_red_cones(frame)
            detections = smoother.update(raw_dets)
            draw_detections(frame, detections, rejected, focal)

            if detections:
                last_cone_seen = time.time()
                # Pick the largest (closest) cone
                target = max(detections, key=lambda d: d[4])
                tx, ty, tw, th, tarea, tellipse = target

                cone_cx = tx + tw / 2.0
                frame_cx = actual_w / 2.0
                bearing = (cone_cx - frame_cx) / frame_cx

                dist_mm, mode = estimate_distance(tx, ty, tw, th, focal, actual_w)

                # Draw targeting overlay
                center = (int(cone_cx), int(ty + th / 2))
                cv2.circle(frame, center, 20, (0, 255, 255), 2)
                cv2.line(frame, (center[0] - 25, center[1]), (center[0] + 25, center[1]), (0, 255, 255), 1)
                cv2.line(frame, (center[0], center[1] - 25), (center[0], center[1] + 25), (0, 255, 255), 1)
                cv2.putText(frame, f'COLLECT {dist_mm:.0f}mm', (10, actual_h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                angular = -bearing * ANGULAR_GAIN

                if dist_mm <= ARRIVE_DIST_MM:
                    # Ram: drive forward for RAM_DURATION then stop
                    self.get_logger().info(f'[COLLECT] Ramming! dist={dist_mm:.0f}mm')
                    ram_start = time.time()
                    while time.time() - ram_start < RAM_DURATION and not self.collection_cancel:
                        self.send_velocity(RAM_SPEED, 0.0)
                        # Keep reading frames for camera stream
                        ret2, frame2 = cap.read()
                        if ret2:
                            cv2.putText(frame2, 'RAMMING!', (10, actual_h - 15),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                            _, jpeg = cv2.imencode('.jpg', frame2, [cv2.IMWRITE_JPEG_QUALITY, 70])
                            self.collection_frame = jpeg.tobytes()
                        time.sleep(0.05)
                    self.send_velocity(0.0, 0.0)
                    return 'collected'
                elif abs(bearing) > TURN_THRESH:
                    # Turn in place
                    self.send_velocity(0.0, angular)
                else:
                    # Slow approach with angular correction
                    self.send_velocity(SLOW_SPEED, angular)
            else:
                # No cone seen
                self.send_velocity(0.0, 0.0)
                cv2.putText(frame, 'SEARCHING...', (10, actual_h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                if time.time() - last_cone_seen > MISSING_TIMEOUT:
                    self.get_logger().warn('[COLLECT] Cone missing — not seen for 2s')
                    return 'missing'

            # Store frame for /camera
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            self.collection_frame = jpeg.tobytes()

            time.sleep(0.05)  # ~20Hz

        return 'missing'

    def run_collection(self, cones, dwell_time=4.0):
        """Main collection loop. Runs in a thread."""
        self.collecting = True
        self.collection_cancel = False

        total = len(cones)
        results = [{'cone_id': c['id'], 'status': 'pending'} for c in cones]
        self.collection_status = {
            'active': True,
            'cone_index': 0,
            'cone_total': total,
            'cone_id': cones[0]['id'] if cones else '',
            'phase': 'navigating',
            'phase_detail': f'Navigating to cone 1/{total}',
            'results': results,
        }

        # Auto-calibrate if needed
        if not self.calibrated:
            self.collection_status['phase'] = 'navigating'
            self.collection_status['phase_detail'] = 'Calibrating...'
            if not self.calibrate():
                self.get_logger().error('[COLLECT] Calibration failed')
                self.collecting = False
                self.collection_status['active'] = False
                self.collection_status['phase'] = 'done'
                return

        # Open camera once for entire run
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.get_logger().error('[COLLECT] Cannot open camera')
            self.collecting = False
            self.collection_status['active'] = False
            self.collection_status['phase'] = 'done'
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        focal = compute_focal_length_px(actual_w, actual_h, CAMERA_DFOV_DEG)
        smoother = DetectionSmoother(hold_frames=10, match_distance=80, smooth=0.5)

        prev_x, prev_y = self.get_fused_position()

        try:
            for i, cone in enumerate(cones):
                if self.collection_cancel:
                    break

                cone_id = cone['id']
                cone_x = cone['x']
                cone_y = cone['y']

                self.get_logger().info(
                    f'[COLLECT] Cone {i+1}/{total}: id={cone_id} at ({cone_x:.2f}, {cone_y:.2f})'
                )

                # Update status: navigating
                self.collection_status.update({
                    'cone_index': i,
                    'cone_id': cone_id,
                    'phase': 'navigating',
                    'phase_detail': f'Navigating to cone {i+1}/{total}',
                })

                # Compute staging point (10cm before cone)
                staging_x, staging_y = self._compute_staging_point(
                    cone_x, cone_y, prev_x, prev_y
                )

                # Navigate to staging point
                self.re_anchor()
                self.cancel_nav = False
                success = self.navigate_to(staging_x, staging_y)
                if not success or self.collection_cancel:
                    results[i]['status'] = 'missing'
                    break

                # Turn to face the cone direction
                fx, fy = self.get_fused_position()
                target_angle = math.atan2(cone_y - fy, cone_x - fx)
                heading = self.get_fused_heading()
                angle_error = self.normalize_angle(target_angle - heading)
                turn_start = time.time()
                while abs(angle_error) > 0.15 and time.time() - turn_start < 3.0 and not self.collection_cancel:
                    angular = max(-ANGULAR_SPEED, min(ANGULAR_SPEED, angle_error * 2.0))
                    self.send_velocity(0.0, angular)
                    time.sleep(0.05)
                    heading = self.get_fused_heading()
                    angle_error = self.normalize_angle(target_angle - heading)
                self.send_velocity(0.0, 0.0)

                if self.collection_cancel:
                    results[i]['status'] = 'missing'
                    break

                # Visual servo phase
                self.collection_status.update({
                    'phase': 'visual_servo',
                    'phase_detail': f'Visual servo on cone {i+1}/{total}',
                })

                result = self._visual_servo_collect(cap, focal, smoother)
                results[i]['status'] = result

                if result == 'collected':
                    self.get_logger().info(f'[COLLECT] Cone {i+1}/{total} collected!')
                    self.collection_status.update({
                        'phase': 'dwell',
                        'phase_detail': f'Collected cone {i+1}/{total} — dwelling',
                    })
                    # Dwell
                    dwell_start = time.time()
                    while time.time() - dwell_start < dwell_time and not self.collection_cancel:
                        time.sleep(0.1)
                else:
                    self.get_logger().warn(f'[COLLECT] Cone {i+1}/{total} missing')
                    self.collection_status.update({
                        'phase': 'missing',
                        'phase_detail': f'Cone {i+1}/{total} not found',
                    })
                    time.sleep(1.0)

                # Update previous position for next staging point
                prev_x, prev_y = self.get_fused_position()

        except Exception as e:
            self.get_logger().error(f'[COLLECT] Error: {e}')
        finally:
            cap.release()
            self.send_velocity(0.0, 0.0)
            self.collecting = False
            self.collection_frame = None
            self.collection_status.update({
                'active': False,
                'phase': 'done',
                'phase_detail': 'Collection complete',
            })
            self.get_logger().info(
                f'[COLLECT] Done. '
                f'Collected: {sum(1 for r in results if r["status"] == "collected")}, '
                f'Missing: {sum(1 for r in results if r["status"] == "missing")}, '
                f'Pending: {sum(1 for r in results if r["status"] == "pending")}'
            )

    # ── Status helpers ────────────────────────────────────────────

    def get_display_pose(self):
        """Return the best available pose for the app to display.
        Always uses raw UWB for position (stable, no fused jitter).
        Falls back to odom only if UWB is unavailable."""
        if self.uwb_x is not None:
            return {'x': self.uwb_x, 'y': self.uwb_y, 'theta': self.get_fused_heading()}

        return {'x': self.odom_x, 'y': self.odom_y, 'theta': self.odom_yaw}


bridge_node: ConeBridgeNode = None


class Handler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/odom':
            self._json_response({
                'x': bridge_node.odom_x,
                'y': bridge_node.odom_y,
                'theta': bridge_node.odom_yaw,
            })
        elif self.path == '/status':
            pose = bridge_node.get_display_pose()
            chase_active = bridge_node.cone_chase_active
            chase_status = bridge_node.read_cone_chase_status() if chase_active else None
            self._json_response({
                'connected': True,
                'navigating': bridge_node.navigating,
                'calibrated': bridge_node.calibrated,
                'pose': pose,
                'uwb_pose': {
                    'x': bridge_node.uwb_x,
                    'y': bridge_node.uwb_y,
                } if bridge_node.uwb_x is not None else None,
                'odom_pose': {
                    'x': bridge_node.odom_x,
                    'y': bridge_node.odom_y,
                    'theta': bridge_node.odom_yaw,
                },
                'waypoint_index': bridge_node.waypoint_index,
                'waypoint_total': bridge_node.waypoint_total,
                'waypoint_state': bridge_node.waypoint_state,
                'dwell_remaining': round(bridge_node.dwell_remaining, 1),
                'cone_chase_active': chase_active,
                'cone_chase': chase_status,
                'lock_on_active': bridge_node.lock_on_running,
                'lock_on': bridge_node.lock_on_info if bridge_node.lock_on_running else None,
                'collection': bridge_node.collection_status if bridge_node.collecting or bridge_node.collection_status.get('active') else None,
                'ultrasonic': bridge_node.read_ultrasonic_status(),
                'nav_debug': bridge_node.nav_debug if bridge_node.navigating else None,
                'odom_count': bridge_node.odom_count,
                'uwb_count': bridge_node.uwb_count,
                'ev3_mechanism': bridge_node.ev3_status(),
            })
        elif self.path == '/camera':
            # If collection is running, serve its annotated frames
            if bridge_node.collecting:
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self._cors_headers()
                self.end_headers()
                try:
                    while bridge_node.collecting:
                        jpeg = bridge_node.collection_frame
                        if jpeg:
                            self.wfile.write(b'--frame\r\n')
                            self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                            self.wfile.write(jpeg)
                            self.wfile.write(b'\r\n')
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            # If lock-on is running, serve its annotated frames
            if bridge_node.lock_on_running:
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self._cors_headers()
                self.end_headers()
                try:
                    while bridge_node.lock_on_running:
                        jpeg = bridge_node.lock_on_frame
                        if jpeg:
                            self.wfile.write(b'--frame\r\n')
                            self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                            self.wfile.write(jpeg)
                            self.wfile.write(b'\r\n')
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            if bridge_node.cone_chase_active:
                self._json_response({'error': 'camera in use by cone chase'}, 409)
                return
            if bridge_node.camera_streaming:
                self._json_response({'error': 'camera already streaming'}, 409)
                return

            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                self._json_response({'error': 'cannot open camera'}, 500)
                return

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            focal = compute_focal_length_px(actual_w, actual_h, CAMERA_DFOV_DEG)

            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self._cors_headers()
            self.end_headers()

            bridge_node.camera_streaming = True
            bridge_node.camera_stop = False

            try:
                while not bridge_node.camera_stop:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    # Stop if cone chase started while we're streaming
                    if bridge_node.cone_chase_active:
                        break

                    # Detection overlay
                    detections, rejected, _ = detect_red_cones(frame)
                    draw_detections(frame, detections, rejected, focal)

                    _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    self.wfile.write(b'--frame\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                    self.wfile.write(jpeg.tobytes())
                    self.wfile.write(b'\r\n')

                    time.sleep(0.1)  # ~10 fps
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                cap.release()
                bridge_node.camera_streaming = False

        else:
            self._json_response({'error': 'not found'}, 404)

    def do_POST(self):
        body = self._read_body()

        if self.path == '/cmd_vel':
            if bridge_node.cone_chase_active:
                self._json_response({'error': 'cone chase active'}, 409)
                return
            if bridge_node.lock_on_running:
                self._json_response({'error': 'lock-on active'}, 409)
                return
            bridge_node.send_velocity(
                body.get('linear', 0.0),
                body.get('angular', 0.0),
            )
            self._json_response({'ok': True})

        elif self.path == '/stop':
            if bridge_node.cone_chase_active:
                bridge_node.stop_cone_chase()
            if bridge_node.lock_on_running:
                bridge_node.stop_lock_on()
            if bridge_node.collecting:
                bridge_node.collection_cancel = True
            bridge_node.stop()
            self._json_response({'ok': True})

        elif self.path == '/navigate':
            if bridge_node.cone_chase_active:
                self._json_response({'error': 'cone chase active'}, 409)
                return
            if bridge_node.lock_on_running:
                self._json_response({'error': 'lock-on active'}, 409)
                return
            x = body.get('x', 0.0)
            y = body.get('y', 0.0)

            def nav():
                # Auto-calibrate on first navigation
                if not bridge_node.calibrated:
                    if not bridge_node.calibrate():
                        return
                bridge_node.re_anchor()
                bridge_node.navigate_to(x, y)

            threading.Thread(target=nav, daemon=True).start()
            self._json_response({'ok': True, 'msg': 'navigation started'})

        elif self.path == '/waypoints':
            if bridge_node.cone_chase_active:
                self._json_response({'error': 'cone chase active'}, 409)
                return
            if bridge_node.lock_on_running:
                self._json_response({'error': 'lock-on active'}, 409)
                return
            waypoints = body.get('waypoints', [])
            dwell_time = body.get('dwell_time', 0)
            use_obstacle_avoidance = body.get('obstacle_avoidance', True)
            mechanism_action = body.get('mechanism', None)  # 'place' | 'pickup' | None

            bridge_node.get_logger().info(
                f'[WAYPOINTS] Received: {len(waypoints)} waypoints, '
                f'dwell={dwell_time}, oa={use_obstacle_avoidance}, '
                f'mechanism={mechanism_action}'
            )

            # When mechanism is active: drive FORWARD to first waypoint,
            # then REVERSE to each subsequent waypoint (so we never drive
            # over a cone we just placed)
            use_reverse = dwell_time > 0

            def run_waypoints():
                # Auto-calibrate on first navigation
                if not bridge_node.calibrated:
                    if not bridge_node.calibrate():
                        bridge_node.waypoint_state = 'idle'
                        return

                # Track whether we just placed a cone (need to reverse to next)
                just_placed = False

                bridge_node.waypoint_total = len(waypoints)
                for i, wp in enumerate(waypoints):
                    bridge_node.waypoint_index = i
                    bridge_node.waypoint_state = 'navigating'

                    # Re-anchor from UWB before each waypoint
                    bridge_node.re_anchor()

                    # After placing a cone, reverse to the next waypoint
                    # so we don't drive over the cone we just dropped
                    nav_reverse = just_placed and mechanism_action == 'place'

                    bridge_node.get_logger().info(
                        f'Waypoint {i+1}/{len(waypoints)}: '
                        f'({wp["x"]:.2f}, {wp["y"]:.2f})'
                        f'{" [REVERSE]" if nav_reverse else " [FORWARD]"}'
                    )
                    success = bridge_node.navigate_to(wp['x'], wp['y'], reverse=nav_reverse, obstacle_avoidance=use_obstacle_avoidance)
                    if not success:
                        bridge_node.get_logger().warn(
                            f'Waypoint {i+1} cancelled'
                        )
                        break

                    # UWB verification: check raw UWB distance to goal
                    # If fused nav got us close but UWB says we're off, retry
                    if bridge_node.uwb_x is not None:
                        for retry in range(UWB_VERIFY_MAX_RETRIES):
                            time.sleep(0.3)  # let UWB settle
                            uwb_dx = wp['x'] - bridge_node.uwb_x
                            uwb_dy = wp['y'] - bridge_node.uwb_y
                            uwb_dist = math.sqrt(uwb_dx * uwb_dx + uwb_dy * uwb_dy)
                            if uwb_dist <= UWB_VERIFY_TOLERANCE:
                                bridge_node.get_logger().info(
                                    f'[NAV] UWB verify OK: {uwb_dist:.3f}m from goal'
                                )
                                break
                            bridge_node.get_logger().warn(
                                f'[NAV] UWB verify FAILED: {uwb_dist:.3f}m from goal '
                                f'(>{UWB_VERIFY_TOLERANCE}m), retry {retry+1}/{UWB_VERIFY_MAX_RETRIES}'
                            )
                            bridge_node.re_anchor()
                            success = bridge_node.navigate_to(wp['x'], wp['y'], reverse=use_reverse, obstacle_avoidance=use_obstacle_avoidance)
                            if not success:
                                break
                        if not success:
                            bridge_node.get_logger().warn(
                                f'Waypoint {i+1} cancelled during UWB verify'
                            )
                            break

                    # Trigger EV3 mechanism at waypoint (if requested)
                    just_placed = False
                    if mechanism_action and not bridge_node.cancel_nav:
                        bridge_node.waypoint_state = 'mechanism'
                        bridge_node.get_logger().info(
                            f'[EV3] Triggering {mechanism_action} at waypoint {i+1}'
                        )
                        if mechanism_action == 'place':
                            bridge_node.ev3_place_cone()
                            just_placed = True
                        elif mechanism_action == 'pickup':
                            bridge_node.ev3_pickup_cone()

                    # Dwell at waypoint
                    if dwell_time > 0:
                        bridge_node.waypoint_state = 'dwelling'
                        bridge_node.dwell_remaining = dwell_time
                        bridge_node.get_logger().info(
                            f'Dwelling at waypoint {i+1} for {dwell_time}s'
                        )
                        elapsed = 0.0
                        while elapsed < dwell_time and not bridge_node.cancel_nav:
                            time.sleep(0.1)
                            elapsed += 0.1
                            bridge_node.dwell_remaining = max(0, dwell_time - elapsed)
                        bridge_node.dwell_remaining = 0.0
                        if bridge_node.cancel_nav:
                            bridge_node.get_logger().warn(
                                f'Dwell at waypoint {i+1} cancelled'
                            )
                            break

                bridge_node.waypoint_state = 'completed'
                bridge_node.waypoint_index = -1
                bridge_node.waypoint_total = 0
                bridge_node.dwell_remaining = 0.0
                bridge_node.get_logger().info('Waypoint sequence complete')

            threading.Thread(target=run_waypoints, daemon=True).start()
            self._json_response({
                'ok': True,
                'msg': f'executing {len(waypoints)} waypoints',
            })

        elif self.path == '/mechanism/place':
            def do_place():
                bridge_node.ev3_place_cone()
            threading.Thread(target=do_place, daemon=True).start()
            self._json_response({'ok': True, 'msg': 'placing cone'})

        elif self.path == '/mechanism/pickup':
            def do_pickup():
                bridge_node.ev3_pickup_cone()
            threading.Thread(target=do_pickup, daemon=True).start()
            self._json_response({'ok': True, 'msg': 'picking up cone'})

        elif self.path == '/calibrate':
            def cal():
                bridge_node.calibrate()
            threading.Thread(target=cal, daemon=True).start()
            self._json_response({'ok': True, 'msg': 'calibration started'})

        elif self.path == '/cone-chase/start':
            max_cones = body.get('max_cones', 0)
            camera = body.get('camera', 0)
            ok, err = bridge_node.start_cone_chase(max_cones=max_cones, camera=camera)
            if ok:
                self._json_response({'ok': True})
            else:
                self._json_response({'error': err}, 409)

        elif self.path == '/cone-chase/stop':
            bridge_node.stop_cone_chase()
            self._json_response({'ok': True})

        elif self.path == '/lock-on/start':
            ok, err = bridge_node.start_lock_on()
            if ok:
                self._json_response({'ok': True})
            else:
                self._json_response({'error': err}, 409)

        elif self.path == '/lock-on/stop':
            bridge_node.stop_lock_on()
            self._json_response({'ok': True})

        elif self.path == '/collect':
            if bridge_node.collecting:
                self._json_response({'error': 'collection already active'}, 409)
                return
            if bridge_node.cone_chase_active:
                self._json_response({'error': 'cone chase active'}, 409)
                return
            if bridge_node.lock_on_running:
                self._json_response({'error': 'lock-on active'}, 409)
                return
            if bridge_node.navigating:
                self._json_response({'error': 'navigation active'}, 409)
                return

            cones = body.get('cones', [])
            dwell_time = body.get('dwell_time', 4.0)
            if not cones:
                self._json_response({'error': 'no cones provided'}, 400)
                return

            # Release camera stream if active
            if bridge_node.camera_streaming:
                bridge_node.camera_stop = True
                for _ in range(20):
                    if not bridge_node.camera_streaming:
                        break
                    time.sleep(0.05)

            threading.Thread(
                target=bridge_node.run_collection,
                args=(cones, dwell_time),
                daemon=True,
            ).start()
            self._json_response({'ok': True, 'msg': f'collecting {len(cones)} cones'})

        elif self.path == '/collect/stop':
            bridge_node.collection_cancel = True
            bridge_node.send_velocity(0.0, 0.0)
            self._json_response({'ok': True})

        else:
            self._json_response({'error': 'not found'}, 404)

    def log_message(self, format, *args):
        print(f"[HTTP] {format % args}")


def main():
    global bridge_node
    rclpy.init()
    bridge_node = ConeBridgeNode()

    spin_thread = threading.Thread(
        target=lambda: rclpy.spin(bridge_node), daemon=True
    )
    spin_thread.start()

    server = ThreadedHTTPServer(('0.0.0.0', PORT), Handler)
    print(f'ConeBridge HTTP server listening on port {PORT}')
    print(f'Endpoints:')
    print(f'  GET  /status           - connection status + fused pose')
    print(f'  GET  /odom             - raw odometry pose')
    print(f'  GET  /camera           - MJPEG camera stream with detection overlay')
    print(f'  POST /cmd_vel          - send velocity')
    print(f'  POST /stop             - stop the robot')
    print(f'  POST /navigate         - go to point (auto-calibrates)')
    print(f'  POST /waypoints        - execute waypoint sequence')
    print(f'  POST /calibrate        - manually trigger calibration')
    print(f'  POST /cone-chase/start - start autonomous cone chase')
    print(f'  POST /cone-chase/stop  - stop cone chase')
    print(f'  POST /lock-on/start    - start visual lock-on mode')
    print(f'  POST /lock-on/stop     - stop lock-on mode')
    print(f'  POST /collect          - start cone collection')
    print(f'  POST /collect/stop     - stop cone collection')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if bridge_node.cone_chase_active:
            bridge_node.stop_cone_chase()
        if bridge_node.lock_on_running:
            bridge_node.stop_lock_on()
        if bridge_node.collecting:
            bridge_node.collection_cancel = True
        bridge_node.stop()
        bridge_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
