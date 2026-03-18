
import { create } from 'zustand';
import { api } from '../lib/api';
import { getSocket } from '../lib/socket';
import { rosBridge, type RobotPose, type RobotStatus } from '../services/rosbridge';
import { calculateOptimalPath } from '../services/tsp';

export const SessionStatus = {
    SETUP: 'SETUP',
    READY: 'READY',
    PLACING: 'PLACING',
    COLLECTING: 'COLLECTING',
    COMPLETED: 'COMPLETED',
    PAUSED: 'PAUSED'
} as const;
export type SessionStatus = typeof SessionStatus[keyof typeof SessionStatus];

export interface ConeData {
    id: string;
    x: number;
    y: number;
    orderIndex?: number | null;
    status: string;
}

export interface SessionData {
    id: string;
    name: string;
    fieldWidth: number;
    fieldHeight: number;
    status: SessionStatus;
    cones: ConeData[];
    robotPath?: { x: number; y: number }[];
    updatedAt?: string;
}

interface SessionState {
    sessions: SessionData[];
    currentSession: SessionData | null;
    isLoading: boolean;

    loadSessions: () => Promise<void>;
    createSession: (name: string, fieldWidth?: number, fieldHeight?: number) => Promise<string>; // returns id
    loadSessionById: (id: string) => Promise<void>;
    deleteSession: (id: string) => Promise<void>;
    renameSession: (id: string, name: string) => Promise<void>;
    addCone: (sessionId: string, x: number, y: number) => Promise<void>;
    isPlacingCone: boolean;
    pendingCone: { x: number; y: number } | null;
    removeCone: (sessionId: string, coneId: string) => Promise<void>;
    removeAllCones: (sessionId: string) => Promise<void>;
    updateConePosition: (sessionId: string, coneId: string, x: number, y: number) => Promise<void>;

    // Simulation State
    optimizedPath: { x: number, y: number }[];
    isSimulating: boolean;
    simulationStatus: 'IDLE' | 'MOVING' | 'PLACING' | 'COMPLETED';
    simulationStats: {
        conesPlaced: number;
        distanceTraveled: number; // in meters
        etaSeconds: number;
    };
    robotTelemetry: {
        velocity: number; // m/s
        mechanismVelocity: number; // m/s
    };
    currentSequenceLogs: { step: string; timeTaken: number }[];
    placementHistory: { coneIndex: number; totalTime: number; logs: { step: string; timeTaken: number }[] }[];

    // Robot Connection State
    robotConnected: boolean;
    robotUrl: string;
    robotPose: RobotPose | null;
    isConnecting: boolean;
    isReadOnly: boolean;
    robotLockHolder: string | null;

    setOptimizedPath: (path: { x: number, y: number }[]) => void;
    setIsSimulating: (isSimulating: boolean) => void;
    setSimulationStatus: (status: 'IDLE' | 'MOVING' | 'PLACING' | 'COMPLETED') => void;
    updateSimulationStats: (stats: Partial<{ conesPlaced: number; distanceTraveled: number; etaSeconds: number }>) => void;
    updateTelemetry: (telemetry: Partial<{ velocity: number; mechanismVelocity: number }>) => void;
    addSequenceLog: (log: { step: string; timeTaken: number }) => void;
    addPlacementHistory: (entry: { coneIndex: number; totalTime: number; logs: { step: string; timeTaken: number }[] }) => void;
    clearSequenceLogs: () => void;
    resetSimulationStats: () => void;

    // Robot Connection Actions
    connectToRobot: (url: string) => Promise<void>;
    disconnectRobot: () => void;
    sendWaypointsToRobot: () => void;
    stopRobot: () => void;

    // Debug Mode
    debugMode: boolean;
    debugWaypointIndex: number;
    debugIntervalId: number | null;
    setDebugMode: (enabled: boolean) => void;
    debugAdvanceWaypoint: () => void;
    startDebugSimulation: () => void;
    stopDebugSimulation: () => void;

    // Mission State
    missionActive: boolean;
    missionConeIds: Set<string>;
    missionDwellTime: number;
    missionWaypointIndex: number;
    missionWaypointTotal: number;
    missionWaypointState: 'idle' | 'calibrating' | 'navigating' | 'dwelling' | 'completed';
    missionDwellRemaining: number;

    // Mission Actions
    toggleMissionCone: (coneId: string) => void;
    setMissionDwellTime: (seconds: number) => void;
    startMission: () => void;
    clearMissionSelection: () => void;
    selectAllConesForMission: () => void;
    stopMission: () => void;

    // Cone Chase State
    coneChaseActive: boolean;
    coneChaseState: string | null;
    coneChaseReached: number;
    coneChaseMax: number;

    // Cone Chase Actions
    startConeChase: (maxCones?: number) => void;
    stopConeChase: () => void;
    setConeChaseMax: (n: number) => void;

    // Lock-on State
    lockOnActive: boolean;
    lockOnLocked: boolean;
    lockOnDistance: number | null;
    lockOnBearing: number | null;

    // Lock-on Actions
    startLockOn: () => void;
    stopLockOn: () => void;
}

export const useSessionStore = create<SessionState>((set, get) => ({
    sessions: [],
    currentSession: null,
    isLoading: false,
    isPlacingCone: false,
    pendingCone: null,
    optimizedPath: [],
    isSimulating: false,
    simulationStatus: 'IDLE',
    simulationStats: {
        conesPlaced: 0,
        distanceTraveled: 0,
        etaSeconds: 0
    },
    robotTelemetry: {
        velocity: 0,
        mechanismVelocity: 0
    },
    currentSequenceLogs: [],
    placementHistory: [],

    // Robot Connection State
    robotConnected: false,
    robotUrl: '/robot',
    robotPose: null,
    isConnecting: false,
    isReadOnly: false,
    robotLockHolder: null,

    // Cone Chase State
    coneChaseActive: false,
    coneChaseState: null,
    coneChaseReached: 0,
    coneChaseMax: 0,

    // Debug Mode
    debugMode: false,
    debugWaypointIndex: 0,
    debugIntervalId: null,

    // Lock-on State
    lockOnActive: false,
    lockOnLocked: false,
    lockOnDistance: null,
    lockOnBearing: null,

    // Mission State
    missionActive: false,
    missionConeIds: new Set<string>(),
    missionDwellTime: 3,
    missionWaypointIndex: 0,
    missionWaypointTotal: 0,
    missionWaypointState: 'idle',
    missionDwellRemaining: 0,

    loadSessions: async () => {
        set({ isLoading: true });
        try {
            const { data } = await api.get<{ sessions: SessionData[] }>('/sessions');
            set({ sessions: data.sessions, isLoading: false });
        } catch (e) {
            set({ isLoading: false });
        }
    },


    createSession: async (name, fieldWidth, fieldHeight) => {
        set({ isLoading: true });
        try {
            const { data } = await api.post<{ session: SessionData }>('/sessions', { name, fieldWidth, fieldHeight });
            set(state => ({
                sessions: [data.session, ...state.sessions],
                isLoading: false,
                // Clear simulation state for new session
                optimizedPath: [],
                simulationStats: { conesPlaced: 0, distanceTraveled: 0, etaSeconds: 0 },
                currentSequenceLogs: [],
                placementHistory: []
            }));
            return data.session.id;
        } catch (e) {
            set({ isLoading: false });
            throw e;
        }
    },

    loadSessionById: async (id) => {
        set({ isLoading: true });
        try {
            const { data } = await api.get<{ session: SessionData }>(`/sessions/${id}`);
            set({
                currentSession: data.session,
                // Sync optimizedPath with the session's stored path
                optimizedPath: data.session.robotPath ? data.session.robotPath.map(p => ({ x: p.x, y: p.y })) : [],
                isLoading: false,
                // Reset simulation state when switching sessions
                simulationStatus: 'IDLE',
                isSimulating: false,
                currentSequenceLogs: [],
                placementHistory: []
            });
        } catch (e) {
            set({ isLoading: false });
        }
    },

    deleteSession: async (id) => {
        set({ isLoading: true });
        try {
            await api.delete(`/sessions/${id}`);
            set(state => ({
                sessions: state.sessions.filter(s => s.id !== id),
                isLoading: false,
                currentSession: state.currentSession?.id === id ? null : state.currentSession
            }));
        } catch (e) {
            set({ isLoading: false });
            throw e;
        }
    },

    renameSession: async (id, name) => {
        // Optimistic update
        set(state => ({
            sessions: state.sessions.map(s => s.id === id ? { ...s, name } : s),
            currentSession: state.currentSession?.id === id ? { ...state.currentSession, name } : state.currentSession
        }));

        try {
            await api.put(`/sessions/${id}`, { name });
        } catch (e) {
            // Revert? For now just log
            console.error("Failed to rename session", e);
            // Could reload sessions here to revert
        }
    },

    addCone: async (sessionId, x, y) => {
        if (useSessionStore.getState().isPlacingCone) return;
        set({ isPlacingCone: true, pendingCone: { x, y } });
        try {
            const { data } = await api.post<{ cone: ConeData }>(`/sessions/${sessionId}/cones`, { x, y });
            set(state => {
                if (!state.currentSession || state.currentSession.id !== sessionId) return { isPlacingCone: false, pendingCone: null };
                return {
                    currentSession: {
                        ...state.currentSession,
                        cones: [...state.currentSession.cones, data.cone]
                    },
                    isPlacingCone: false,
                    pendingCone: null,
                };
            });
        } catch (e) {
            set({ isPlacingCone: false, pendingCone: null });
        }
    },

    removeCone: async (sessionId, coneId) => {
        await api.delete(`/sessions/${sessionId}/cones/${coneId}`);
        set(state => {
            if (!state.currentSession || state.currentSession.id !== sessionId) return state;
            return {
                currentSession: {
                    ...state.currentSession,
                    cones: state.currentSession.cones.filter(c => c.id !== coneId)
                }
            };
        });
    },

    removeAllCones: async (sessionId) => {
        const state = useSessionStore.getState();
        if (!state.currentSession || state.currentSession.id !== sessionId) return;
        const coneIds = state.currentSession.cones.map(c => c.id);
        // Optimistic clear
        set(state => {
            if (!state.currentSession || state.currentSession.id !== sessionId) return state;
            return { currentSession: { ...state.currentSession, cones: [] } };
        });
        await Promise.all(coneIds.map(id => api.delete(`/sessions/${sessionId}/cones/${id}`)));
    },

    updateConePosition: async (sessionId, coneId, x, y) => {
        // Optimistic update
        set(state => {
            if (!state.currentSession || state.currentSession.id !== sessionId) return state;
            return {
                currentSession: {
                    ...state.currentSession,
                    cones: state.currentSession.cones.map(c => c.id === coneId ? { ...c, x, y } : c)
                }
            };
        });

        // Debounce this in real app, but for now direct call
        await api.put(`/sessions/${sessionId}/cones/${coneId}`, { x, y });
    },

    setOptimizedPath: (path) => set({ optimizedPath: path }),
    setIsSimulating: (isSimulating) => set({ isSimulating, simulationStatus: isSimulating ? 'MOVING' : 'IDLE' }),
    setSimulationStatus: (status) => set({ simulationStatus: status }),
    updateSimulationStats: (stats) => set(state => ({
        simulationStats: { ...state.simulationStats, ...stats }
    })),
    updateTelemetry: (telemetry) => set(state => ({
        robotTelemetry: { ...state.robotTelemetry, ...telemetry }
    })),
    addSequenceLog: (log) => set(state => ({
        currentSequenceLogs: [...state.currentSequenceLogs, log]
    })),
    addPlacementHistory: (entry) => set(state => ({
        placementHistory: [entry, ...state.placementHistory] // Newest first
    })),
    clearSequenceLogs: () => set({ currentSequenceLogs: [] }),
    resetSimulationStats: () => set({
        simulationStats: { conesPlaced: 0, distanceTraveled: 0, etaSeconds: 0 },
        robotTelemetry: { velocity: 0, mechanismVelocity: 0 },
        currentSequenceLogs: [],
        placementHistory: [],
        simulationStatus: 'IDLE'
    }),

    // Robot Connection Actions
    connectToRobot: async (url: string) => {
        set({ isConnecting: true, robotUrl: url });

        const CONNECTION_TIMEOUT_MS = 30_000;

        try {
            rosBridge.setCallbacks({
                onConnectionChange: (connected) => {
                    set({ robotConnected: connected });
                    if (!connected) set({ robotPose: null, missionActive: false, coneChaseActive: false, coneChaseState: null, lockOnActive: false, lockOnLocked: false, lockOnDistance: null, lockOnBearing: null });
                },
                onPoseUpdate: (pose) => {
                    // Client-side EMA smoothing to eliminate visual jitter
                    const prev = get().robotPose;
                    if (prev) {
                        const alpha = 0.3; // 30% new, 70% old — smooth but responsive
                        set({
                            robotPose: {
                                x: alpha * pose.x + (1 - alpha) * prev.x,
                                y: alpha * pose.y + (1 - alpha) * prev.y,
                                theta: pose.theta, // don't smooth heading
                            },
                        });
                    } else {
                        set({ robotPose: pose });
                    }
                },
                onStatusUpdate: (status: RobotStatus) => {
                    set({
                        missionWaypointIndex: status.waypoint_index,
                        missionWaypointTotal: status.waypoint_total,
                        missionWaypointState: status.waypoint_state,
                        missionDwellRemaining: status.dwell_remaining,
                        coneChaseActive: status.cone_chase_active,
                        coneChaseState: status.cone_chase?.state ?? null,
                        coneChaseReached: status.cone_chase?.cones_reached ?? 0,
                        lockOnActive: status.lock_on_active,
                        lockOnLocked: status.lock_on?.locked ?? false,
                        lockOnDistance: status.lock_on?.distance_m ?? null,
                        lockOnBearing: status.lock_on?.bearing_deg ?? null,
                    });
                    // Auto-detect mission completion
                    if (status.waypoint_state === 'completed') {
                        set({ missionActive: false });
                    }
                    // Auto-detect cone chase completion
                    if (!status.cone_chase_active) {
                        set({ coneChaseActive: false });
                    }
                },
            });

            // Race the entire connection + lock flow against a 30s timeout
            const timeoutPromise = new Promise<never>((_, reject) =>
                setTimeout(() => reject(new Error('Connection timed out after 30 seconds')), CONNECTION_TIMEOUT_MS)
            );

            await Promise.race([
                (async () => {
                    await rosBridge.connect(url);

                    // Request exclusive lock via Socket.io
                    const socket = getSocket();
                    const normalizedUrl = url.replace(/\/+$/, '').toLowerCase();

                    // Listen for lock released (other controller disconnected)
                    socket.off('robot:lock-released');
                    socket.on('robot:lock-released', (data: { robotUrl: string }) => {
                        if (data.robotUrl === normalizedUrl) {
                            set({ robotLockHolder: null });
                            // Don't auto-acquire — user can reconnect to get control
                        }
                    });

                    // Listen for lock state changes
                    socket.off('robot:lock-state');
                    socket.on('robot:lock-state', (data: { robotUrl: string; lockedBy: string }) => {
                        if (data.robotUrl === normalizedUrl) {
                            set({ robotLockHolder: data.lockedBy });
                        }
                    });

                    const response = await new Promise<{ granted: boolean }>((resolve) => {
                        socket.emit('robot:lock', url, resolve);
                    });

                    set({
                        isConnecting: false,
                        isReadOnly: !response.granted,
                        robotLockHolder: response.granted ? socket.id ?? null : 'other',
                    });
                })(),
                timeoutPromise,
            ]);
        } catch (e) {
            console.error('[RosBridge] Connection failed:', e);
            rosBridge.disconnect();
            set({ isConnecting: false, robotConnected: false });
        }
    },

    disconnectRobot: () => {
        const state = useSessionStore.getState();
        if (state.debugMode) {
            get().setDebugMode(false);
            return;
        }
        // Release lock if we held it
        if (!state.isReadOnly && state.robotConnected) {
            const socket = getSocket();
            socket.emit('robot:unlock', state.robotUrl);
            socket.off('robot:lock-released');
            socket.off('robot:lock-state');
        }
        rosBridge.disconnect();
        set({ robotConnected: false, robotPose: null, isReadOnly: false, robotLockHolder: null });
    },

    sendWaypointsToRobot: async () => {
        const state = useSessionStore.getState();
        if (state.debugMode) return;
        if (state.isReadOnly) return;
        if (!state.robotConnected || state.optimizedPath.length === 0) return;

        // Skip the first point (0,0 start) — send cone waypoints
        const waypoints = state.optimizedPath.slice(1);

        set({ isSimulating: true, simulationStatus: 'MOVING' });

        const success = await rosBridge.sendWaypoints(waypoints);
        if (!success) {
            set({ isSimulating: false, simulationStatus: 'IDLE' });
        }
        // Pose updates come via polling; waypoint progress tracked via /status
    },

    stopRobot: () => {
        const state = useSessionStore.getState();
        if (state.isReadOnly) return;
        if (state.debugMode) {
            get().stopDebugSimulation();
            return;
        }
        rosBridge.stop();
        set({ isSimulating: false, simulationStatus: 'IDLE' });
    },

    // Mission Actions
    toggleMissionCone: (coneId: string) => {
        set(state => {
            const next = new Set(state.missionConeIds);
            if (next.has(coneId)) {
                next.delete(coneId);
            } else {
                next.add(coneId);
            }
            return { missionConeIds: next };
        });
    },

    setMissionDwellTime: (seconds: number) => {
        set({ missionDwellTime: Math.max(0, seconds) });
    },

    startMission: async () => {
        const state = useSessionStore.getState();
        if (state.isReadOnly) return;
        if (!state.robotConnected || state.missionConeIds.size === 0 || !state.currentSession) return;

        // Get selected cones
        const selectedCones = state.currentSession.cones
            .filter(c => state.missionConeIds.has(c.id))
            .map(c => ({ id: c.id, x: c.x, y: c.y }));

        if (selectedCones.length === 0) return;

        // TSP optimize from robot's current position (or origin)
        const startPos = state.robotPose
            ? { id: 'start', x: state.robotPose.x, y: state.robotPose.y }
            : { id: 'start', x: 0, y: 0 };

        const ordered = calculateOptimalPath(selectedCones, startPos);
        const waypoints = ordered.map(p => ({ x: p.x, y: p.y }));

        set({ missionActive: true });

        const success = await rosBridge.sendWaypoints(waypoints, state.missionDwellTime);
        if (!success) {
            set({ missionActive: false });
        }
    },

    clearMissionSelection: () => {
        set({ missionConeIds: new Set<string>() });
    },

    selectAllConesForMission: () => {
        const state = useSessionStore.getState();
        if (!state.currentSession) return;
        set({ missionConeIds: new Set(state.currentSession.cones.map(c => c.id)) });
    },

    stopMission: () => {
        if (useSessionStore.getState().isReadOnly) return;
        rosBridge.stop();
        set({ missionActive: false });
    },

    // Cone Chase Actions
    startConeChase: async (maxCones?: number) => {
        const state = useSessionStore.getState();
        if (state.isReadOnly) return;
        if (!state.robotConnected || state.missionActive) return;
        const cones = maxCones ?? state.coneChaseMax;
        const success = await rosBridge.startConeChase(cones);
        if (success) {
            set({ coneChaseActive: true });
        }
    },

    stopConeChase: async () => {
        if (useSessionStore.getState().isReadOnly) return;
        await rosBridge.stopConeChase();
        set({ coneChaseActive: false, coneChaseState: null, coneChaseReached: 0 });
    },

    setConeChaseMax: (n: number) => {
        set({ coneChaseMax: Math.max(0, n) });
    },

    // Debug Mode Actions
    setDebugMode: (enabled: boolean) => {
        if (enabled) {
            set({
                debugMode: true,
                robotConnected: true,
                robotPose: { x: 0, y: 0, theta: 0 },
            });
        } else {
            const state = get();
            if (state.debugIntervalId !== null) {
                clearInterval(state.debugIntervalId);
            }
            set({
                debugMode: false,
                robotConnected: false,
                robotPose: null,
                isSimulating: false,
                simulationStatus: 'IDLE',
                debugWaypointIndex: 0,
                debugIntervalId: null,
            });
        }
    },

    startDebugSimulation: () => {
        const state = get();
        const path = state.optimizedPath;
        if (path.length === 0) return;

        set({
            isSimulating: true,
            simulationStatus: 'MOVING',
            debugWaypointIndex: 0,
            simulationStats: { conesPlaced: 0, distanceTraveled: 0, etaSeconds: 0 },
        });

        const SPEED = 2; // m/s
        const TICK_MS = 50;
        const stepDist = SPEED * (TICK_MS / 1000);

        const id = window.setInterval(() => {
            const s = get();
            const idx = s.debugWaypointIndex;
            if (idx >= path.length) {
                clearInterval(s.debugIntervalId!);
                set({ isSimulating: false, simulationStatus: 'COMPLETED', debugIntervalId: null });
                return;
            }

            const target = path[idx];
            const pose = s.robotPose ?? { x: 0, y: 0, theta: 0 };
            const dx = target.x - pose.x;
            const dy = target.y - pose.y;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < 0.05) {
                // Reached waypoint
                const nextIdx = idx + 1;
                // Count placed cones (skip index 0 which is the start position)
                const conesPlaced = idx >= 1 ? idx : 0;
                set({
                    debugWaypointIndex: nextIdx,
                    robotPose: { x: target.x, y: target.y, theta: Math.atan2(dy, dx) },
                    simulationStats: { ...s.simulationStats, conesPlaced },
                });
                if (nextIdx >= path.length) {
                    clearInterval(s.debugIntervalId!);
                    set({
                        isSimulating: false,
                        simulationStatus: 'COMPLETED',
                        debugIntervalId: null,
                        simulationStats: { ...s.simulationStats, conesPlaced: path.length - 1 },
                    });
                }
                return;
            }

            // Lerp toward target
            const ratio = stepDist / dist;
            const nx = pose.x + dx * ratio;
            const ny = pose.y + dy * ratio;
            set({
                robotPose: { x: nx, y: ny, theta: Math.atan2(dy, dx) },
                simulationStats: {
                    ...s.simulationStats,
                    distanceTraveled: s.simulationStats.distanceTraveled + stepDist,
                },
            });
        }, TICK_MS);

        set({ debugIntervalId: id });
    },

    stopDebugSimulation: () => {
        const state = get();
        if (state.debugIntervalId !== null) {
            clearInterval(state.debugIntervalId);
        }
        set({
            isSimulating: false,
            simulationStatus: 'IDLE',
            debugIntervalId: null,
        });
    },

    debugAdvanceWaypoint: () => {
        const state = get();
        const path = state.optimizedPath;
        const idx = state.debugWaypointIndex;
        if (idx >= path.length) return;

        const target = path[idx];
        const nextIdx = idx + 1;
        const conesPlaced = idx >= 1 ? idx : 0;

        set({
            robotPose: { x: target.x, y: target.y, theta: 0 },
            debugWaypointIndex: nextIdx,
            simulationStats: { ...state.simulationStats, conesPlaced },
        });

        if (nextIdx >= path.length) {
            if (state.debugIntervalId !== null) {
                clearInterval(state.debugIntervalId);
            }
            set({
                isSimulating: false,
                simulationStatus: 'COMPLETED',
                debugIntervalId: null,
                simulationStats: { ...state.simulationStats, conesPlaced: path.length - 1 },
            });
        }
    },

    // Lock-on Actions
    startLockOn: async () => {
        const state = useSessionStore.getState();
        if (state.isReadOnly) return;
        if (!state.robotConnected || state.missionActive || state.coneChaseActive) return;
        const success = await rosBridge.startLockOn();
        if (success) {
            set({ lockOnActive: true });
        }
    },

    stopLockOn: async () => {
        if (useSessionStore.getState().isReadOnly) return;
        await rosBridge.stopLockOn();
        set({ lockOnActive: false, lockOnLocked: false, lockOnDistance: null, lockOnBearing: null });
    },
}));
