#!/usr/bin/env bash
# Quick test: start bringup and wiggle the robot to confirm motors work.
# Run on the TurtleBot: ./test_motor.sh

source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=58
export TURTLEBOT3_MODEL=burger
unset CYCLONEDDS_URI 2>/dev/null
unset RMW_IMPLEMENTATION 2>/dev/null

# Kill anything lingering
pkill -f "robot.launch.py" 2>/dev/null
pkill -f "cone_bridge.py" 2>/dev/null
ros2 daemon stop 2>/dev/null
sleep 1
ros2 daemon start 2>/dev/null

echo "=== Starting robot bringup ==="
ros2 launch turtlebot3_bringup robot.launch.py &
BRINGUP_PID=$!
sleep 10

echo ""
echo "=== Checking topics ==="
ros2 topic list
echo ""

echo "=== Reading odom (3 seconds) ==="
timeout 3 ros2 topic echo /odom --once 2>/dev/null || echo "(no odom received)"
echo ""

echo "=== Spinning left for 2 seconds ==="
ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: ''}, twist: {linear: {x: 0.0}, angular: {z: 0.5}}}"
sleep 2

echo "=== Stop ==="
ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: ''}, twist: {linear: {x: 0.0}, angular: {z: 0.0}}}"
sleep 1

echo "=== Driving forward for 2 seconds ==="
ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: ''}, twist: {linear: {x: 0.1}, angular: {z: 0.0}}}"
sleep 2

echo "=== Stop ==="
ros2 topic pub --once /cmd_vel geometry_msgs/msg/TwistStamped \
  "{header: {frame_id: ''}, twist: {linear: {x: 0.0}, angular: {z: 0.0}}}"

echo ""
echo "=== Done. Killing bringup ==="
kill $BRINGUP_PID 2>/dev/null
wait $BRINGUP_PID 2>/dev/null
echo "Finished."
