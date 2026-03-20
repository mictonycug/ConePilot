#!/usr/bin/env bash
# ============================================================================
# ConePilot - TurtleBot Unified Startup Script
# ============================================================================
# Starts all required services on the TurtleBot in the correct order:
#   1. ROS2 TurtleBot3 bringup (robot.launch.py)
#   2. UWB positioning node (uwb_node.py)
#   3. ConePilot HTTP bridge (cone_bridge.py)
#
# Usage:
#   ./start_robot.sh              # Start all services
#   ./start_robot.sh --no-uwb     # Skip UWB node (no UWB hardware)
#   ./start_robot.sh --restart    # Kill everything, reset ROS2, start fresh
#   ./start_robot.sh --stop       # Stop all services
#   ./start_robot.sh --status     # Check what's running
#   ./start_robot.sh --diagnose   # Full diagnostic check of all subsystems
# ============================================================================

set -eo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

ROS_DISTRO="jazzy"
ROS_DOMAIN=58
TURTLEBOT_MODEL="burger"
BRIDGE_PORT=8888

# How long to wait for robot.launch.py before starting bridge
BRINGUP_WAIT=8

# Watchdog: seconds between health checks while monitoring
WATCHDOG_INTERVAL=10

# ── Color helpers ────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[  OK]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()   { echo -e "${RED}[ ERR]${NC}  $*"; }
log_step()  { echo -e "\n${CYAN}${BOLD}── $* ──${NC}"; }

# ── ROS2 Environment Setup ──────────────────────────────────────────────────

setup_ros_env() {
    if [ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
        source "/opt/ros/$ROS_DISTRO/setup.bash"
    else
        log_err "ROS2 $ROS_DISTRO not found at /opt/ros/$ROS_DISTRO/setup.bash"
        exit 1
    fi

    # Source TurtleBot3 workspace overlays (built packages like turtlebot3_bringup)
    # Use /home/ubuntu explicitly so this works under sudo too
    local real_home="/home/${SUDO_USER:-$USER}"
    for ws in "$real_home/turtlebot3_ws/install/setup.bash" "$real_home/tb3_ws/install/setup.bash"; do
        if [ -f "$ws" ]; then
            source "$ws"
            log_ok "Sourced workspace: $ws"
        fi
    done

    export ROS_DOMAIN_ID="$ROS_DOMAIN"
    export TURTLEBOT3_MODEL="$TURTLEBOT_MODEL"
    export LDS_MODEL="${LDS_MODEL:-LDS-01}"

    # CRITICAL: Unset university DDS config that breaks off-campus networking.
    # The robot's .bashrc sets CYCLONEDDS_URI for the university network with
    # AllowMulticast=false and hardcoded university hostnames. This prevents
    # ROS2 discovery when running on a personal hotspot.
    unset CYCLONEDDS_URI 2>/dev/null || true
    unset RMW_IMPLEMENTATION 2>/dev/null || true

    log_ok "ROS2 $ROS_DISTRO env loaded (DOMAIN_ID=$ROS_DOMAIN, MODEL=$TURTLEBOT_MODEL)"
    log_ok "CYCLONEDDS_URI and RMW_IMPLEMENTATION unset"
}

# ── Full ROS2 Reset ─────────────────────────────────────────────────────────
# Kills daemon, clears stale shared memory, and restarts cleanly.
# Fixes: topics disappear mid-session, "publisher's context is invalid", etc.

reset_ros2() {
    log_step "Resetting ROS2 environment"

    # Stop daemon
    ros2 daemon stop 2>/dev/null || true
    log_ok "ROS2 daemon stopped"

    # Kill any zombie ROS2 processes (nodes that didn't clean up)
    pkill -9 -f "ros2" 2>/dev/null || true
    sleep 0.5

    # Clear stale shared memory segments left by crashed nodes
    local shm_cleaned=0
    shm_cleaned=$(find /dev/shm -maxdepth 1 \( -name 'fastrtps_*' -o -name 'ros2_*' \) -delete -print 2>/dev/null | wc -l || echo 0)
    if [ "$shm_cleaned" -gt 0 ]; then
        log_ok "Cleaned $shm_cleaned stale shared memory segments"
    fi

    # Restart daemon
    ros2 daemon start 2>/dev/null || true
    log_ok "ROS2 daemon restarted"
}

# ── Process Management ───────────────────────────────────────────────────────

BRINGUP_PID=""
UWB_PID=""
BRIDGE_PID=""
ULTRASONIC_PID=""

is_running() {
    pgrep -f "$1" > /dev/null 2>&1
}

get_pid() {
    pgrep -f "$1" 2>/dev/null | head -1
}

kill_service() {
    local name="$1"
    local display_name="$2"
    if is_running "$name"; then
        local pids
        pids=$(pgrep -f "$name" 2>/dev/null || true)
        log_warn "Stopping $display_name (PIDs: $pids)..."
        # Graceful first
        kill $pids 2>/dev/null || true
        for _ in $(seq 1 10); do
            if ! is_running "$name"; then
                log_ok "$display_name stopped"
                return 0
            fi
            sleep 0.5
        done
        # Force kill
        log_warn "Force-killing $display_name..."
        kill -9 $pids 2>/dev/null || true
        sleep 0.5
        log_ok "$display_name killed"
    fi
}

stop_all() {
    log_step "Stopping all ConePilot services"

    # Stop in reverse order (bridge first, bringup last)
    kill_service "cone_bridge.py" "ConePilot Bridge"
    kill_service "ultrasonic_radar.py" "Ultrasonic Radar"
    kill_service "uwb_node.py" "UWB Node"
    kill_service "robot.launch.py" "TurtleBot3 Bringup"

    # Also kill any lingering turtlebot3 nodes
    kill_service "turtlebot3" "TurtleBot3 nodes"

    # Reset ROS2 daemon
    if command -v ros2 &>/dev/null; then
        setup_ros_env
        ros2 daemon stop 2>/dev/null || true
        log_ok "ROS2 daemon stopped"
    fi

    # Clear stale shared memory
    find /dev/shm -maxdepth 1 \( -name 'fastrtps_*' -o -name 'ros2_*' \) -delete 2>/dev/null || true

    # Clear old logs
    rm -f "$LOG_DIR"/*.log 2>/dev/null || true

    log_ok "All services stopped and cleaned up"
}

show_status() {
    log_step "ConePilot Service Status"

    local all_ok=true

    if is_running "robot.launch.py"; then
        log_ok "TurtleBot3 Bringup    running (PID $(get_pid 'robot.launch.py'))"
    else
        log_err "TurtleBot3 Bringup    NOT RUNNING"
        all_ok=false
    fi

    if is_running "uwb_node.py"; then
        log_ok "UWB Node              running (PID $(get_pid 'uwb_node.py'))"
    else
        log_warn "UWB Node              not running (optional)"
    fi

    if is_running "cone_bridge.py"; then
        log_ok "ConePilot Bridge      running (PID $(get_pid 'cone_bridge.py'))"
    else
        log_err "ConePilot Bridge      NOT RUNNING"
        all_ok=false
    fi

    if is_running "ultrasonic_radar.py"; then
        log_ok "Ultrasonic Radar      running (PID $(get_pid 'ultrasonic_radar.py'))"
    else
        log_warn "Ultrasonic Radar      not running (optional)"
    fi

    echo ""

    # Bridge HTTP health check
    if is_running "cone_bridge.py"; then
        local status_json
        status_json=$(curl -sf "http://localhost:$BRIDGE_PORT/status" 2>/dev/null || echo "")
        if [ -n "$status_json" ]; then
            log_ok "Bridge HTTP responding on port $BRIDGE_PORT"
        else
            log_warn "Bridge process up but HTTP not responding"
        fi
    fi

    # ROS2 topics check
    if command -v ros2 &>/dev/null; then
        local topics
        topics=$(ros2 topic list 2>/dev/null || echo "")
        if echo "$topics" | grep -q "/odom"; then
            log_ok "ROS2 /odom topic available"
        else
            log_warn "ROS2 /odom topic not visible"
        fi
        if echo "$topics" | grep -q "/cmd_vel"; then
            log_ok "ROS2 /cmd_vel topic available"
        else
            log_warn "ROS2 /cmd_vel topic not visible"
        fi
    fi

    if $all_ok; then
        echo -e "\n${GREEN}${BOLD}All core services running.${NC}"
    fi
}

# ── Diagnostics ──────────────────────────────────────────────────────────────

run_diagnostics() {
    log_step "ConePilot Full Diagnostics"

    local issues=0

    # 1. ROS2 installation
    echo ""
    log_info "Checking ROS2 installation..."
    if [ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
        log_ok "ROS2 $ROS_DISTRO found"
    else
        log_err "ROS2 $ROS_DISTRO NOT FOUND"
        issues=$((issues + 1))
    fi

    # 2. DDS environment
    log_info "Checking DDS environment..."
    if [ -n "${CYCLONEDDS_URI:-}" ]; then
        log_err "CYCLONEDDS_URI is set: $CYCLONEDDS_URI"
        log_err "  -> This will break off-campus. Run: unset CYCLONEDDS_URI"
        issues=$((issues + 1))
    else
        log_ok "CYCLONEDDS_URI not set (good)"
    fi

    # 3. Python scripts present
    log_info "Checking ConePilot scripts..."
    for script in cone_bridge.py cone_detector.py uwb_node.py; do
        if [ -f "$SCRIPT_DIR/$script" ]; then
            log_ok "$script present"
        else
            log_err "$script MISSING from $SCRIPT_DIR"
            issues=$((issues + 1))
        fi
    done

    # 4. Python dependencies
    log_info "Checking Python dependencies..."
    for pkg in cv2 rclpy numpy; do
        if python3 -c "import $pkg" 2>/dev/null; then
            log_ok "Python: $pkg available"
        else
            log_err "Python: $pkg NOT FOUND"
            issues=$((issues + 1))
        fi
    done

    # 5. Camera
    log_info "Checking camera..."
    if [ -e /dev/video0 ]; then
        log_ok "Camera detected at /dev/video0"
    else
        log_warn "No camera at /dev/video0 (cone detection won't work)"
    fi

    # 6. UWB hardware
    log_info "Checking UWB hardware..."
    local uwb_device="/dev/serial/by-id/usb-SEGGER_J-Link_000760180803-if00"
    if [ -e "$uwb_device" ]; then
        log_ok "UWB device found"
    else
        log_warn "UWB device not found (will use odometry only)"
    fi

    # 7. Calibration files
    log_info "Checking calibration files..."
    if [ -f "$SCRIPT_DIR/cone_calibration.json" ]; then
        log_ok "cone_calibration.json present"
    else
        log_warn "cone_calibration.json missing (will use defaults)"
    fi
    if [ -f "$SCRIPT_DIR/uwb_calibration.json" ]; then
        log_ok "uwb_calibration.json present"
    else
        log_warn "uwb_calibration.json missing (UWB will use uncalibrated values)"
    fi

    # 8. Network
    log_info "Checking network..."
    local robot_ip
    robot_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
    if [ -n "$robot_ip" ]; then
        log_ok "Robot IP: $robot_ip"
    else
        log_err "No network IP detected"
        issues=$((issues + 1))
    fi

    # 9. Port availability
    log_info "Checking port $BRIDGE_PORT..."
    if ss -tlnp 2>/dev/null | grep -q ":$BRIDGE_PORT"; then
        log_warn "Port $BRIDGE_PORT already in use"
        ss -tlnp 2>/dev/null | grep ":$BRIDGE_PORT" || true
    else
        log_ok "Port $BRIDGE_PORT available"
    fi

    # 10. ROS2 daemon + topics (if bringup is running)
    if command -v ros2 &>/dev/null; then
        log_info "Checking ROS2 daemon..."
        setup_ros_env
        local topics
        topics=$(ros2 topic list 2>/dev/null || echo "(daemon not responding)")
        if echo "$topics" | grep -q "/odom"; then
            log_ok "ROS2 topics healthy: /odom visible"
            echo -e "  ${DIM}$(echo "$topics" | tr '\n' ' ')${NC}"
        elif echo "$topics" | grep -q "daemon"; then
            log_warn "ROS2 daemon not responding - try: ros2 daemon stop && ros2 daemon start"
        else
            log_warn "ROS2 bringup not running (topics: $topics)"
        fi
    fi

    # Summary
    echo ""
    if [ "$issues" -eq 0 ]; then
        echo -e "${GREEN}${BOLD}Diagnostics passed - no issues found.${NC}"
    else
        echo -e "${RED}${BOLD}Found $issues issue(s) that need attention.${NC}"
    fi
}

# ── Service Launchers ────────────────────────────────────────────────────────

start_bringup() {
    log_step "Starting TurtleBot3 Bringup"

    if is_running "robot.launch.py"; then
        log_warn "TurtleBot3 Bringup already running (PID $(get_pid 'robot.launch.py'))"
        return 0
    fi

    mkdir -p "$LOG_DIR"

    ros2 launch turtlebot3_bringup robot.launch.py usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00 \
        >> "$LOG_DIR/bringup.log" 2>&1 &
    BRINGUP_PID=$!

    log_info "TurtleBot3 Bringup started (PID $BRINGUP_PID)"
    log_info "Waiting ${BRINGUP_WAIT}s for bringup to initialize..."

    for _ in $(seq 1 "$BRINGUP_WAIT"); do
        if ! kill -0 "$BRINGUP_PID" 2>/dev/null; then
            log_err "Bringup crashed during startup! Last 20 lines of log:"
            tail -20 "$LOG_DIR/bringup.log" 2>/dev/null || true
            exit 1
        fi
        sleep 1
        printf "."
    done
    echo ""

    # Verify topics
    local topics
    topics=$(ros2 topic list 2>/dev/null || echo "")
    if echo "$topics" | grep -q "/odom"; then
        log_ok "Bringup healthy - /odom topic detected"
    else
        log_warn "Bringup running but /odom not yet visible (may need more time)"
    fi
}

start_uwb() {
    log_step "Starting UWB Node"

    if is_running "uwb_node.py"; then
        log_warn "UWB Node already running (PID $(get_pid 'uwb_node.py'))"
        return 0
    fi

    local uwb_device="/dev/serial/by-id/usb-SEGGER_J-Link_000760180803-if00"
    if [ ! -e "$uwb_device" ]; then
        log_warn "UWB device not found at $uwb_device - skipping"
        return 0
    fi

    mkdir -p "$LOG_DIR"

    python3 "$SCRIPT_DIR/uwb_node.py" \
        >> "$LOG_DIR/uwb_node.log" 2>&1 &
    UWB_PID=$!

    sleep 2

    if kill -0 "$UWB_PID" 2>/dev/null; then
        log_ok "UWB Node started (PID $UWB_PID)"
    else
        log_warn "UWB Node failed to start:"
        tail -10 "$LOG_DIR/uwb_node.log" 2>/dev/null || true
    fi
}

start_bridge() {
    log_step "Starting ConePilot Bridge"

    if is_running "cone_bridge.py"; then
        log_warn "ConePilot Bridge already running (PID $(get_pid 'cone_bridge.py'))"
        return 0
    fi

    mkdir -p "$LOG_DIR"

    python3 "$SCRIPT_DIR/cone_bridge.py" \
        >> "$LOG_DIR/cone_bridge.log" 2>&1 &
    BRIDGE_PID=$!

    sleep 3

    if kill -0 "$BRIDGE_PID" 2>/dev/null; then
        log_ok "ConePilot Bridge started (PID $BRIDGE_PID)"
    else
        log_err "Bridge failed to start! Last 20 lines of log:"
        tail -20 "$LOG_DIR/cone_bridge.log" 2>/dev/null || true
        exit 1
    fi

    if curl -sf "http://localhost:$BRIDGE_PORT/status" > /dev/null 2>&1; then
        log_ok "Bridge HTTP responding on port $BRIDGE_PORT"
    else
        log_warn "Bridge process running but HTTP not responding yet"
    fi
}

start_ultrasonic() {
    log_step "Starting Ultrasonic Radar"

    if is_running "ultrasonic_radar.py"; then
        log_warn "Ultrasonic Radar already running (PID $(get_pid 'ultrasonic_radar.py'))"
        return 0
    fi

    mkdir -p "$LOG_DIR"

    sudo python3 "$SCRIPT_DIR/ultrasonic_radar.py" --headless \
        --status-file /tmp/ultrasonic_status.json \
        >> "$LOG_DIR/ultrasonic.log" 2>&1 &
    ULTRASONIC_PID=$!

    sleep 2

    if is_running "ultrasonic_radar.py"; then
        log_ok "Ultrasonic Radar started (PID $(get_pid 'ultrasonic_radar.py'))"
    else
        log_warn "Ultrasonic Radar failed to start (non-fatal):"
        tail -10 "$LOG_DIR/ultrasonic.log" 2>/dev/null || true
    fi
}

# ── Watchdog ─────────────────────────────────────────────────────────────────
# Runs in the background, checks services every WATCHDOG_INTERVAL seconds,
# and auto-restarts any that have crashed.

SKIP_UWB_GLOBAL=false

watchdog_loop() {
    while true; do
        sleep "$WATCHDOG_INTERVAL"

        # Check bringup
        if ! is_running "robot.launch.py"; then
            log_err "WATCHDOG: TurtleBot3 Bringup crashed - restarting..."
            echo "--- WATCHDOG RESTART $(date) ---" >> "$LOG_DIR/bringup.log"
            ros2 launch turtlebot3_bringup robot.launch.py usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00 \
                >> "$LOG_DIR/bringup.log" 2>&1 &
            BRINGUP_PID=$!
            log_ok "WATCHDOG: Bringup restarted (PID $BRINGUP_PID)"
            sleep "$BRINGUP_WAIT"
        fi

        # Check UWB (only if it was started)
        if ! $SKIP_UWB_GLOBAL && [ -n "$UWB_PID" ] && ! is_running "uwb_node.py"; then
            log_err "WATCHDOG: UWB Node crashed - restarting..."
            echo "--- WATCHDOG RESTART $(date) ---" >> "$LOG_DIR/uwb_node.log"
            python3 "$SCRIPT_DIR/uwb_node.py" \
                >> "$LOG_DIR/uwb_node.log" 2>&1 &
            UWB_PID=$!
            log_ok "WATCHDOG: UWB Node restarted (PID $UWB_PID)"
        fi

        # Check bridge
        if ! is_running "cone_bridge.py"; then
            log_err "WATCHDOG: ConePilot Bridge crashed - restarting..."
            echo "--- WATCHDOG RESTART $(date) ---" >> "$LOG_DIR/cone_bridge.log"
            python3 "$SCRIPT_DIR/cone_bridge.py" \
                >> "$LOG_DIR/cone_bridge.log" 2>&1 &
            BRIDGE_PID=$!
            log_ok "WATCHDOG: Bridge restarted (PID $BRIDGE_PID)"
        fi

        # Check ultrasonic (non-fatal)
        if [ -n "$ULTRASONIC_PID" ] && ! is_running "ultrasonic_radar.py"; then
            log_warn "WATCHDOG: Ultrasonic Radar crashed - restarting..."
            echo "--- WATCHDOG RESTART $(date) ---" >> "$LOG_DIR/ultrasonic.log"
            sudo python3 "$SCRIPT_DIR/ultrasonic_radar.py" --headless \
                --status-file /tmp/ultrasonic_status.json \
                >> "$LOG_DIR/ultrasonic.log" 2>&1 &
            ULTRASONIC_PID=$!
            log_ok "WATCHDOG: Ultrasonic restarted (PID $ULTRASONIC_PID)"
        fi
    done
}

# ── Cleanup on exit ──────────────────────────────────────────────────────────

cleanup() {
    echo ""
    log_step "Shutting down (Ctrl+C received)"
    # Kill watchdog first
    kill "$WATCHDOG_PID" 2>/dev/null || true
    stop_all
    exit 0
}

WATCHDOG_PID=""

# ── Monitor with watchdog ────────────────────────────────────────────────────

monitor_with_watchdog() {
    log_step "Monitoring (Ctrl+C to stop all services)"
    log_info "Watchdog active: auto-restarts crashed services every ${WATCHDOG_INTERVAL}s"
    echo -e "${DIM}Logs: $LOG_DIR/${NC}\n"

    # Start watchdog in background
    watchdog_loop &
    WATCHDOG_PID=$!

    # Tail all log files
    tail -f "$LOG_DIR"/*.log 2>/dev/null || {
        log_warn "No log files to tail yet"
        while true; do sleep 60; done
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    local skip_uwb=false
    local do_restart=false
    local do_stop=false
    local do_status=false
    local do_diagnose=false

    for arg in "$@"; do
        case "$arg" in
            --no-uwb)    skip_uwb=true ;;
            --restart)   do_restart=true ;;
            --stop)      do_stop=true ;;
            --status)    do_status=true ;;
            --diagnose)  do_diagnose=true ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "  (no args)    Start all services with watchdog"
                echo "  --no-uwb     Skip UWB positioning node"
                echo "  --restart    Kill everything, full ROS2 reset, start fresh"
                echo "  --stop       Stop all services and clean up"
                echo "  --status     Check what's running"
                echo "  --diagnose   Full diagnostic of hardware, software, and network"
                exit 0
                ;;
            *)
                log_err "Unknown argument: $arg"
                exit 1
                ;;
        esac
    done

    echo -e "${BOLD}${CYAN}"
    echo "  ╔═══════════════════════════════════════╗"
    echo "  ║        ConePilot Robot Startup         ║"
    echo "  ╚═══════════════════════════════════════╝"
    echo -e "${NC}"

    # --diagnose
    if $do_diagnose; then
        setup_ros_env
        run_diagnostics
        exit 0
    fi

    # --status
    if $do_status; then
        setup_ros_env
        show_status
        exit 0
    fi

    # --stop
    if $do_stop; then
        stop_all
        exit 0
    fi

    # --restart: full nuclear reset
    if $do_restart; then
        stop_all
        sleep 2
    fi

    # Guard against double-start
    if ! $do_restart; then
        if is_running "robot.launch.py" || is_running "cone_bridge.py"; then
            log_warn "Services already running. Use --restart to stop and restart."
            setup_ros_env
            show_status
            exit 1
        fi
    fi

    # Trap Ctrl+C
    trap cleanup SIGINT SIGTERM

    # Set up ROS2
    setup_ros_env

    # Full ROS2 reset (daemon + shared memory)
    reset_ros2

    # Track whether we should watchdog UWB
    SKIP_UWB_GLOBAL=$skip_uwb

    # Launch services in order
    start_bringup

    if ! $skip_uwb; then
        start_uwb
    else
        log_info "Skipping UWB node (--no-uwb)"
    fi

    start_bridge

    start_ultrasonic

    # Final status
    echo ""
    show_status

    # Print connection info
    local robot_ip
    robot_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "???")

    echo ""
    log_step "Ready!"
    echo -e "  Connect from web app: ${BOLD}http://${robot_ip}:${BRIDGE_PORT}${NC}"
    echo -e "  Quick test:           ${BOLD}curl http://${robot_ip}:${BRIDGE_PORT}/status${NC}"
    echo -e "  Restart:              ${BOLD}./start_robot.sh --restart${NC}"
    echo -e "  Diagnose issues:      ${BOLD}./start_robot.sh --diagnose${NC}"
    echo ""

    # Stay in foreground with watchdog
    monitor_with_watchdog
}

main "$@"
