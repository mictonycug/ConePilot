import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Play, Square, Trash2, Wifi, WifiOff, Bot, Target, Clock, CheckCircle2, Info, Eye, Camera, CameraOff, Crosshair } from 'lucide-react';
import { useSessionStore } from '../../store/useSessionStore';
import { rosBridge } from '../../services/rosbridge';

interface SessionControlsProps {
    onClearAll: () => void;
    coneCount: number;
}

export const SessionControls: React.FC<SessionControlsProps> = ({ onClearAll, coneCount }) => {
    const {
        robotConnected,
        robotUrl,
        isConnecting,
        connectToRobot,
        disconnectRobot,
        stopRobot,
        currentSession,
        missionActive,
        missionConeIds,
        missionDwellTime,
        missionWaypointIndex,
        missionWaypointTotal,
        missionWaypointState,
        missionDwellRemaining,
        setMissionDwellTime,
        startMission,
        stopMission,
        clearMissionSelection,
        selectAllConesForMission,
        coneChaseActive,
        coneChaseState,
        coneChaseReached,
        coneChaseMax,
        startConeChase,
        stopConeChase,
        setConeChaseMax,
        lockOnActive,
        lockOnLocked,
        lockOnDistance,
        lockOnBearing,
        startLockOn,
        stopLockOn,
    } = useSessionStore();

    const [urlInput, setUrlInput] = useState(robotUrl);
    const [showConnect, setShowConnect] = useState(false);
    const [showCamera, setShowCamera] = useState(false);

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
            if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return;

            if (!robotConnected) return;
            if (useSessionStore.getState().coneChaseActive) return;
            if (useSessionStore.getState().lockOnActive) return;

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
            rosBridge.sendVelocity(0, 0);
        };
    }, [robotConnected, computeAndSend]);

    const handleConnect = async () => {
        await connectToRobot(urlInput);
    };

    return (
        <div className="flex flex-col gap-3 w-full">
            {/* Instructions */}
            <div className="p-2.5 bg-blue-50 border border-blue-200 rounded-lg">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-700 mb-1.5">
                    <Info size={12} />
                    How to use
                </div>
                <ul className="text-[11px] text-blue-600 space-y-0.5 leading-relaxed">
                    <li><span className="font-medium">Click</span> canvas to place a cone</li>
                    <li><span className="font-medium">Click</span> a cone to delete it</li>
                    <li><span className="font-medium">Drag</span> a cone to reposition</li>
                    <li>When connected: <span className="font-medium">click</span> cones to select for mission</li>
                </ul>
            </div>

            <button
                onClick={onClearAll}
                disabled={coneCount === 0}
                className="flex items-center justify-center gap-2 py-2 px-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed font-medium"
            >
                <Trash2 size={15} />
                Delete All Cones ({coneCount})
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

                        {/* Mission Panel */}
                        {robotConnected && (
                            <div className="mt-1 p-3 bg-gray-50 rounded-lg border border-border space-y-2.5">
                                <div className="text-xs font-semibold text-text-secondary uppercase tracking-wider text-center flex items-center justify-center gap-1.5">
                                    <Target size={12} />
                                    Mission
                                </div>

                                {/* Selection summary */}
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-text-secondary">
                                        <span className="font-semibold text-text-primary">{missionConeIds.size}</span> of {currentSession?.cones.length ?? 0} cones selected
                                    </span>
                                    <div className="flex gap-1.5">
                                        <button
                                            onClick={selectAllConesForMission}
                                            disabled={missionActive}
                                            className="text-[10px] px-1.5 py-0.5 bg-white border border-gray-300 rounded hover:bg-gray-100 transition-colors disabled:opacity-40 font-medium"
                                        >
                                            All
                                        </button>
                                        <button
                                            onClick={clearMissionSelection}
                                            disabled={missionActive}
                                            className="text-[10px] px-1.5 py-0.5 bg-white border border-gray-300 rounded hover:bg-gray-100 transition-colors disabled:opacity-40 font-medium"
                                        >
                                            Clear
                                        </button>
                                    </div>
                                </div>

                                {/* Dwell time input */}
                                <div className="flex items-center gap-2">
                                    <Clock size={12} className="text-text-secondary flex-shrink-0" />
                                    <label className="text-xs text-text-secondary whitespace-nowrap">Dwell</label>
                                    <input
                                        type="number"
                                        min="0"
                                        max="60"
                                        step="0.5"
                                        value={missionDwellTime}
                                        onChange={(e) => setMissionDwellTime(parseFloat(e.target.value) || 0)}
                                        disabled={missionActive}
                                        className="w-16 px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-primary/40 text-center disabled:opacity-50"
                                    />
                                    <span className="text-xs text-text-secondary">sec</span>
                                </div>

                                {/* Start / Stop Mission */}
                                {!missionActive ? (
                                    <button
                                        onClick={startMission}
                                        disabled={missionConeIds.size === 0 || coneChaseActive || lockOnActive}
                                        className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-primary text-white rounded-lg hover:bg-opacity-90 transition-colors text-sm font-medium disabled:opacity-40"
                                    >
                                        <Play size={14} />
                                        Start Mission ({missionConeIds.size} waypoints)
                                    </button>
                                ) : (
                                    <div className="space-y-2">
                                        {/* Progress display */}
                                        <div className="bg-white rounded-md border border-gray-200 p-2">
                                            <div className="flex items-center justify-between text-xs mb-1.5">
                                                <span className="font-medium text-text-primary">
                                                    {missionWaypointState === 'calibrating' && (
                                                        <>Calibrating UWB heading...</>
                                                    )}
                                                    {missionWaypointState === 'navigating' && (
                                                        <>Navigating to {missionWaypointIndex + 1}/{missionWaypointTotal}</>
                                                    )}
                                                    {missionWaypointState === 'dwelling' && (
                                                        <>Dwelling at {missionWaypointIndex + 1}/{missionWaypointTotal} ({missionDwellRemaining}s)</>
                                                    )}
                                                    {missionWaypointState === 'completed' && (
                                                        <span className="flex items-center gap-1 text-green-600">
                                                            <CheckCircle2 size={12} /> Mission Complete
                                                        </span>
                                                    )}
                                                    {missionWaypointState === 'idle' && 'Starting...'}
                                                </span>
                                            </div>
                                            {/* Progress bar */}
                                            {missionWaypointTotal > 0 && (
                                                <div className="w-full bg-gray-200 rounded-full h-1.5">
                                                    <div
                                                        className="bg-primary h-1.5 rounded-full transition-all duration-300"
                                                        style={{
                                                            width: `${Math.min(100, ((missionWaypointIndex + (missionWaypointState === 'dwelling' ? 0.5 : 0)) / missionWaypointTotal) * 100)}%`
                                                        }}
                                                    />
                                                </div>
                                            )}
                                        </div>

                                        <button
                                            onClick={stopMission}
                                            className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 transition-colors text-sm font-medium"
                                        >
                                            <Square size={14} />
                                            Stop Mission
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Cone Chase Panel */}
                        {robotConnected && (
                            <div className="mt-1 p-3 bg-gray-50 rounded-lg border border-border space-y-2.5">
                                <div className="text-xs font-semibold text-text-secondary uppercase tracking-wider text-center flex items-center justify-center gap-1.5">
                                    <Eye size={12} />
                                    Cone Chase (Camera)
                                </div>

                                {!coneChaseActive ? (
                                    <>
                                        <div className="flex items-center gap-2">
                                            <label className="text-xs text-text-secondary whitespace-nowrap">Max cones</label>
                                            <input
                                                type="number"
                                                min="0"
                                                max="100"
                                                step="1"
                                                value={coneChaseMax}
                                                onChange={(e) => setConeChaseMax(parseInt(e.target.value) || 0)}
                                                className="w-16 px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-primary/40 text-center"
                                            />
                                            <span className="text-[10px] text-text-secondary">0 = unlimited</span>
                                        </div>
                                        <button
                                            onClick={() => startConeChase()}
                                            disabled={missionActive || lockOnActive}
                                            className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors text-sm font-medium disabled:opacity-40"
                                        >
                                            <Play size={14} />
                                            Start Cone Chase
                                        </button>
                                    </>
                                ) : (
                                    <div className="space-y-2">
                                        <div className="bg-white rounded-md border border-gray-200 p-2">
                                            <div className="flex items-center justify-between text-xs">
                                                <span className="font-medium text-text-primary">
                                                    {coneChaseState ?? 'Starting...'}
                                                </span>
                                                <span className="text-text-secondary">
                                                    Reached: <span className="font-semibold text-text-primary">{coneChaseReached}</span>
                                                    {coneChaseMax > 0 ? ` / ${coneChaseMax}` : ''}
                                                </span>
                                            </div>
                                        </div>
                                        <button
                                            onClick={stopConeChase}
                                            className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 transition-colors text-sm font-medium"
                                        >
                                            <Square size={14} />
                                            Stop Cone Chase
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Lock-On Mode Panel */}
                        {robotConnected && (
                            <div className="mt-1 p-3 bg-gray-50 rounded-lg border border-border space-y-2.5">
                                <div className="text-xs font-semibold text-text-secondary uppercase tracking-wider text-center flex items-center justify-center gap-1.5">
                                    <Crosshair size={12} />
                                    Lock-On (Camera)
                                </div>

                                {!lockOnActive ? (
                                    <button
                                        onClick={startLockOn}
                                        disabled={missionActive || coneChaseActive}
                                        className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-purple-500 text-white rounded-lg hover:bg-purple-600 transition-colors text-sm font-medium disabled:opacity-40"
                                    >
                                        <Crosshair size={14} />
                                        Start Lock-On
                                    </button>
                                ) : (
                                    <div className="space-y-2">
                                        <div className="bg-white rounded-md border border-gray-200 p-2">
                                            <div className="flex items-center justify-between text-xs">
                                                <span className={`font-medium ${lockOnLocked ? 'text-green-600' : 'text-red-500'}`}>
                                                    {lockOnLocked ? 'LOCKED' : 'SEARCHING...'}
                                                </span>
                                                {lockOnLocked && lockOnDistance != null && (
                                                    <span className="text-text-secondary">
                                                        {lockOnDistance.toFixed(2)}m &middot; {lockOnBearing?.toFixed(0) ?? 0}&deg;
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                        <button
                                            onClick={stopLockOn}
                                            className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-red-50 text-red-600 border border-red-200 rounded-lg hover:bg-red-100 transition-colors text-sm font-medium"
                                        >
                                            <Square size={14} />
                                            Stop Lock-On
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Camera Feed */}
                        {robotConnected && (
                            <div className="mt-1 p-3 bg-gray-50 rounded-lg border border-border space-y-2">
                                <button
                                    onClick={() => setShowCamera(!showCamera)}
                                    disabled={coneChaseActive && !lockOnActive}
                                    className="w-full flex items-center justify-center gap-2 py-1.5 text-xs font-semibold text-text-secondary uppercase tracking-wider disabled:opacity-40"
                                >
                                    {showCamera ? <CameraOff size={12} /> : <Camera size={12} />}
                                    {showCamera ? 'Hide Camera' : 'Show Camera'}
                                </button>
                                {showCamera && !coneChaseActive && (
                                    <img
                                        src={`${robotUrl}/camera`}
                                        alt="Robot camera feed"
                                        className="w-full rounded border border-gray-200"
                                        style={{ aspectRatio: '4/3', objectFit: 'cover', background: '#000' }}
                                    />
                                )}
                                {showCamera && coneChaseActive && !lockOnActive && (
                                    <div className="text-[10px] text-text-secondary text-center py-4">
                                        Camera in use by cone chase
                                    </div>
                                )}
                            </div>
                        )}

                        {/* WASD Manual Controls */}
                        <div className={`mt-2 p-3 bg-gray-50 rounded-lg border border-border transition-opacity ${!robotConnected || coneChaseActive || lockOnActive ? 'opacity-40 pointer-events-none' : ''}`}>
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
