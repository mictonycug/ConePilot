export interface RobotPose {
    x: number;
    y: number;
    theta: number;
}

interface RobotStatus {
    connected: boolean;
    nav_in_progress: boolean;
    pose: RobotPose;
}

type ConnectionCallback = (connected: boolean) => void;
type PoseCallback = (pose: RobotPose) => void;

class RosBridge {
    private baseUrl = '';
    private pollInterval: ReturnType<typeof setInterval> | null = null;
    private onConnectionChange: ConnectionCallback | null = null;
    private onPoseUpdate: PoseCallback | null = null;

    private _connected = false;

    get connected() { return this._connected; }

    setCallbacks(cbs: {
        onConnectionChange?: ConnectionCallback;
        onPoseUpdate?: PoseCallback;
    }) {
        if (cbs.onConnectionChange) this.onConnectionChange = cbs.onConnectionChange;
        if (cbs.onPoseUpdate) this.onPoseUpdate = cbs.onPoseUpdate;
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

        // Poll odom at 5Hz
        this.pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`${this.baseUrl}/odom`);
                if (res.ok) {
                    const pose: RobotPose = await res.json();
                    this.onPoseUpdate?.(pose);
                }
            } catch (e) {
                console.warn('[RosBridge] Odom poll failed, disconnecting:', e);
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

    async sendWaypoints(waypoints: { x: number; y: number }[]): Promise<boolean> {
        if (!this._connected) return false;
        try {
            const res = await fetch(`${this.baseUrl}/waypoints`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ waypoints }),
            });
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
