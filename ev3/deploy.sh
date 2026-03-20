#!/bin/bash
# Deploy EV3 scripts to the robot
# Usage: ./ev3/deploy.sh [host] [user] [password]

HOST="${1:-172.20.10.2}"
USER="${2:-robot}"
PASS="${3:-maker}"
DEST="/home/robot/conepilot"

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Deploying EV3 scripts to ${USER}@${HOST}:${DEST}"

# Create destination directory
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=accept-new "${USER}@${HOST}" "mkdir -p ${DEST}" || {
    echo "Failed to connect. Is the EV3 on the network?"
    exit 1
}

# Copy all Python scripts
for f in "$DIR"/*.py; do
    echo "  Copying $(basename "$f")..."
    sshpass -p "$PASS" scp -o StrictHostKeyChecking=accept-new "$f" "${USER}@${HOST}:${DEST}/"
done

echo ""
echo "Done! Scripts are at ${DEST}/ on the EV3."
echo ""
echo "To use:"
echo "  ssh ${USER}@${HOST}"
echo "  cd ${DEST}"
echo ""
echo "  # 1. Test which motors are connected:"
echo "  python3 test_motors.py"
echo ""
echo "  # 2. Calibrate the spiral (cone drop/pickup):"
echo "  python3 calibrate_spiral.py --port outB"
echo ""
echo "  # 3. Calibrate the column (lift up/down):"
echo "  python3 calibrate_column.py --port outA"
echo ""
echo "  # 4. Test a full place sequence:"
echo "  python3 test_place.py"
echo ""
echo "  # 5. Test a full pickup sequence:"
echo "  python3 test_pickup.py"
echo ""
echo "  # 6. Start the HTTP server (for ConePilot integration):"
echo "  python3 cone_mechanism.py --port 8080"
