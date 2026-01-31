import { create } from 'zustand';
import { api } from '../lib/api';
// import { Session, Cone } from '../../../shared/types'; // (Unused)

// Re-defining for safety in store file to avoid path hell if alias is flaky
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
    updatedAt?: string;
}

interface SessionState {
    sessions: SessionData[];
    currentSession: SessionData | null;
    isLoading: boolean;

    loadSessions: () => Promise<void>;
    createSession: (name: string) => Promise<string>; // returns id
    loadSessionById: (id: string) => Promise<void>;
    addCone: (sessionId: string, x: number, y: number) => Promise<void>;
    removeCone: (sessionId: string, coneId: string) => Promise<void>;
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


    createSession: async (name) => {
        set({ isLoading: true });
        try {
            const { data } = await api.post<{ session: SessionData }>('/sessions', { name });
            set(state => ({
                sessions: [data.session, ...state.sessions],
                isLoading: false
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
            set({ currentSession: data.session, isLoading: false });
        } catch (e) {
            set({ isLoading: false });
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
