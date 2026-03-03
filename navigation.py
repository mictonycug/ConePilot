#!/usr/bin/env python3
"""
UWB + Odometry fused navigation for TurtleBot.
Accepts goals via /nav topic (PoseStamped) or CLI args.
Re-anchors from UWB before each new waypoint to eliminate odom drift.

NOTE: This standalone node is superseded by cone_bridge.py which embeds
the same UWB+odom fusion logic and exposes it via HTTP for the ConePilot app.
Keep this file for standalone CLI testing only.
"""

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseStamped, TwistStamped
import math
import sys


class Navigation(Node):
    def __init__(self, goal_x=None, goal_y=None):
        super().__init__('navigation')

        # Goal coordinates (None = waiting for /nav goal)
        self.goal_x = float(goal_x) if goal_x is not None else None
        self.goal_y = float(goal_y) if goal_y is not None else None
        self.has_goal = self.goal_x is not None

        # Odom coordinates (latest)
        self.odom_x = 0.0
        self.odom_y = 0.0
        self.odom_yaw = 0.0
        self.odom_received = False

        # Odom anchor (reset before each waypoint navigation)
        self.odom_anchor_x = None
        self.odom_anchor_y = None

        # UWB position (continuously updated)
        self.uwb_x = None
        self.uwb_y = None
        self.uwb_received = False

        # World-frame anchor (reset before each waypoint)
        self.anchor_x = None
        self.anchor_y = None

        # Calibration state
        self.calibrated = False
        self.calibration_start_uwb_x = None
        self.calibration_start_uwb_y = None
        self.calibration_start_odom_yaw = None
        self.calibration_distance = 0.0
        self.calibration_target = 0.5
        self.yaw_offset = None

        # Navigation parameters
        self.goal_tolerance = 0.02   # 2cm
        self.max_speed = 0.20
        self.max_turn_speed = 0.5
        self.turn_threshold = 0.2

        if self.has_goal:
            self.get_logger().info(f'Initial goal: ({self.goal_x}, {self.goal_y})')
        else:
            self.get_logger().info('Waiting for goal on /nav topic...')

        self.create_timer(0.1, self.main_loop)

        # Subscribers
        self.odom_subscription = self.create_subscription(
            Odometry, '/odom', self.odom_callback, 10
        )
        self.uwb_subscription = self.create_subscription(
            PoseStamped, '/uwb/pose', self.uwb_callback, 10
        )
        # Accept new goals at runtime via /nav
        self.nav_subscription = self.create_subscription(
            PoseStamped, '/nav', self.nav_callback, 10
        )

        # Publisher
        self.cmd_pub = self.create_publisher(TwistStamped, '/cmd_vel', 10)

    def odom_callback(self, msg):
        self.odom_x = msg.pose.pose.position.x
        self.odom_y = msg.pose.pose.position.y

        q = msg.pose.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self.odom_yaw = math.atan2(siny_cosp, cosy_cosp)

        if not self.odom_received:
            self.odom_received = True
            self.get_logger().info(
                f'Odom online: ({self.odom_x:.2f}, {self.odom_y:.2f}), '
                f'yaw: {self.odom_yaw:.2f}'
            )

    def uwb_callback(self, msg):
        self.uwb_x = msg.pose.position.x
        self.uwb_y = msg.pose.position.y
        if not self.uwb_received:
            self.uwb_received = True
            self.get_logger().info(
                f'UWB online: ({self.uwb_x:.2f}, {self.uwb_y:.2f})'
            )

    def nav_callback(self, msg):
        """Accept a new goal at runtime. Re-anchors from UWB automatically."""
        new_x = msg.pose.position.x
        new_y = msg.pose.position.y
        self.get_logger().info(f'New goal received: ({new_x:.2f}, {new_y:.2f})')

        self.goal_x = new_x
        self.goal_y = new_y
        self.has_goal = True

        # Re-anchor: snapshot current UWB + odom so drift from
        # previous navigation doesn't carry over
        if self.calibrated and self.uwb_x is not None:
            self.anchor_x = self.uwb_x
            self.anchor_y = self.uwb_y
            self.odom_anchor_x = self.odom_x
            self.odom_anchor_y = self.odom_y
            self.get_logger().info(
                f'Re-anchored: UWB=({self.anchor_x:.2f}, {self.anchor_y:.2f}), '
                f'odom=({self.odom_anchor_x:.2f}, {self.odom_anchor_y:.2f})'
            )

    def send_velocity(self, forward_speed, angular_speed):
        cmd = TwistStamped()
        cmd.header.stamp = self.get_clock().now().to_msg()
        cmd.twist.linear.x = forward_speed
        cmd.twist.angular.z = angular_speed
        self.cmd_pub.publish(cmd)

    def stop(self):
        self.send_velocity(0.0, 0.0)

    def normalize_angle(self, angle):
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle

    def get_real_position(self):
        if self.anchor_x is None or self.odom_anchor_x is None:
            return None, None

        dx_odom = self.odom_x - self.odom_anchor_x
        dy_odom = self.odom_y - self.odom_anchor_y

        if self.yaw_offset is not None:
            rotated_x = dx_odom * math.cos(self.yaw_offset) - dy_odom * math.sin(self.yaw_offset)
            rotated_y = dx_odom * math.sin(self.yaw_offset) + dy_odom * math.cos(self.yaw_offset)
            return self.anchor_x + rotated_x, self.anchor_y + rotated_y

        return self.anchor_x + dx_odom, self.anchor_y + dy_odom

    def get_real_heading(self):
        if self.yaw_offset is not None:
            return self.normalize_angle(self.odom_yaw + self.yaw_offset)
        return self.odom_yaw

    def calibration_loop(self):
        if self.calibration_start_uwb_x is None:
            self.calibration_start_uwb_x = self.uwb_x
            self.calibration_start_uwb_y = self.uwb_y
            self.calibration_start_odom_yaw = self.odom_yaw

            # Set initial anchors
            self.anchor_x = self.uwb_x
            self.anchor_y = self.uwb_y
            self.odom_anchor_x = self.odom_x
            self.odom_anchor_y = self.odom_y

        dx = self.uwb_x - self.calibration_start_uwb_x
        dy = self.uwb_y - self.calibration_start_uwb_y
        self.calibration_distance = math.sqrt(dx * dx + dy * dy)

        if self.calibration_distance >= self.calibration_target:
            self.stop()

            uwb_heading = math.atan2(dy, dx)
            self.yaw_offset = self.normalize_angle(
                uwb_heading - self.calibration_start_odom_yaw
            )
            self.calibrated = True
            self.get_logger().info(
                f'Calibrated! yaw_offset={math.degrees(self.yaw_offset):.1f}°'
            )

            # Re-anchor after calibration drive so the 0.5m calibration
            # distance doesn't count as drift
            self.anchor_x = self.uwb_x
            self.anchor_y = self.uwb_y
            self.odom_anchor_x = self.odom_x
            self.odom_anchor_y = self.odom_y
        else:
            self.send_velocity(0.10, 0.0)

    def navigation_loop(self):
        if not self.has_goal:
            return

        real_x, real_y = self.get_real_position()
        if real_x is None or real_y is None:
            return

        dx = self.goal_x - real_x
        dy = self.goal_y - real_y
        distance = math.sqrt(dx * dx + dy * dy)

        self.get_logger().info(
            f'Pos: ({real_x:.2f}, {real_y:.2f}) -> '
            f'Goal: ({self.goal_x:.2f}, {self.goal_y:.2f}), '
            f'dist: {distance:.2f}m',
            throttle_duration_sec=1.0
        )

        if distance < self.goal_tolerance:
            self.stop()
            self.get_logger().info(
                f'Reached goal ({self.goal_x:.2f}, {self.goal_y:.2f})!'
            )
            self.has_goal = False
            return

        target_heading = math.atan2(dy, dx)
        current_heading = self.get_real_heading()
        heading_error = self.normalize_angle(target_heading - current_heading)

        if abs(heading_error) > self.turn_threshold:
            turn_speed = self.max_turn_speed if heading_error > 0 else -self.max_turn_speed
            self.send_velocity(0.0, turn_speed)
        else:
            forward_speed = min(self.max_speed, distance * 0.5)
            turn_speed = heading_error * 2.0
            turn_speed = max(-self.max_turn_speed, min(self.max_turn_speed, turn_speed))
            self.send_velocity(forward_speed, turn_speed)

    def main_loop(self):
        if not self.odom_received or not self.uwb_received:
            return

        if not self.calibrated:
            self.calibration_loop()
        else:
            self.navigation_loop()


def main():
    rclpy.init()

    goal_x = float(sys.argv[1]) if len(sys.argv) >= 3 else None
    goal_y = float(sys.argv[2]) if len(sys.argv) >= 3 else None

    node = Navigation(goal_x, goal_y)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        node.stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
