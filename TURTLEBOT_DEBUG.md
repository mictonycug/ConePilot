# TurtleBot3 Debug Guide

## Problem: `ros2 topic list` only shows `/parameter_events` and `/rosout`

Even when `robot.launch.py` is running, `ros2 topic list` doesn't show `/odom`, `/cmd_vel`, etc.

### Root Cause

The `CYCLONEDDS_URI` in `~/.bashrc` is configured for the university (DiCE) network with:
- `AllowMulticast=false`
- Peer addresses pointing to university hostnames (`bronzor.inf.ed.ac.uk`, `ito.inf.ed.ac.uk`)

When running off-campus (e.g., on a personal hotspot), this breaks discovery because:
1. Multicast is disabled
2. University hostnames can't resolve (DNS fails)
3. CycloneDDS only binds to `wlan0`, not loopback — so even the `localhost` peer can't reach the robot node

### Fix (run in BOTH terminals on the robot)

```bash
unset CYCLONEDDS_URI
unset RMW_IMPLEMENTATION
ros2 daemon stop
```

Then restart the robot launch:

```bash
# Terminal 1 (Ctrl+C first if robot.launch.py is running)
unset CYCLONEDDS_URI
unset RMW_IMPLEMENTATION
ros2 launch turtlebot3_bringup robot.launch.py

# Terminal 2 (wait ~5 seconds)
ros2 topic list
# Should now show /odom, /cmd_vel, /scan, etc.
```

Then start the bridge:

```bash
# Terminal 2
python3 cone_bridge.py
```

### Quick Reference: Full Startup Sequence

```bash
# 1. SSH into robot
ssh ubuntu@<robot-ip>

# 2. Source ROS and unset university DDS config
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=58
export TURTLEBOT3_MODEL=burger
unset CYCLONEDDS_URI
unset RMW_IMPLEMENTATION

# 3. Launch robot drivers (terminal 1)
ros2 launch turtlebot3_bringup robot.launch.py

# 4. In a second SSH terminal, same exports as step 2, then:
ros2 topic list          # verify /odom and /cmd_vel appear
python3 cone_bridge.py   # start the HTTP bridge on port 8888
```

### Other Common Issues

#### `ntpdig: no eligible servers`
Harmless — the `.bashrc` tries to sync time with `ntp2.inf.ed.ac.uk` which isn't reachable off-campus. Ignore it, or comment out the `sudo ntpdate` line in `~/.bashrc`.

#### `publisher's context is invalid` (cone_bridge.py crash)
The ROS2 context was invalidated (usually after a daemon reset or crash). Just restart `cone_bridge.py`.

#### Daemon goes stale / topics disappear mid-session
```bash
ros2 daemon stop
ros2 daemon start
```
Then restart `cone_bridge.py`. May also need to restart `robot.launch.py`.

#### Vite proxy errors: `ECONNREFUSED 172.20.10.3:8888`
The bridge isn't running on the robot, or the robot IP changed. Verify with:
```bash
curl http://<robot-ip>:8888/status
```
Update the IP in `client/vite.config.ts` if it changed.
