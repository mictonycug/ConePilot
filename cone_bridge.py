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
GOAL_TOLERANCE = 0.08     # meters - how close is "arrived"
ANGLE_TOLERANCE = 0.1     # radians - how aligned before driving forward
CALIBRATION_DRIVE_DIST = 0.5  # meters to drive during calibration


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

        # Camera stream state
        self.camera_streaming = False
        self.camera_stop = False

        # Lock-on mode state
        self.lock_on_running = False
        self.lock_on_info = {}       # {locked, distance_m, bearing_deg}
        self.lock_on_frame = None    # latest JPEG bytes for /camera

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

    def navigate_to(self, goal_x, goal_y):
        """Proportional go-to-point using UWB+odom fused position."""
        self.navigating = True
        self.cancel_nav = False
        rate = 0.05  # 20Hz
        loop_count = 0
        start_time = time.time()

        self.get_logger().info(
            f'[NAV] ── Starting navigation to ({goal_x:.3f}, {goal_y:.3f}) ──'
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
            angle_error = self.normalize_angle(target_angle - heading)

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
            }

            if dist < GOAL_TOLERANCE:
                self.send_velocity(0.0, 0.0)
                self.get_logger().info(
                    f'[NAV] ✓ Reached ({goal_x:.2f}, {goal_y:.2f}), '
                    f'error: {dist:.3f}m, loops: {loop_count}, '
                    f'time: {time.time() - start_time:.1f}s'
                )
                self.nav_debug = {}
                self.navigating = False
                return True

            if abs(angle_error) > ANGLE_TOLERANCE:
                angular = max(-ANGULAR_SPEED,
                              min(ANGULAR_SPEED, angle_error * 2.0))
                self.send_velocity(0.0, angular)
                mode = 'TURNING'
            else:
                linear = min(LINEAR_SPEED, dist * 0.5)
                angular = angle_error * 1.5
                self.send_velocity(linear, angular)
                mode = 'DRIVING'

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

    # ── Status helpers ────────────────────────────────────────────

    def get_display_pose(self):
        """Return the best available pose for the app to display.
        Prefers fused position; falls back to raw UWB; then raw odom."""
        if self.calibrated and self.anchor_x is not None:
            fx, fy = self.get_fused_position()
            return {'x': fx, 'y': fy, 'theta': self.get_fused_heading()}

        if self.uwb_x is not None:
            return {'x': self.uwb_x, 'y': self.uwb_y, 'theta': self.odom_yaw}

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
                'nav_debug': bridge_node.nav_debug if bridge_node.navigating else None,
                'odom_count': bridge_node.odom_count,
                'uwb_count': bridge_node.uwb_count,
            })
        elif self.path == '/camera':
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

            def run_waypoints():
                # Auto-calibrate on first navigation
                if not bridge_node.calibrated:
                    if not bridge_node.calibrate():
                        bridge_node.waypoint_state = 'idle'
                        return

                bridge_node.waypoint_total = len(waypoints)
                for i, wp in enumerate(waypoints):
                    bridge_node.waypoint_index = i
                    bridge_node.waypoint_state = 'navigating'

                    # Re-anchor from UWB before each waypoint
                    bridge_node.re_anchor()

                    bridge_node.get_logger().info(
                        f'Waypoint {i+1}/{len(waypoints)}: '
                        f'({wp["x"]:.2f}, {wp["y"]:.2f})'
                    )
                    success = bridge_node.navigate_to(wp['x'], wp['y'])
                    if not success:
                        bridge_node.get_logger().warn(
                            f'Waypoint {i+1} cancelled'
                        )
                        break

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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if bridge_node.cone_chase_active:
            bridge_node.stop_cone_chase()
        if bridge_node.lock_on_running:
            bridge_node.stop_lock_on()
        bridge_node.stop()
        bridge_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
