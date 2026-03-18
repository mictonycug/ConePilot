#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, TransformStamped
from nav_msgs.msg import Odometry
from tf2_ros import TransformBroadcaster
import serial
import re
import time
import json
import os
import numpy as np
import math

ANCHORS = {
    '029F': np.array([0.00, 0.00]),
    '0816': np.array([3.50, 0.00]),
    'DB9A': np.array([0.00, 3.00]),
    'DC06': np.array([3.50, 3.00]),
}

# Sorted anchor IDs — MUST be consistent across readings
SORTED_ANCHOR_IDS = sorted(ANCHORS.keys())

# Max possible distance in the space (diagonal + margin)
MAX_DISTANCE = 5.0  # sqrt(3.5^2 + 3^2) ≈ 4.61 + margin

def trilaterate(anchors, distances):
    """Trilaterate using a fixed reference anchor to avoid jitter
    from changing reference between readings."""
    # Always use the same reference anchor (first in sorted order that
    # has a distance reading). This prevents jitter from reference switching.
    available = [aid for aid in SORTED_ANCHOR_IDS if aid in distances]
    if len(available) < 3:
        return None

    ref_id = available[0]
    x0, y0 = anchors[ref_id]
    d0 = distances[ref_id]

    A = []
    b = []
    w = []
    for aid in available[1:]:
        xi, yi = anchors[aid]
        di = distances[aid]
        A.append([2*(xi - x0), 2*(yi - y0)])
        b.append(d0**2 - di**2 + xi**2 - x0**2 + yi**2 - y0**2)
        w.append(1.0 / (di + 0.1))

    A = np.array(A)
    b = np.array(b)
    W = np.diag(w)

    try:
        # Weighted least squares: (A^T W A)^-1 A^T W b
        AtW = A.T @ W
        result = np.linalg.solve(AtW @ A, AtW @ b)
        return result
    except np.linalg.LinAlgError:
        return None

def residual_check(anchors, distances, pos, threshold=0.20):
    """Check each anchor's residual. Return distances dict with outliers removed.
    Tighter threshold (20cm) catches more multipath/NLOS errors."""
    clean = {}
    for aid, d_meas in distances.items():
        ax, ay = anchors[aid]
        d_expected = math.sqrt((pos[0] - ax)**2 + (pos[1] - ay)**2)
        if abs(d_meas - d_expected) < threshold:
            clean[aid] = d_meas
    return clean

class UWBNode(Node):
    def __init__(self):
        super().__init__('uwb_node')

        self.declare_parameter('port', '/dev/serial/by-id/usb-SEGGER_J-Link_000760180803-if00')
        self.declare_parameter('baud', 115200)

        port = self.get_parameter('port').value
        baud = self.get_parameter('baud').value

        self.pose_pub = self.create_publisher(PoseStamped, '/uwb/pose', 10)
        self.tf_broadcaster = TransformBroadcaster(self)

        self.odom_x = 0.0
        self.odom_y = 0.0
        self.odom_yaw = 0.0
        self.odom_vx = 0.0
        self.odom_vz = 0.0
        self.odom_sub = self.create_subscription(Odometry, '/odom', self.odom_callback, 10)

        self.anchor_pattern = re.compile(r'([0-9A-Fa-f]{4})\[\d+\.\d+,\d+\.\d+,\d+\.\d+\]=(\d+\.\d+)')
        self.buffer = ''

        # ── Filtering parameters ──────────────────────────────────────
        # Stage 1: Per-anchor median filter on raw ranges
        self.dist_history = {aid: [] for aid in ANCHORS}
        self.dist_window = 5  # 5 = sweet spot (impulse removal without lag)

        # Stage 2: Per-anchor EMA on ranges (smooths residual noise after median)
        self.range_ema = {}  # {anchor_id: smoothed_distance}
        self.range_ema_alpha = 0.3

        # Stage 3: MAD-based outlier rejection per anchor
        self.dist_extended_history = {aid: [] for aid in ANCHORS}
        self.dist_extended_window = 15  # for computing MAD
        self.mad_threshold = 3.0  # reject if |range - median| > 3 * MAD

        # Stage 4: Variance-based trilateration weighting
        self.range_variance = {aid: 0.01 for aid in ANCHORS}  # initial variance estimate

        # Stage 5: Adaptive position EMA with velocity-based alpha
        self.filtered_x = None
        self.filtered_y = None
        self.alpha_moving = 0.25   # responsive when robot moves
        self.alpha_still = 0.03    # heavy smoothing when stationary

        # Velocity estimation from position changes (for stationary detection)
        self.pos_history = []  # [(x, y, time), ...]
        self.pos_history_window = 10
        self.velocity_estimate = 0.0
        self.velocity_ema_alpha = 0.15
        self.stationary_threshold = 0.02  # m/s
        self.moving_threshold = 0.05      # m/s

        # Load per-anchor calibration (bias corrections)
        self.anchor_bias = {}
        cal_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uwb_calibration.json')
        try:
            with open(cal_path, 'r') as f:
                cal = json.load(f)
            for aid, data in cal.items():
                self.anchor_bias[aid] = data.get('bias', 0.0)
            self.get_logger().info(
                f'Loaded UWB calibration: {self.anchor_bias}')
        except FileNotFoundError:
            self.get_logger().warn(
                'No uwb_calibration.json found — running without per-anchor corrections')

        try:
            self.serial_port = serial.Serial(port, baud, timeout=0.1)
            self.get_logger().info(f'Connected to UWB tag on {port}')
            time.sleep(1)

            self.serial_port.write(b'\r')
            time.sleep(0.1)
            self.serial_port.write(b'\r')
            time.sleep(1)
            self.serial_port.reset_input_buffer()
            self.serial_port.write(b'les\r')
            time.sleep(0.5)
            self.serial_port.reset_input_buffer()

        except serial.SerialException as e:
            self.get_logger().error(f'Failed to open serial port: {e}')
            raise

        self.timer = self.create_timer(0.05, self.read_serial)
        self.msg_count = 0

    def odom_callback(self, msg):
        self.odom_x = msg.pose.pose.position.x
        self.odom_y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        self.odom_yaw = math.atan2(2.0*(q.w*q.z + q.x*q.y), 1.0 - 2.0*(q.y*q.y + q.z*q.z))
        self.odom_vx = msg.twist.twist.linear.x
        self.odom_vz = msg.twist.twist.angular.z

    def filter_range(self, aid, raw_d):
        """Multi-stage range filtering for a single anchor.
        Returns filtered distance, or None if rejected as outlier."""

        # Stage 1: MAD-based outlier rejection
        ext_hist = self.dist_extended_history[aid]
        ext_hist.append(raw_d)
        if len(ext_hist) > self.dist_extended_window:
            ext_hist.pop(0)

        if len(ext_hist) >= 5:
            median_val = float(np.median(ext_hist))
            mad = float(np.median(np.abs(np.array(ext_hist) - median_val)))
            if mad < 0.001:
                mad = 0.001  # avoid division by zero
            if abs(raw_d - median_val) > self.mad_threshold * mad:
                return None  # reject this reading

            # Update per-anchor variance estimate
            self.range_variance[aid] = float(np.var(ext_hist))

        # Stage 2: Median filter
        hist = self.dist_history[aid]
        hist.append(raw_d)
        if len(hist) > self.dist_window:
            hist.pop(0)

        if len(hist) >= 3:
            median_d = float(np.median(hist))
        else:
            median_d = raw_d

        # Stage 3: Per-anchor range EMA
        if aid in self.range_ema:
            self.range_ema[aid] = (self.range_ema_alpha * median_d +
                                   (1 - self.range_ema_alpha) * self.range_ema[aid])
        else:
            self.range_ema[aid] = median_d

        return self.range_ema[aid]

    def estimate_velocity(self, x, y):
        """Estimate robot velocity from position history for adaptive smoothing."""
        now = time.monotonic()
        self.pos_history.append((x, y, now))
        if len(self.pos_history) > self.pos_history_window:
            self.pos_history.pop(0)

        if len(self.pos_history) >= 2:
            oldest = self.pos_history[0]
            newest = self.pos_history[-1]
            dt = newest[2] - oldest[2]
            if dt > 0:
                dist = math.sqrt((newest[0] - oldest[0])**2 + (newest[1] - oldest[1])**2)
                instant_vel = dist / dt
                self.velocity_estimate = (self.velocity_ema_alpha * instant_vel +
                                          (1 - self.velocity_ema_alpha) * self.velocity_estimate)

    def get_adaptive_alpha(self):
        """Compute position EMA alpha based on motion state.
        Uses both odom velocity and position-derived velocity for robustness."""
        # Use odom velocity as primary signal (instant, no lag)
        odom_moving = abs(self.odom_vx) > 0.01 or abs(self.odom_vz) > 0.05

        if odom_moving:
            return self.alpha_moving

        # When odom says stationary, use position-derived velocity for confirmation
        if self.velocity_estimate < self.stationary_threshold:
            return self.alpha_still
        elif self.velocity_estimate > self.moving_threshold:
            return self.alpha_moving
        else:
            # Linear interpolation in transition zone
            t = ((self.velocity_estimate - self.stationary_threshold) /
                 (self.moving_threshold - self.stationary_threshold))
            return self.alpha_still + t * (self.alpha_moving - self.alpha_still)

    def filter_position(self, x, y):
        # Clamp to valid area with small margin
        x = np.clip(x, -0.3, 3.8)
        y = np.clip(y, -0.3, 3.3)

        # Update velocity estimate from raw trilaterated position
        self.estimate_velocity(x, y)

        if self.filtered_x is None:
            self.filtered_x = float(x)
            self.filtered_y = float(y)
        else:
            alpha = self.get_adaptive_alpha()

            dx = x - self.filtered_x
            dy = y - self.filtered_y
            jump = math.sqrt(dx*dx + dy*dy)
            if jump > 0.3:
                # Suspicious jump — barely move
                self.filtered_x += 0.02 * dx
                self.filtered_y += 0.02 * dy
            else:
                self.filtered_x = alpha * x + (1 - alpha) * self.filtered_x
                self.filtered_y = alpha * y + (1 - alpha) * self.filtered_y

        return self.filtered_x, self.filtered_y

    def read_serial(self):
        try:
            if self.serial_port.in_waiting:
                raw = self.serial_port.read(self.serial_port.in_waiting)
                self.buffer += raw.decode('utf-8', errors='ignore')

                while '\n' in self.buffer:
                    line, self.buffer = self.buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue

                    matches = self.anchor_pattern.findall(line)
                    if len(matches) >= 3:
                        raw_distances = {}
                        for anchor_id, dist_str in matches:
                            anchor_id = anchor_id.upper()
                            d = float(dist_str)
                            if anchor_id in ANCHORS and 0.05 < d < MAX_DISTANCE:
                                raw_distances[anchor_id] = d

                        if len(raw_distances) < 3:
                            continue

                        # Step 0: Apply per-anchor bias correction
                        for aid in raw_distances:
                            if aid in self.anchor_bias:
                                raw_distances[aid] -= self.anchor_bias[aid]

                        # Step 1: Multi-stage range filtering (MAD rejection + median + EMA)
                        distances = {}
                        for aid, d in raw_distances.items():
                            filtered_d = self.filter_range(aid, d)
                            if filtered_d is not None:
                                distances[aid] = filtered_d

                        if len(distances) < 3:
                            continue

                        # Step 2: Variance-weighted trilateration
                        pos = trilaterate(ANCHORS, distances)
                        if pos is None:
                            continue

                        # Step 3: Residual check (tighter 20cm threshold)
                        clean = residual_check(ANCHORS, distances, pos)
                        if len(clean) >= 3 and len(clean) < len(distances):
                            pos2 = trilaterate(ANCHORS, clean)
                            if pos2 is not None:
                                pos = pos2

                        # Step 4: Adaptive position EMA
                        sx, sy = self.filter_position(float(pos[0]), float(pos[1]))
                        now = self.get_clock().now().to_msg()

                        # Publish PoseStamped
                        msg = PoseStamped()
                        msg.header.stamp = now
                        msg.header.frame_id = 'map'
                        msg.pose.position.x = sx
                        msg.pose.position.y = sy
                        msg.pose.position.z = 0.0
                        msg.pose.orientation.w = 1.0
                        self.pose_pub.publish(msg)

                        # Publish map -> odom transform
                        t = TransformStamped()
                        t.header.stamp = now
                        t.header.frame_id = 'map'
                        t.child_frame_id = 'odom'
                        t.transform.translation.x = sx - self.odom_x
                        t.transform.translation.y = sy - self.odom_y
                        t.transform.translation.z = 0.0
                        t.transform.rotation.w = 1.0
                        self.tf_broadcaster.sendTransform(t)

                        self.msg_count += 1
                        if self.msg_count % 10 == 1:
                            self.get_logger().info(
                                f'UWB pos: x={sx:.3f} y={sy:.3f} | '
                                f'raw: ({pos[0]:.2f},{pos[1]:.2f}) | '
                                f'anchors: {len(distances)} | '
                                f'alpha: {self.get_adaptive_alpha():.3f} | '
                                f'vel: {self.velocity_estimate:.3f}m/s')
        except Exception as e:
            self.get_logger().warn(f'Read error: {e}')

    def destroy_node(self):
        if hasattr(self, 'serial_port') and self.serial_port.is_open:
            self.serial_port.write(b'\r')
            self.serial_port.close()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = UWBNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
