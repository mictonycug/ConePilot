import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { createServer } from 'http';
import { Server } from 'socket.io';
import authRoutes from './routes/auth';

dotenv.config();

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
    cors: {
        origin: '*', // Allow all for dev, restrict in prod
        methods: ['GET', 'POST']
    }
});

app.use(cors());
app.use(express.json());

import sessionRoutes from './routes/sessions';

app.use('/api/auth', authRoutes);
app.use('/api/sessions', sessionRoutes);

const PORT = process.env.PORT || 3001;

app.get('/health', (req, res) => {
    res.json({ status: 'ok' });
});

// --- Robot auto-discovery: scan local subnet for cone_bridge on port 8888 ---
app.get('/api/discover-robot', async (req, res) => {
    const subnet = (req.query.subnet as string) || '172.20.10';
    const port = 8888;
    const timeout = 800; // ms per probe
    const range = Array.from({ length: 20 }, (_, i) => i + 1); // .1 through .20

    console.log(`[Discovery] Scanning ${subnet}.1-20:${port}...`);

    const probe = async (ip: string): Promise<string | null> => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
            const resp = await fetch(`http://${ip}:${port}/status`, {
                signal: controller.signal,
            });
            if (resp.ok) {
                const data = await resp.json();
                if (data.connected !== undefined) {
                    return ip;
                }
            }
        } catch {
            // timeout or connection refused — not the robot
        } finally {
            clearTimeout(timer);
        }
        return null;
    };

    // Probe all IPs in parallel
    const results = await Promise.all(
        range.map((i) => probe(`${subnet}.${i}`))
    );
    const found = results.filter(Boolean) as string[];

    if (found.length > 0) {
        const robotUrl = `http://${found[0]}:${port}`;
        console.log(`[Discovery] Found robot at ${robotUrl}`);
        res.json({ found: true, ip: found[0], url: robotUrl, all: found });
    } else {
        console.log(`[Discovery] No robot found on ${subnet}.1-20`);
        res.json({ found: false, ip: null, url: null, all: [] });
    }
});

// --- In-memory robot locks: normalizedUrl -> { socketId, lockedAt } ---
const robotLocks = new Map<string, { socketId: string; lockedAt: number }>();

function normalizeUrl(url: string): string {
    return url.replace(/\/+$/, '').toLowerCase();
}

io.on('connection', (socket) => {
    console.log('User connected:', socket.id);

    socket.on('robot:lock', (robotUrl: string, callback: (response: { granted: boolean }) => void) => {
        const key = normalizeUrl(robotUrl);
        const existing = robotLocks.get(key);

        if (!existing || existing.socketId === socket.id) {
            robotLocks.set(key, { socketId: socket.id, lockedAt: Date.now() });
            console.log(`[Lock] Granted ${key} to ${socket.id}`);
            callback({ granted: true });
            io.emit('robot:lock-state', { robotUrl: key, lockedBy: socket.id });
        } else {
            console.log(`[Lock] Denied ${key} for ${socket.id} (held by ${existing.socketId})`);
            callback({ granted: false });
        }
    });

    socket.on('robot:unlock', (robotUrl: string) => {
        const key = normalizeUrl(robotUrl);
        const existing = robotLocks.get(key);
        if (existing && existing.socketId === socket.id) {
            robotLocks.delete(key);
            console.log(`[Lock] Released ${key} by ${socket.id}`);
            io.emit('robot:lock-released', { robotUrl: key });
        }
    });

    socket.on('robot:lock-query', (robotUrl: string, callback: (response: { locked: boolean; lockedBy: string | null }) => void) => {
        const key = normalizeUrl(robotUrl);
        const existing = robotLocks.get(key);
        callback({
            locked: !!existing,
            lockedBy: existing?.socketId ?? null,
        });
    });

    socket.on('disconnect', () => {
        console.log('User disconnected:', socket.id);
        // Release all locks held by this socket
        for (const [key, lock] of robotLocks.entries()) {
            if (lock.socketId === socket.id) {
                robotLocks.delete(key);
                console.log(`[Lock] Auto-released ${key} (socket disconnected)`);
                io.emit('robot:lock-released', { robotUrl: key });
            }
        }
    });
});

httpServer.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});
