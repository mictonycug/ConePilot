export const SessionStatus = {
    SETUP: 'SETUP',
    READY: 'READY',
    PLACING: 'PLACING',
    COLLECTING: 'COLLECTING',
    COMPLETED: 'COMPLETED',
    PAUSED: 'PAUSED'
} as const;
export type SessionStatus = typeof SessionStatus[keyof typeof SessionStatus];

export const ConeStatus = {
    PENDING: 'PENDING',
    PLACED: 'PLACED',
    COLLECTED: 'COLLECTED',
    FAILED: 'FAILED'
} as const;
export type ConeStatus = typeof ConeStatus[keyof typeof ConeStatus];

export interface User {
    id: string;
    email: string;
    name: string;
}

export interface Cone {
    id: string;
    sessionId: string;
    x: number;
    y: number;
    orderIndex?: number | null;
    status: ConeStatus;
    placedAt?: string | null;  // ISO Date string
    collectedAt?: string | null; // ISO Date string
}

export interface PathPoint {
    id: string;
    sessionId: string;
    x: number;
    y: number;
    timestamp: string; // ISO Date string
}

export interface Session {
    id: string;
    userId: string;
    name: string;
    fieldWidth: number;
    fieldHeight: number;
    status: SessionStatus;
    cones: Cone[];
    robotPath: PathPoint[];
    createdAt: string; // ISO Date string
    updatedAt: string; // ISO Date string
}

export interface AuthResponse {
    user: User;
    token: string;
}
