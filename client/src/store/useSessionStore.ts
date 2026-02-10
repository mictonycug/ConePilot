
import { create } from 'zustand';
import { api } from '../lib/api';

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

    setOptimizedPath: (path: { x: number, y: number }[]) => void;
    setIsSimulating: (isSimulating: boolean) => void;
    setSimulationStatus: (status: 'IDLE' | 'MOVING' | 'PLACING' | 'COMPLETED') => void;
    updateSimulationStats: (stats: Partial<{ conesPlaced: number; distanceTraveled: number; etaSeconds: number }>) => void;
    updateTelemetry: (telemetry: Partial<{ velocity: number; mechanismVelocity: number }>) => void;
    addSequenceLog: (log: { step: string; timeTaken: number }) => void;
    addPlacementHistory: (entry: { coneIndex: number; totalTime: number; logs: { step: string; timeTaken: number }[] }) => void;
    clearSequenceLogs: () => void;
    resetSimulationStats: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
    sessions: [],
    currentSession: null,
    isLoading: false,
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
        // Optimistic update? Maybe later. For now, simple.
        const { data } = await api.post<{ cone: ConeData }>(`/sessions/${sessionId}/cones`, { x, y });
        set(state => {
            if (!state.currentSession || state.currentSession.id !== sessionId) return state;
            return {
                currentSession: {
                    ...state.currentSession,
                    cones: [...state.currentSession.cones, data.cone]
                }
            };
        });
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
    })
}));
