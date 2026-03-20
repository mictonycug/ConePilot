export interface RobotPose {
    x: number;
    y: number;
    theta: number;
}

export interface ConeChaseStatus {
    state: string;
    cones_reached: number;
    max_cones: number;
    tracks: number;
    confirmed: number;
    visited: number;
}

export interface CollectionConeResult {
    cone_id: string;
    status: 'pending' | 'collected' | 'missing';
}

export interface CollectionStatus {
    active: boolean;
    cone_index: number;
    cone_total: number;
    cone_id: string;
    phase: 'navigating' | 'visual_servo' | 'ramming' | 'dwell' | 'missing' | 'done';
    phase_detail: string;
    results: CollectionConeResult[];
}

export interface RobotStatus {
    connected: boolean;
    navigating: boolean;
    calibrated: boolean;
    pose: RobotPose;
    uwb_pose: { x: number; y: number } | null;
    odom_pose: RobotPose;
    waypoint_index: number;
    waypoint_total: number;
    waypoint_state: 'idle' | 'calibrating' | 'navigating' | 'dwelling' | 'completed';
    dwell_remaining: number;
    cone_chase_active: boolean;
    cone_chase: ConeChaseStatus | null;
    lock_on_active: boolean;
    lock_on: { locked: boolean; distance_m?: number; bearing_deg?: number } | null;
    collection: CollectionStatus | null;
    ultrasonic: Record<string, number> | null;
    nav_debug: {
        oa_state?: string;
        oa_speed?: number;
        oa_steer?: number;
        dist?: number;
        goal?: [number, number];
    } | null;
}

type ConnectionCallback = (connected: boolean) => void;
type PoseCallback = (pose: RobotPose) => void;
type StatusCallback = (status: RobotStatus) => void;

class RosBridge {
    private baseUrl = '';
    private pollInterval: ReturnType<typeof setInterval> | null = null;
    private onConnectionChange: ConnectionCallback | null = null;
    private onPoseUpdate: PoseCallback | null = null;
    private onStatusUpdate: StatusCallback | null = null;

    private _connected = false;

    get connected() { return this._connected; }

    setCallbacks(cbs: {
        onConnectionChange?: ConnectionCallback;
        onPoseUpdate?: PoseCallback;
        onStatusUpdate?: StatusCallback;
    }) {
        if (cbs.onConnectionChange) this.onConnectionChange = cbs.onConnectionChange;
        if (cbs.onPoseUpdate) this.onPoseUpdate = cbs.onPoseUpdate;
        if (cbs.onStatusUpdate) this.onStatusUpdate = cbs.onStatusUpdate;
    }

    async connect(url: string): Promise<void> {
        this.disconnect();
        this.baseUrl = url.replace(/\/$/, '');

        console.log(`[RosBridge] Connecting to ${this.baseUrl}/status ...`);

        // Test connection
        const res = await fetch(`${this.baseUrl}/status`);
        if (!res.ok) throw new Error(`Failed to connect: HTTP ${res.status}`);

        const statusData = await res.json();
        console.log(`[RosBridge] Connected!`, statusData);

        this._connected = true;
        this.onConnectionChange?.(true);

        // Poll status at 5Hz (includes pose + mission progress)
        this.pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`${this.baseUrl}/status`);
                if (res.ok) {
                    const status: RobotStatus = await res.json();
                    this.onPoseUpdate?.(status.pose);
                    this.onStatusUpdate?.(status);
                }
            } catch (e) {
                console.warn('[RosBridge] Status poll failed, disconnecting:', e);
                this._connected = false;
                this.onConnectionChange?.(false);
                this.disconnect();
            }
        }, 200);
    }

    disconnect() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
        this._connected = false;
        this.baseUrl = '';
    }

    async navigateToPoint(x: number, y: number, theta: number = 0): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/navigate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x, y, theta }),
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    async sendWaypoints(waypoints: { x: number; y: number }[], dwellTime?: number, obstacleAvoidance: boolean = true, mechanism?: 'place' | 'pickup' | null): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const payload: Record<string, unknown> = {
                waypoints,
                dwell_time: dwellTime ?? 0,
                obstacle_avoidance: obstacleAvoidance,
            };
            if (mechanism) payload.mechanism = mechanism;
            console.log('[RosBridge] sendWaypoints payload:', JSON.stringify(payload));
            const res = await fetch(`${this.baseUrl}/waypoints`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            console.log('[RosBridge] sendWaypoints response:', res.status, res.ok);
            return res.ok;
        } catch {
            return false;
        }
    }

    async triggerMechanism(action: 'place' | 'pickup'): Promise<boolean> {
        if (!this._connected) return false;
        try {
            console.log(`[RosBridge] mechanism/${action}`);
            const res = await fetch(`${this.baseUrl}/mechanism/${action}`, { method: 'POST' });
            return res.ok;
        } catch {
            return false;
        }
    }

    async sendVelocity(linear: number, angular: number): Promise<void> {
        if (!this._connected) {
            console.warn('[RosBridge] sendVelocity ignored — not connected');
            return;
        }
        console.log(`[RosBridge] cmd_vel: linear=${linear}, angular=${angular}`);
        await fetch(`${this.baseUrl}/cmd_vel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ linear, angular }),
        }).catch((e) => console.error('[RosBridge] cmd_vel failed:', e));
    }

    async stop(): Promise<void> {
        if (!this._connected) return;
        await fetch(`${this.baseUrl}/stop`, { method: 'POST' }).catch(() => {});
    }

    async startConeChase(maxCones?: number, camera?: number): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/cone-chase/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ max_cones: maxCones ?? 0, camera: camera ?? 0 }),
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    async stopConeChase(): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/cone-chase/stop`, {
                method: 'POST',
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    async startLockOn(): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/lock-on/start`, {
                method: 'POST',
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    async stopLockOn(): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/lock-on/stop`, {
                method: 'POST',
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    async startCollection(cones: { id: string; x: number; y: number }[], dwellTime: number = 4.0): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/collect`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cones, dwell_time: dwellTime }),
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    async stopCollection(): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/collect/stop`, {
                method: 'POST',
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    async getStatus(): Promise<RobotStatus | null> {
        if (!this._connected) return null;
        try {
            const res = await fetch(`${this.baseUrl}/status`);
            return await res.json();
        } catch {
            return null;
        }
    }
}

export const rosBridge = new RosBridge();
