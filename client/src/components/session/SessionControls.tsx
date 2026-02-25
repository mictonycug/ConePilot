import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Play, Square, Trash2, Wifi, WifiOff, Bot } from 'lucide-react';
import { useSessionStore } from '../../store/useSessionStore';
import { rosBridge } from '../../services/rosbridge';

interface SessionControlsProps {
    onStart: () => void;
    onStop: () => void;
    onClearAll: () => void;
    isSimulating: boolean;
    coneCount: number;
}

export const SessionControls: React.FC<SessionControlsProps> = ({ onStart, onStop, onClearAll, isSimulating, coneCount }) => {
    const {
        robotConnected,
        robotUrl,
        isConnecting,
        connectToRobot,
        disconnectRobot,
        sendWaypointsToRobot,
        stopRobot,
        optimizedPath,
    } = useSessionStore();

    const [urlInput, setUrlInput] = useState(robotUrl);
    const [showConnect, setShowConnect] = useState(false);

    // WASD manual control
    const LINEAR_SPEED = 0.15;
    const ANGULAR_SPEED = 0.5;
    const pressedKeys = useRef(new Set<string>());
    const [activeKeys, setActiveKeys] = useState(new Set<string>());

    const computeAndSend = useCallback(() => {
        const keys = pressedKeys.current;
        let linear = 0;
        let angular = 0;

        if (keys.has('w')) linear += LINEAR_SPEED;
        if (keys.has('s')) linear -= LINEAR_SPEED;
        if (keys.has('a')) angular += ANGULAR_SPEED;
        if (keys.has('d')) angular -= ANGULAR_SPEED;

        rosBridge.sendVelocity(linear, angular);
    }, []);

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            const key = e.key.toLowerCase();
            if (!['w', 'a', 's', 'd'].includes(key)) return;
            if (e.repeat) return;
            // Don't capture if user is typing in an input
            if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return;

            if (!robotConnected) {
                console.warn(`[WASD] Key '${key}' pressed but robot not connected`);
                return;
            }

            pressedKeys.current.add(key);
            setActiveKeys(new Set(pressedKeys.current));
            computeAndSend();
        };

        const handleKeyUp = (e: KeyboardEvent) => {
            const key = e.key.toLowerCase();
            if (!['w', 'a', 's', 'd'].includes(key)) return;

            pressedKeys.current.delete(key);
            setActiveKeys(new Set(pressedKeys.current));
            computeAndSend();
        };

        // Stop robot if window loses focus
        const handleBlur = () => {
            pressedKeys.current.clear();
            setActiveKeys(new Set());
            rosBridge.sendVelocity(0, 0);
        };

        window.addEventListener('keydown', handleKeyDown);
        window.addEventListener('keyup', handleKeyUp);
        window.addEventListener('blur', handleBlur);

        return () => {
            window.removeEventListener('keydown', handleKeyDown);
            window.removeEventListener('keyup', handleKeyUp);
            window.removeEventListener('blur', handleBlur);
            // Stop on unmount
            rosBridge.sendVelocity(0, 0);
        };
    }, [robotConnected, computeAndSend]);

    // Debug: log connection state changes
    useEffect(() => {
        console.log(`[RosBridge] robotConnected = ${robotConnected}`);
    }, [robotConnected]);

    const handleConnect = async () => {
        await connectToRobot(urlInput);
    };

    return (
        <div className="flex flex-col gap-3 w-full">
            {/* Simulation Controls */}
            <div className="flex gap-3">
                <button
                    onClick={onStart}
                    className="flex-1 flex items-center justify-center gap-2 py-3 px-4 bg-primary text-white rounded-lg hover:bg-opacity-90 transition-colors shadow-sm disabled:opacity-50 font-medium"
                    disabled={isSimulating}
                >
                    <Play size={18} />
                    <span className="hidden sm:inline">Start Placing</span>
                    <span className="sm:hidden">Place</span>
                </button>

                <button
                    onClick={robotConnected ? stopRobot : onStop}
                    className="flex-1 flex items-center justify-center gap-2 py-3 px-4 bg-white border border-border rounded-lg hover:bg-gray-50 text-text-primary transition-colors shadow-sm font-medium"
                >
                    <Square size={18} />
                    Stop
                </button>
            </div>

            <button
                onClick={onClearAll}
                disabled={isSimulating || coneCount === 0}
                className="flex items-center justify-center gap-2 py-2 px-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed font-medium"
            >
                <Trash2 size={15} />
                Delete All Cones
            </button>

            {/* Robot Connection Section */}
            <div className="border-t border-border pt-3">
                <button
                    onClick={() => setShowConnect(!showConnect)}
                    className="w-full flex items-center justify-between text-sm font-semibold text-text-secondary uppercase tracking-wider mb-2"
                >
                    <span className="flex items-center gap-2">
                        <Bot size={14} />
                        TurtleBot
                    </span>
                    <span className={`w-2 h-2 rounded-full ${robotConnected ? 'bg-green-500' : 'bg-gray-300'}`} />
                </button>

                {showConnect && (
                    <div className="space-y-2">
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={urlInput}
                                onChange={(e) => setUrlInput(e.target.value)}
                                placeholder="http://localhost:8888"
                                className="flex-1 px-3 py-2 text-sm border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/30"
                                disabled={robotConnected}
                            />
                            {robotConnected ? (
                                <button
                                    onClick={disconnectRobot}
                                    className="px-3 py-2 bg-red-50 text-red-600 border border-red-200 rounded-lg text-sm font-medium hover:bg-red-100 transition-colors"
                                >
                                    <WifiOff size={16} />
                                </button>
                            ) : (
                                <button
                                    onClick={handleConnect}
                                    disabled={isConnecting}
                                    className="px-3 py-2 bg-green-50 text-green-600 border border-green-200 rounded-lg text-sm font-medium hover:bg-green-100 transition-colors disabled:opacity-50"
                                >
                                    {isConnecting ? '...' : <Wifi size={16} />}
                                </button>
                            )}
                        </div>

                        {robotConnected && (
                            <button
                                onClick={sendWaypointsToRobot}
                                disabled={isSimulating || optimizedPath.length === 0}
                                className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors text-sm font-medium disabled:opacity-50"
                            >
                                <Bot size={16} />
                                Send to Robot
                            </button>
                        )}

                        {/* WASD Manual Controls */}
                        <div className={`mt-2 p-3 bg-gray-50 rounded-lg border border-border transition-opacity ${!robotConnected ? 'opacity-40 pointer-events-none' : ''}`}>
                            <div className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2 text-center">
                                Manual Drive (WASD)
                            </div>
                            <div className="flex flex-col items-center gap-1">
                                <div>
                                    <kbd className={`inline-flex items-center justify-center w-9 h-9 rounded text-sm font-bold border-2 transition-colors ${
                                        activeKeys.has('w')
                                            ? 'bg-primary text-white border-primary'
                                            : 'bg-white text-text-primary border-gray-300'
                                    }`}>W</kbd>
                                </div>
                                <div className="flex gap-1">
                                    <kbd className={`inline-flex items-center justify-center w-9 h-9 rounded text-sm font-bold border-2 transition-colors ${
                                        activeKeys.has('a')
                                            ? 'bg-primary text-white border-primary'
                                            : 'bg-white text-text-primary border-gray-300'
                                    }`}>A</kbd>
                                    <kbd className={`inline-flex items-center justify-center w-9 h-9 rounded text-sm font-bold border-2 transition-colors ${
                                        activeKeys.has('s')
                                            ? 'bg-primary text-white border-primary'
                                            : 'bg-white text-text-primary border-gray-300'
                                    }`}>S</kbd>
                                    <kbd className={`inline-flex items-center justify-center w-9 h-9 rounded text-sm font-bold border-2 transition-colors ${
                                        activeKeys.has('d')
                                            ? 'bg-primary text-white border-primary'
                                            : 'bg-white text-text-primary border-gray-300'
                                    }`}>D</kbd>
                                </div>
                            </div>
                            <div className="text-[10px] text-text-secondary text-center mt-1.5">
                                {robotConnected
                                    ? <>W/S = forward/back &middot; A/D = turn left/right</>
                                    : 'Connect to enable manual drive'
                                }
                            </div>
                        </div>

                        <div className="text-xs text-text-secondary">
                            {robotConnected ? (
                                <span className="text-green-600">Connected to rosbridge</span>
                            ) : (
                                <span>Enter rosbridge WebSocket URL</span>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
