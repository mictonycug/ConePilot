#!/usr/bin/env python3
"""
ConePilot Bridge - Lightweight HTTP server that bridges ConePilot to ROS2.
Run on the TurtleBot alongside robot.launch.py.
Uses only basic ROS2 packages (no Nav2 required).

Usage:
    source /opt/ros/jazzy/setup.bash
    python3 cone_bridge.py
"""

import json
import math
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TwistStamped
from nav_msgs.msg import Odometry

PORT = 8888

# Tuning parameters
LINEAR_SPEED = 0.15       # m/s max forward speed
ANGULAR_SPEED = 0.8       # rad/s max turning speed
GOAL_TOLERANCE = 0.08     # meters - how close is "arrived"
ANGLE_TOLERANCE = 0.1     # radians - how aligned before driving forward


class ConeBridgeNode(Node):
    def __init__(self):
        super().__init__('cone_bridge')
        self.cmd_vel_pub = self.create_publisher(TwistStamped, '/cmd_vel', 10)

        self.current_pose = {'x': 0.0, 'y': 0.0, 'theta': 0.0}
        self.navigating = False
        self.cancel_nav = False
        self.waypoint_index = -1
        self.waypoint_total = 0

        self.odom_sub = self.create_subscription(
            Odometry, '/odom', self.odom_callback, 10
        )
        self.get_logger().info(f'ConeBridge running on port {PORT}')

    def odom_callback(self, msg):
        pos = msg.pose.pose.position
        ori = msg.pose.pose.orientation
        siny = 2.0 * (ori.w * ori.z + ori.x * ori.y)
        cosy = 1.0 - 2.0 * (ori.y * ori.y + ori.z * ori.z)
        theta = math.atan2(siny, cosy)
        self.current_pose = {'x': pos.x, 'y': pos.y, 'theta': theta}

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

    def normalize_angle(self, angle):
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle

    def navigate_to(self, goal_x, goal_y):
        """Simple proportional go-to-point controller using odometry."""
        self.navigating = True
        self.cancel_nav = False
        rate = 0.05  # 20Hz control loop

        while not self.cancel_nav:
            dx = goal_x - self.current_pose['x']
            dy = goal_y - self.current_pose['y']
            dist = math.sqrt(dx * dx + dy * dy)

            if dist < GOAL_TOLERANCE:
                self.send_velocity(0.0, 0.0)
                self.get_logger().info(
                    f'Reached ({goal_x:.2f}, {goal_y:.2f}), error: {dist:.3f}m'
                )
                self.navigating = False
                return True

            # Angle to goal
            target_angle = math.atan2(dy, dx)
            angle_error = self.normalize_angle(
                target_angle - self.current_pose['theta']
            )

            # Turn first, then drive
            if abs(angle_error) > ANGLE_TOLERANCE:
                angular = max(-ANGULAR_SPEED,
                              min(ANGULAR_SPEED, angle_error * 2.0))
                self.send_velocity(0.0, angular)
            else:
                linear = min(LINEAR_SPEED, dist * 0.5)
                angular = angle_error * 1.5
                self.send_velocity(linear, angular)

            time.sleep(rate)

        self.send_velocity(0.0, 0.0)
        self.navigating = False
        return False


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
            self._json_response(bridge_node.current_pose)
        elif self.path == '/status':
            self._json_response({
                'connected': True,
                'navigating': bridge_node.navigating,
                'pose': bridge_node.current_pose,
                'waypoint_index': bridge_node.waypoint_index,
                'waypoint_total': bridge_node.waypoint_total,
            })
        else:
            self._json_response({'error': 'not found'}, 404)

    def do_POST(self):
        body = self._read_body()

        if self.path == '/cmd_vel':
            bridge_node.send_velocity(
                body.get('linear', 0.0),
                body.get('angular', 0.0),
            )
            self._json_response({'ok': True})

        elif self.path == '/stop':
            bridge_node.stop()
            self._json_response({'ok': True})

        elif self.path == '/navigate':
            x = body.get('x', 0.0)
            y = body.get('y', 0.0)

            def nav():
                bridge_node.navigate_to(x, y)

            threading.Thread(target=nav, daemon=True).start()
            self._json_response({'ok': True, 'msg': 'navigation started'})

        elif self.path == '/waypoints':
            waypoints = body.get('waypoints', [])

            def run_waypoints():
                bridge_node.waypoint_total = len(waypoints)
                for i, wp in enumerate(waypoints):
                    bridge_node.waypoint_index = i
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
                bridge_node.waypoint_index = -1
                bridge_node.waypoint_total = 0
                bridge_node.get_logger().info('Waypoint sequence complete')

            threading.Thread(target=run_waypoints, daemon=True).start()
            self._json_response({
                'ok': True,
                'msg': f'executing {len(waypoints)} waypoints',
            })

        else:
            self._json_response({'error': 'not found'}, 404)

    def log_message(self, format, *args):
        # Log all requests so we can debug what's coming in
        print(f"[HTTP] {format % args}")


def main():
    global bridge_node
    rclpy.init()
    bridge_node = ConeBridgeNode()

    spin_thread = threading.Thread(
        target=lambda: rclpy.spin(bridge_node), daemon=True
    )
    spin_thread.start()

    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'ConeBridge HTTP server listening on port {PORT}')
    print(f'Endpoints:')
    print(f'  GET  /status    - connection status + pose')
    print(f'  GET  /odom      - current robot pose')
    print(f'  POST /cmd_vel   - send velocity')
    print(f'  POST /stop      - stop the robot')
    print(f'  POST /navigate  - go to point')
    print(f'  POST /waypoints - execute waypoint sequence')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bridge_node.stop()
        bridge_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
