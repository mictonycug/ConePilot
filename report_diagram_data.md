# ConePilot Report Diagram Data
> All values extracted from the codebase. Use this to build the three report assets.

---

## 1. SYSTEM INTEGRATION FLOWCHART

### Components

| Component | Technology | Location | Port |
|-----------|-----------|----------|------|
| **Web App (Client)** | React 19 + TypeScript + Vite | `client/` | 5173 (dev) |
| **Backend Server** | Node.js + Express + Socket.IO | `server/` | 3001 |
| **Robot Bridge** | Python 3 + ROS2 (cone_bridge.py) | TurtleBot3 | 8888 |
| **EV3 Mechanism** | Python 3 + ev3dev (cone_mechanism.py) | EV3 Brick | 8080 |
| **UWB Positioning** | Python 3 + ROS2 (uwb_node.py) | TurtleBot3 | ROS2 topic |
| **Ultrasonic Sensors** | Python 3 + ROS2 (ultrasonic_radar.py) | TurtleBot3 | ROS2 topic |

### Communication Protocols & Arrows

```
User Browser
    │
    │  HTTP (Vite proxy)
    ▼
┌──────────────┐
│  Web App     │  (React + Zustand store)
│  (Client)    │──── TSP Algorithm runs HERE (client/src/services/tsp.ts)
│              │     Nearest-Neighbor heuristic, computes cone visit order
└──────┬───────┘
       │
       │  Two connections:
       │
       ├──── Socket.IO ──▶ Backend Server (Node.js, port 3001)
       │                      • Robot auto-discovery (GET /api/discover-robot)
       │                      • Robot locking (prevents concurrent control)
       │                      • Auth + session management
       │
       └──── HTTP REST ──▶ Robot Bridge (cone_bridge.py, port 8888)
                              • Status polling at 5 Hz (every 200ms)
                              • Navigation commands
                              • Collection commands
                              • Camera stream (MJPEG)
```

### Detailed Message Flow (App → Robot → EV3)

```
┌─────────────┐        HTTP REST (JSON)         ┌────────────────────┐
│             │ ──────────────────────────────▶  │                    │
│   Web App   │  POST /collect {cones, dwell}    │   cone_bridge.py   │
│  (Browser)  │                                  │   (TurtleBot3)     │
│             │ ◀─────────────────────────────── │                    │
│             │  GET /status (5Hz poll, 200ms)   │   ROS2 node with:  │
│             │  Response: RobotStatus JSON      │   • /odom subscriber│
│             │                                  │   • /cmd_vel publish│
│             │  GET /camera (MJPEG stream)      │   • /uwb/pose sub  │
│             │                                  │   • /scan subscriber│
└─────────────┘                                  └────────┬───────────┘
                                                          │
                                                          │  HTTP REST
                                                          │  (internal robot network)
                                                          │
                                                          ▼
                                                 ┌────────────────────┐
                                                 │ cone_mechanism.py  │
                                                 │ (EV3 Brick)        │
                                                 │ Port 8080          │
                                                 │                    │
                                                 │ POST /pickup       │
                                                 │ POST /place        │
                                                 │ GET  /status       │
                                                 └────────────────────┘
```

### API Endpoints on cone_bridge.py (port 8888)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/status` | Full robot state (pose, sensors, mission progress) |
| GET | `/odom` | Raw odometry pose |
| GET | `/camera` | MJPEG video stream with detection overlay |
| POST | `/navigate` | Single waypoint navigation (auto-calibrates) |
| POST | `/waypoints` | Multi-waypoint sequence with dwell + mechanism |
| POST | `/calibrate` | Manual UWB/odom fusion calibration |
| POST | `/cmd_vel` | Direct velocity control {linear, angular} |
| POST | `/stop` | Emergency stop |
| POST | `/mechanism/place` | Drop cone via EV3 |
| POST | `/mechanism/pickup` | Pick up cone via EV3 |
| POST | `/cone-chase/start` | Autonomous cone discovery mode |
| POST | `/cone-chase/stop` | Stop cone chase |
| POST | `/lock-on/start` | Visual lock-on to nearest cone |
| POST | `/lock-on/stop` | Stop lock-on |
| POST | `/collect` | Full autonomous collection sequence |
| POST | `/collect/stop` | Abort collection |

### API Endpoints on EV3 cone_mechanism.py (port 8080)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/status` | Mechanism state (busy, cones, positions) |
| POST | `/place` | Drop a cone (column down → spiral reverse → column up) |
| POST | `/pickup` | Pick up a cone (column down → spiral forward → column up) |
| POST | `/calibrate` | Reset motors to home |

### TSP Algorithm Details

- **Location**: `client/src/services/tsp.ts` (runs entirely in browser)
- **Algorithm**: Nearest-Neighbor greedy heuristic
- **Start position**: Robot home (0, 0)
- **Process**: Iteratively selects the nearest unvisited cone
- **Output**: Ordered array of cone positions
- **Invoked by**: ControlPanel component before sending waypoints/collection

### Robot Auto-Discovery

- Server scans `172.20.10.1` through `172.20.10.20` on port 8888
- Probes each IP with `GET /status` (800ms timeout per probe)
- All 20 probes run in parallel
- Returns first responding IP as robot URL

### Robot Locking (Socket.IO)

- `robot:lock` — Acquire exclusive control of a robot URL
- `robot:unlock` — Release control
- `robot:lock-query` — Check if locked
- Auto-releases on socket disconnect

---

## 2. TIMELINE OF A CONE PICKUP

### Full Sequence Breakdown

| Step | Action | Duration | Source |
|------|--------|----------|--------|
| **1** | **App sends `POST /collect`** | ~50ms (HTTP round-trip over LAN) | rosbridge.ts:243 |
| **2** | **cone_bridge receives & starts thread** | <10ms | cone_bridge.py:928 |
| **3** | **Auto-calibration** (first cone only) | **~13-18s** | cone_bridge.py:946-954 |
| 3a | Wait for UWB + odom data | up to 5s (timeout) | cone_bridge.py:228-233 |
| 3b | Drive forward 50cm at 0.15 m/s | ~3.3s | cone_bridge.py:259 |
| 3c | UWB settling delay | 0.3s | cone_bridge.py:259 |
| 3d | Compute yaw offset | <1ms | cone_bridge.py:277 |
| **4** | **Pre-turn toward cone** | **0.5-3s** | cone_bridge.py:1013-1017 |
| | Turn in place at up to 0.8 rad/s | Until heading error < 0.15 rad (8.6°), max 3s | |
| **5** | **Navigate to staging point** (10cm before cone) | **8-15s** | cone_bridge.py:320-467 |
| | Speed: 0.15 m/s max (proportional: dist × 0.5) | Varies by distance | |
| | Goal tolerance: 8cm | | cone_bridge.py:47 |
| | UWB verification: ≤ 10cm | | cone_bridge.py:48 |
| | Control loop rate: 20Hz (50ms sleep) | | cone_bridge.py:467 |
| | Obstacle avoidance: hard stop at 15cm, slowdown at 40cm | | |
| **6** | **Visual servo final approach** | **2-8s** (8s timeout) | cone_bridge.py:842-926 |
| 6a | Camera opens, detects red cones at 20Hz | 50ms/frame | |
| 6b | Center cone in frame (angular gain = 1.8) | ~1-3s | cone_bridge.py:844 |
| 6c | Slow approach at 0.08 m/s | Until distance ≤ 120mm | cone_bridge.py:846, 849 |
| 6d | If cone not seen for 2s → abort as 'missing' | 2s timeout | cone_bridge.py:850 |
| **7** | **Ramming** | **1.5s** (fixed) | cone_bridge.py:848 |
| | Drive straight at 0.06 m/s | 1.5s (RAM_DURATION) | cone_bridge.py:893 |
| | Physically contacts cone with gripper mechanism | | |
| **8** | **Dwell** (wait for mechanism) | **4s** (default, configurable) | cone_bridge.py:1042-1044 |
| **9** | **EV3 pickup** (if mechanism enabled) | **~10s** | cone_mechanism.py:104-127 |
| 9a | Column lowers to position -100 | 4s | cone_mechanism.py:56-57 |
| 9b | Spiral motor rotates (720°/s × cone_count × 360°) | ~1s | cone_mechanism.py:67-69 |
| 9c | Wait for spiral to seat | 2s | cone_mechanism.py:117 |
| 9d | Column raises to position 100 | 4s | cone_mechanism.py:62-63 |
| 9e | cone_bridge polls EV3 `/status` every 0.5s until not busy | 0-0.5s overhead | cone_bridge.py:513-537 |
| **10** | **Status update to app** | <50ms | Next poll cycle (200ms max) |

### Summary Timings

| Phase | Best Case | Typical | Worst Case |
|-------|-----------|---------|------------|
| App signal → Robot receives | ~50ms | ~50ms | ~200ms |
| Calibration (first cone only) | 8s | 13s | 18s |
| Navigation to cone | 5s | 10s | 15s |
| Visual servo + centering | 2s | 4s | 8s |
| Ramming | 1.5s | 1.5s | 1.5s |
| Dwell | 4s | 4s | 4s (configurable) |
| EV3 motor pickup | 8s | 10s | 12s |
| **Total per cone (after first)** | **~16s** | **~20s** | **~30s** |
| **First cone (with calibration)** | **~24s** | **~33s** | **~48s** |

### Key Constants from Code

```python
# Navigation (cone_bridge.py lines 45-50)
LINEAR_SPEED       = 0.15      # m/s max forward speed
ANGULAR_SPEED      = 0.8       # rad/s max turning speed
GOAL_TOLERANCE     = 0.08      # meters (8cm) — "arrived"
UWB_VERIFY_TOLERANCE = 0.10    # meters (10cm) — UWB check
ANGLE_TOLERANCE    = 0.1       # radians (5.7°)

# Visual Servo (cone_bridge.py lines 844-850)
ANGULAR_GAIN       = 1.8       # proportional steering gain
TURN_THRESH        = 0.25      # bearing threshold for turn-in-place
SLOW_SPEED         = 0.08      # m/s approach speed
RAM_SPEED          = 0.06      # m/s ramming speed
RAM_DURATION       = 1.5       # seconds
ARRIVE_DIST_MM     = 120       # mm — trigger ramming
MISSING_TIMEOUT    = 2.0       # seconds — abort if cone lost

# EV3 Mechanism (cone_mechanism.py lines 24-33)
COLUMN_SPEED       = 12        # ticks/sec
COLUMN_POS_TOP     = 100       # absolute position
COLUMN_POS_BOTTOM  = -100      # absolute position
SPIRALS_SPEED      = 720       # ticks/sec (fast rotation)
# Column up/down: 4s each (sleep(4))
# Spiral seat time: 2s (sleep(2))

# Obstacle Avoidance (cone_bridge.py)
OA_HARD_STOP_CM    = 15        # emergency brake distance
OA_SLOW_START_CM   = 40        # proportional slowdown begins
OA_SIDE_BIAS_CM    = 60        # steering influence range

# Polling & Control
STATUS_POLL_RATE   = 200       # ms (5 Hz) — rosbridge.ts:113
CONTROL_LOOP_RATE  = 50        # ms (20 Hz) — cone_bridge.py:467
EV3_POLL_RATE      = 500       # ms — cone_bridge.py:513
EV3_POLL_TIMEOUT   = 30000     # ms (30s max wait)
DISCOVERY_TIMEOUT  = 800       # ms per IP probe — server/src/index.ts:37
```

### Speeds Reference

| Mode | Linear Speed | Angular Speed |
|------|-------------|---------------|
| Normal navigation | 0.15 m/s | up to 0.8 rad/s |
| Visual servo approach | 0.08 m/s | proportional (1.8 × bearing) |
| Ramming | 0.06 m/s | 0 |
| Lock-on search | 0.0 m/s | 0.3 rad/s (spinning) |
| Lock-on approach | up to 0.15 m/s | proportional |

---

## 3. APP SOFTWARE TESTING COVERAGE

### Test Inventory

| Test File | Type | What It Tests | Framework |
|-----------|------|--------------|-----------|
| `ev3/test_motors.py` | Integration (Hardware) | Motor connectivity & individual motor control on all 4 EV3 ports | Manual / ev3dev2 |
| `ev3/test_pickup.py` | Integration (Hardware) | Full pickup sequence: column down → spiral screw → column up | Manual / ev3dev2 |
| `ev3/test_place.py` | Integration (Hardware) | Spiral motor drop sequence (360° per cone release) | Manual / ev3dev2 |
| `test.py` | Integration (Hardware) | Camera capture validation (OpenCV webcam test) | Manual / OpenCV |

### Coverage Summary

| Category | Tests | Pass Rate | Notes |
|----------|-------|-----------|-------|
| **Unit Tests (Client - JS/TS)** | 0 | N/A | No Jest/Vitest configured; no `.test.ts` or `.spec.ts` files in project source |
| **Unit Tests (Server - JS/TS)** | 0 | N/A | No test runner configured |
| **Unit Tests (Python)** | 0 | N/A | No pytest/unittest configured |
| **Integration Tests (Hardware)** | 4 | Manual — pass on hardware | Interactive scripts requiring physical EV3 + camera |
| **End-to-End Tests** | 0 | N/A | No Cypress/Playwright configured |
| **CI/CD Pipeline** | None | N/A | No GitHub Actions or similar found |

### What The Integration Tests Validate

| Test | Validates | How |
|------|-----------|-----|
| `test_motors.py` | EV3 motor detection on outA-outD, individual motor spin to target position | Scans all 4 ports, reports connected/not, runs motor to user-specified degrees |
| `test_pickup.py` | Pickup mechanism full sequence (column lower → spiral engage → column raise) | Interactive: press 'p' to pick up, 'd' to drop, 'a' to reset |
| `test_place.py` | Spiral motor cone release (360° per drop) | Interactive: press Enter to drop, 'q' to quit |
| `test.py` | Camera opens and captures frames | Opens VideoCapture(0), displays frames until 'q' pressed |

### Tech Stack (for context in testing table)

| Layer | Technology | Test Coverage |
|-------|-----------|---------------|
| Frontend | React 19 + TypeScript + Vite | **Not tested** |
| State Management | Zustand | **Not tested** |
| Real-time Comms | Socket.IO | **Not tested** |
| HTTP Client | Fetch API (rosbridge.ts) | **Not tested** |
| TSP Algorithm | Custom nearest-neighbor (tsp.ts) | **Not tested** |
| Backend API | Express + Socket.IO | **Not tested** |
| Robot Bridge | Python + ROS2 (cone_bridge.py) | **Not tested** |
| Cone Detection | OpenCV (cone_detector.py) | **Not tested** |
| UWB Positioning | Python + ROS2 (uwb_node.py) | **Not tested** |
| EV3 Mechanism | ev3dev (cone_mechanism.py) | **4 integration tests** (manual, hardware-dependent) |
| Camera | OpenCV (test.py) | **1 integration test** (manual) |

---

## 4. POSITIONING SYSTEM (supplementary data for flowchart)

### UWB Anchor Layout

```
DC06 (3.50, 3.00) ─────────────────── DB9A (0.00, 3.00)
│                                       │
│           3.5m × 3.0m field           │
│                                       │
0816 (3.50, 0.00) ─────────────────── 029F (0.00, 0.00) ← ORIGIN
```

### Sensor Data Flow (ROS2 Topics)

```
/odom          ← TurtleBot3 wheel encoders (odometry)
/cmd_vel       → TurtleBot3 motor controller (velocity commands)
/scan          ← LiDAR (not actively used in collection, available)
/uwb/pose      ← UWB node trilateration result
Ultrasonic     ← 6× Grove sensors on GPIO (FC, FL, FR, BL, BR, BC)
Camera         ← Logitech C270 USB (640×480, ~20fps in code)
```

### Fused Position Algorithm

```
1. Anchor: snapshot UWB (uwb_anchor) + odom (odom_anchor) at waypoint start
2. Delta:  dx = odom_now.x - odom_anchor.x
           dy = odom_now.y - odom_anchor.y
3. Rotate: rx = dx·cos(yaw_offset) - dy·sin(yaw_offset)
           ry = dx·sin(yaw_offset) + dy·cos(yaw_offset)
4. Fuse:   x = uwb_anchor.x + rx
           y = uwb_anchor.y + ry
```
