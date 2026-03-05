import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Play, Square, Trash2, Wifi, WifiOff, Bot, Target, Clock, CheckCircle2, Eye, Camera, CameraOff, Crosshair, ChevronDown, Gamepad2, Navigation, Bug, ChevronRight, Wrench } from 'lucide-react';
import { useSessionStore } from '../../store/useSessionStore';
import { rosBridge } from '../../services/rosbridge';
import { calculateOptimalPath } from '../../services/tsp';

type Mode = 'setup' | 'manual' | 'mission' | 'chase' | 'lockon';

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
        isReadOnly,
        isSimulating,
        setIsSimulating,
        setOptimizedPath,
        resetSimulationStats,
        sendWaypointsToRobot,
        stopRobot,
        debugMode,
        setDebugMode,
        debugAdvanceWaypoint,
        startDebugSimulation,
        stopDebugSimulation,
    } = useSessionStore();

    const [urlInput, setUrlInput] = useState(robotUrl);
    const [mode, setMode] = useState<Mode>('setup');
    const [showCamera, setShowCamera] = useState(false);
    const [isStartingPlacement, setIsStartingPlacement] = useState(false);
    const [devToolsOpen, setDevToolsOpen] = useState(false);

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

    // Touch hold for mobile joystick buttons
    const touchInterval = useRef<ReturnType<typeof setInterval> | null>(null);
    const handleTouchStart = useCallback((key: string) => {
        if (!robotConnected || isReadOnly || coneChaseActive || lockOnActive) return;
        pressedKeys.current.add(key);
        setActiveKeys(new Set(pressedKeys.current));
        computeAndSend();
        // Continuous send while held
        touchInterval.current = setInterval(computeAndSend, 100);
    }, [robotConnected, isReadOnly, coneChaseActive, lockOnActive, computeAndSend]);

    const handleTouchEnd = useCallback((key: string) => {
        pressedKeys.current.delete(key);
        setActiveKeys(new Set(pressedKeys.current));
        if (touchInterval.current) {
            clearInterval(touchInterval.current);
            touchInterval.current = null;
        }
        computeAndSend();
    }, [computeAndSend]);

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            const key = e.key.toLowerCase();
            if (!['w', 'a', 's', 'd'].includes(key)) return;
            if (e.repeat) return;
            if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return;
            if (!robotConnected) return;
            if (useSessionStore.getState().isReadOnly) return;
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

    const handleStartPlacing = async () => {
        if (!currentSession || currentSession.cones.length === 0) return;
        setIsStartingPlacement(true);
        try {
            // Calculate TSP path
            const points = currentSession.cones.map(c => ({ id: c.id, x: c.x, y: c.y }));
            const path = calculateOptimalPath(points, { id: 'start', x: 0, y: 0 });
            const simplePath = [{ x: 0, y: 0 }, ...path.map(p => ({ x: p.x, y: p.y }))];
            setOptimizedPath(simplePath);
            resetSimulationStats();

            if (debugMode) {
                startDebugSimulation();
            } else {
                if (!robotConnected) {
                    await connectToRobot(urlInput);
                    const state = useSessionStore.getState();
                    if (!state.robotConnected || state.isReadOnly) return;
                }
                setIsSimulating(true);
                sendWaypointsToRobot();
            }
        } finally {
            setIsStartingPlacement(false);
        }
    };

    const handleStopPlacing = () => {
        if (debugMode) {
            stopDebugSimulation();
        } else {
            setIsSimulating(false);
            stopRobot();
        }
    };

    // Auto-switch mode when an autonomous mode activates
    useEffect(() => {
        if (coneChaseActive) setMode('chase');
        else if (lockOnActive) setMode('lockon');
        else if (missionActive) setMode('mission');
    }, [coneChaseActive, lockOnActive, missionActive]);

    const modes: { id: Mode; label: string; icon: React.ReactNode; connected?: boolean }[] = [
        { id: 'setup', label: 'Setup', icon: <Target size={16} /> },
        { id: 'manual', label: 'Drive', icon: <Gamepad2 size={16} />, connected: true },
        { id: 'mission', label: 'Mission', icon: <Navigation size={16} />, connected: true },
        { id: 'chase', label: 'Chase', icon: <Eye size={16} />, connected: true },
        { id: 'lockon', label: 'Lock-On', icon: <Crosshair size={16} />, connected: true },
    ];

    const visibleModes = modes.filter(m => !m.connected || robotConnected);

    const isAnyAutoMode = coneChaseActive || lockOnActive || missionActive;

    return (
        <div className="flex flex-col gap-3 w-full">
            {/* Read-only banner */}
            {isReadOnly && robotConnected && !debugMode && (
                <div className="p-3 bg-amber-50 border border-amber-300 rounded-xl">
                    <div className="flex items-center gap-2 text-sm font-semibold text-amber-700">
                        <Eye size={16} />
                        View Only
                    </div>
                    <p className="text-xs text-amber-600 mt-1 leading-relaxed">
                        Another user is controlling this robot.
                    </p>
                </div>
            )}

            {/* ═══ PRIMARY CONTROLS (always visible) ═══ */}
            {/* Instructions */}
            <div className="p-3.5 bg-blue-50 border border-blue-200 rounded-xl">
                <ul className="text-sm text-blue-700 space-y-1.5 leading-relaxed">
                    <li><span className="font-semibold">Tap</span> canvas to place a cone</li>
                    <li><span className="font-semibold">Tap</span> a cone to delete it</li>
                    <li><span className="font-semibold">Drag</span> a cone to reposition</li>
                </ul>
            </div>

            {/* Cone count + clear */}
            <div className="flex items-center justify-between p-3.5 bg-gray-50 rounded-xl border border-border">
                <div>
                    <div className="text-2xl font-bold text-text-primary">{coneCount}</div>
                    <div className="text-xs text-text-secondary">cones placed</div>
                </div>
                <button
                    onClick={onClearAll}
                    disabled={coneCount === 0}
                    className="h-12 px-5 flex items-center gap-2 text-sm font-semibold text-red-600 bg-red-50 border border-red-200 rounded-xl hover:bg-red-100 active:bg-red-200 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                    <Trash2 size={18} />
                    Clear All
                </button>
            </div>

            {/* Start / Stop Placing */}
            {!isSimulating ? (
                <button
                    onClick={handleStartPlacing}
                    disabled={coneCount === 0 || isStartingPlacement || (!debugMode && isReadOnly)}
                    className="h-14 w-full flex items-center justify-center gap-3 bg-green-500 text-white rounded-xl hover:bg-green-600 active:bg-green-700 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                >
                    {isStartingPlacement ? (
                        <>
                            <span className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            {!robotConnected ? 'Connecting...' : 'Starting...'}
                        </>
                    ) : (
                        <>
                            <Play size={22} />
                            Start Placing
                        </>
                    )}
                </button>
            ) : (
                <div className="flex flex-col gap-2">
                    <button
                        onClick={handleStopPlacing}
                        disabled={!debugMode && isReadOnly}
                        className="h-14 w-full flex items-center justify-center gap-3 bg-red-500 text-white rounded-xl hover:bg-red-600 active:bg-red-700 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                    >
                        <Square size={22} />
                        Stop Placing
                    </button>
                    {debugMode && (
                        <button
                            onClick={debugAdvanceWaypoint}
                            className="h-12 w-full flex items-center justify-center gap-2 bg-blue-500 text-white rounded-xl hover:bg-blue-600 active:bg-blue-700 transition-colors text-sm font-bold shadow-sm"
                        >
                            <ChevronRight size={20} />
                            Next Waypoint
                        </button>
                    )}
                </div>
            )}

            {/* Spacer to push dev tools to bottom */}
            <div className="flex-1" />

            {/* ═══ DEV TOOLS (collapsible, at bottom) ═══ */}
            <div className="border border-border rounded-xl overflow-hidden">
                <button
                    onClick={() => setDevToolsOpen(!devToolsOpen)}
                    className="w-full flex items-center justify-between px-3.5 py-3 bg-gray-50 hover:bg-gray-100 active:bg-gray-200 transition-colors"
                >
                    <div className="flex items-center gap-2 text-sm font-semibold text-text-secondary">
                        <Wrench size={15} />
                        Dev Tools
                    </div>
                    <ChevronDown
                        size={16}
                        className={`text-text-secondary transition-transform ${devToolsOpen ? 'rotate-180' : ''}`}
                    />
                </button>

                {devToolsOpen && (
                    <div className="p-3 border-t border-border flex flex-col gap-3">
                        {/* Mode Tabs */}
                        <div className="flex gap-1.5 overflow-x-auto pb-0.5 -mx-1 px-1 scrollbar-none">
                            {visibleModes.map((m) => (
                                <button
                                    key={m.id}
                                    onClick={() => setMode(m.id)}
                                    className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all flex-shrink-0 ${
                                        mode === m.id
                                            ? 'bg-primary text-white shadow-sm'
                                            : 'bg-gray-100 text-text-secondary hover:bg-gray-200 active:bg-gray-300'
                                    }`}
                                >
                                    {m.icon}
                                    {m.label}
                                </button>
                            ))}
                        </div>

                        {/* Mode Content */}
                        <div>
                            {/* ═══ SETUP MODE ═══ */}
                            {mode === 'setup' && (
                                <div className="p-3 bg-gray-50 rounded-xl text-sm text-text-secondary text-center">
                                    Setup controls are shown above.
                                </div>
                            )}

                            {/* ═══ MANUAL DRIVE MODE ═══ */}
                            {mode === 'manual' && (
                                <div className="flex flex-col gap-3">
                                    {isAnyAutoMode && (
                                        <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700 font-medium text-center">
                                            Manual drive disabled — autonomous mode active
                                        </div>
                                    )}

                                    <div className={`transition-opacity ${isAnyAutoMode || isReadOnly ? 'opacity-40 pointer-events-none' : ''}`}>
                                        {/* D-pad style touch controls */}
                                        <div className="flex flex-col items-center gap-2 py-2">
                                            <DpadButton
                                                label="W"
                                                sublabel="FWD"
                                                active={activeKeys.has('w')}
                                                onTouchStart={() => handleTouchStart('w')}
                                                onTouchEnd={() => handleTouchEnd('w')}
                                            />
                                            <div className="flex gap-2">
                                                <DpadButton
                                                    label="A"
                                                    sublabel="LEFT"
                                                    active={activeKeys.has('a')}
                                                    onTouchStart={() => handleTouchStart('a')}
                                                    onTouchEnd={() => handleTouchEnd('a')}
                                                />
                                                <DpadButton
                                                    label="S"
                                                    sublabel="BACK"
                                                    active={activeKeys.has('s')}
                                                    onTouchStart={() => handleTouchStart('s')}
                                                    onTouchEnd={() => handleTouchEnd('s')}
                                                />
                                                <DpadButton
                                                    label="D"
                                                    sublabel="RIGHT"
                                                    active={activeKeys.has('d')}
                                                    onTouchStart={() => handleTouchStart('d')}
                                                    onTouchEnd={() => handleTouchEnd('d')}
                                                />
                                            </div>
                                        </div>
                                        <p className="text-xs text-text-secondary text-center mt-1">
                                            Hold buttons or use keyboard W/A/S/D
                                        </p>
                                    </div>

                                    {/* Camera toggle */}
                                    <CameraSection
                                        robotUrl={robotUrl}
                                        showCamera={showCamera}
                                        setShowCamera={setShowCamera}
                                        coneChaseActive={coneChaseActive}
                                        lockOnActive={lockOnActive}
                                    />
                                </div>
                            )}

                            {/* ═══ MISSION MODE ═══ */}
                            {mode === 'mission' && (
                                <div className="flex flex-col gap-3">
                                    {/* Selection summary */}
                                    <div className="p-3.5 bg-gray-50 rounded-xl border border-border">
                                        <div className="flex items-center justify-between mb-3">
                                            <div>
                                                <div className="text-2xl font-bold text-text-primary">{missionConeIds.size}</div>
                                                <div className="text-xs text-text-secondary">of {currentSession?.cones.length ?? 0} cones selected</div>
                                            </div>
                                            <div className="flex gap-2">
                                                <button
                                                    onClick={selectAllConesForMission}
                                                    disabled={missionActive || isReadOnly}
                                                    className="h-10 px-4 bg-white border border-gray-300 rounded-xl text-sm font-semibold hover:bg-gray-50 active:bg-gray-100 transition-colors disabled:opacity-30"
                                                >
                                                    Select All
                                                </button>
                                                <button
                                                    onClick={clearMissionSelection}
                                                    disabled={missionActive || isReadOnly}
                                                    className="h-10 px-4 bg-white border border-gray-300 rounded-xl text-sm font-semibold hover:bg-gray-50 active:bg-gray-100 transition-colors disabled:opacity-30"
                                                >
                                                    Clear
                                                </button>
                                            </div>
                                        </div>

                                        {/* Dwell time */}
                                        <div className="flex items-center gap-3">
                                            <Clock size={18} className="text-text-secondary flex-shrink-0" />
                                            <label className="text-sm text-text-secondary whitespace-nowrap">Dwell time</label>
                                            <input
                                                type="number"
                                                min="0"
                                                max="60"
                                                step="0.5"
                                                value={missionDwellTime}
                                                onChange={(e) => setMissionDwellTime(parseFloat(e.target.value) || 0)}
                                                disabled={missionActive || isReadOnly}
                                                className="w-20 px-3 py-2.5 text-sm border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 text-center disabled:opacity-50"
                                            />
                                            <span className="text-sm text-text-secondary">sec</span>
                                        </div>
                                    </div>

                                    {/* Mission action */}
                                    {!missionActive ? (
                                        <button
                                            onClick={startMission}
                                            disabled={missionConeIds.size === 0 || coneChaseActive || lockOnActive || isReadOnly}
                                            className="h-14 w-full flex items-center justify-center gap-3 bg-primary text-white rounded-xl hover:bg-opacity-90 active:bg-opacity-80 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                                        >
                                            <Play size={22} />
                                            Start Mission ({missionConeIds.size} waypoints)
                                        </button>
                                    ) : (
                                        <div className="flex flex-col gap-3">
                                            {/* Progress */}
                                            <div className="p-3.5 bg-white rounded-xl border border-gray-200">
                                                <div className="flex items-center justify-between text-sm mb-2">
                                                    <span className="font-semibold text-text-primary">
                                                        {missionWaypointState === 'calibrating' && 'Calibrating UWB heading...'}
                                                        {missionWaypointState === 'navigating' && `Navigating to ${missionWaypointIndex + 1}/${missionWaypointTotal}`}
                                                        {missionWaypointState === 'dwelling' && `Dwelling at ${missionWaypointIndex + 1}/${missionWaypointTotal} (${missionDwellRemaining}s)`}
                                                        {missionWaypointState === 'completed' && (
                                                            <span className="flex items-center gap-1.5 text-green-600">
                                                                <CheckCircle2 size={16} /> Mission Complete
                                                            </span>
                                                        )}
                                                        {missionWaypointState === 'idle' && 'Starting...'}
                                                    </span>
                                                </div>
                                                {missionWaypointTotal > 0 && (
                                                    <div className="w-full bg-gray-200 rounded-full h-2.5">
                                                        <div
                                                            className="bg-primary h-2.5 rounded-full transition-all duration-300"
                                                            style={{
                                                                width: `${Math.min(100, ((missionWaypointIndex + (missionWaypointState === 'dwelling' ? 0.5 : 0)) / missionWaypointTotal) * 100)}%`
                                                            }}
                                                        />
                                                    </div>
                                                )}
                                            </div>

                                            <button
                                                onClick={stopMission}
                                                disabled={isReadOnly}
                                                className="h-14 w-full flex items-center justify-center gap-3 bg-red-500 text-white rounded-xl hover:bg-red-600 active:bg-red-700 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                                            >
                                                <Square size={22} />
                                                Stop Mission
                                            </button>
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* ═══ CONE CHASE MODE ═══ */}
                            {mode === 'chase' && (
                                <div className="flex flex-col gap-3">
                                    <div className="p-3.5 bg-orange-50 border border-orange-200 rounded-xl">
                                        <p className="text-sm text-orange-700 leading-relaxed">
                                            Robot uses its camera to detect and drive toward cones autonomously.
                                        </p>
                                    </div>

                                    {!coneChaseActive ? (
                                        <>
                                            <div className="flex items-center gap-3 p-3.5 bg-gray-50 rounded-xl border border-border">
                                                <label className="text-sm text-text-secondary whitespace-nowrap font-medium">Max cones</label>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    max="100"
                                                    step="1"
                                                    value={coneChaseMax}
                                                    onChange={(e) => setConeChaseMax(parseInt(e.target.value) || 0)}
                                                    className="w-20 px-3 py-2.5 text-sm border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 text-center"
                                                />
                                                <span className="text-xs text-text-secondary">0 = unlimited</span>
                                            </div>

                                            <button
                                                onClick={() => startConeChase()}
                                                disabled={missionActive || lockOnActive || isReadOnly}
                                                className="h-14 w-full flex items-center justify-center gap-3 bg-orange-500 text-white rounded-xl hover:bg-orange-600 active:bg-orange-700 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                                            >
                                                <Eye size={22} />
                                                Start Cone Chase
                                            </button>
                                        </>
                                    ) : (
                                        <div className="flex flex-col gap-3">
                                            <div className="p-3.5 bg-white rounded-xl border border-gray-200">
                                                <div className="flex items-center justify-between text-sm">
                                                    <span className="font-semibold text-text-primary">
                                                        {coneChaseState ?? 'Starting...'}
                                                    </span>
                                                    <span className="text-text-secondary">
                                                        Reached: <span className="font-bold text-text-primary text-lg">{coneChaseReached}</span>
                                                        {coneChaseMax > 0 ? ` / ${coneChaseMax}` : ''}
                                                    </span>
                                                </div>
                                            </div>

                                            <button
                                                onClick={stopConeChase}
                                                disabled={isReadOnly}
                                                className="h-14 w-full flex items-center justify-center gap-3 bg-red-500 text-white rounded-xl hover:bg-red-600 active:bg-red-700 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                                            >
                                                <Square size={22} />
                                                Stop Cone Chase
                                            </button>
                                        </div>
                                    )}

                                    <CameraSection
                                        robotUrl={robotUrl}
                                        showCamera={showCamera}
                                        setShowCamera={setShowCamera}
                                        coneChaseActive={coneChaseActive}
                                        lockOnActive={lockOnActive}
                                    />
                                </div>
                            )}

                            {/* ═══ LOCK-ON MODE ═══ */}
                            {mode === 'lockon' && (
                                <div className="flex flex-col gap-3">
                                    <div className="p-3.5 bg-purple-50 border border-purple-200 rounded-xl">
                                        <p className="text-sm text-purple-700 leading-relaxed">
                                            Robot locks onto a single visible cone and tracks it continuously.
                                        </p>
                                    </div>

                                    {!lockOnActive ? (
                                        <button
                                            onClick={startLockOn}
                                            disabled={missionActive || coneChaseActive || isReadOnly}
                                            className="h-14 w-full flex items-center justify-center gap-3 bg-purple-500 text-white rounded-xl hover:bg-purple-600 active:bg-purple-700 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                                        >
                                            <Crosshair size={22} />
                                            Start Lock-On
                                        </button>
                                    ) : (
                                        <div className="flex flex-col gap-3">
                                            {/* Lock-on status */}
                                            <div className={`p-4 rounded-xl border-2 ${
                                                lockOnLocked
                                                    ? 'bg-green-50 border-green-300'
                                                    : 'bg-yellow-50 border-yellow-300 animate-pulse'
                                            }`}>
                                                <div className="flex items-center justify-between">
                                                    <div className="flex items-center gap-2">
                                                        <Crosshair size={22} className={lockOnLocked ? 'text-green-600' : 'text-yellow-600'} />
                                                        <span className={`text-lg font-bold ${lockOnLocked ? 'text-green-700' : 'text-yellow-700'}`}>
                                                            {lockOnLocked ? 'LOCKED' : 'SEARCHING...'}
                                                        </span>
                                                    </div>
                                                    {lockOnLocked && lockOnDistance != null && (
                                                        <div className="text-right">
                                                            <div className="text-lg font-bold text-text-primary">{lockOnDistance.toFixed(2)}m</div>
                                                            <div className="text-xs text-text-secondary">{lockOnBearing?.toFixed(0) ?? 0}&deg; bearing</div>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>

                                            <button
                                                onClick={stopLockOn}
                                                disabled={isReadOnly}
                                                className="h-14 w-full flex items-center justify-center gap-3 bg-red-500 text-white rounded-xl hover:bg-red-600 active:bg-red-700 transition-colors text-base font-bold disabled:opacity-30 shadow-sm"
                                            >
                                                <Square size={22} />
                                                Stop Lock-On
                                            </button>
                                        </div>
                                    )}

                                    <CameraSection
                                        robotUrl={robotUrl}
                                        showCamera={showCamera}
                                        setShowCamera={setShowCamera}
                                        coneChaseActive={coneChaseActive}
                                        lockOnActive={lockOnActive}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Robot Connection */}
            <div className="p-3 bg-gray-50 rounded-xl border border-border">
                {debugMode ? (
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-purple-100">
                            <Bug size={20} className="text-purple-600" />
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold text-text-primary">
                                Debug Mode
                            </div>
                            <div className="text-xs text-purple-600">
                                Simulated robot active
                            </div>
                        </div>
                        <span className="px-2.5 py-1 bg-purple-100 text-purple-700 rounded-lg text-xs font-semibold">
                            (Debug)
                        </span>
                    </div>
                ) : (
                    <>
                        <div className="flex items-center gap-3">
                            <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${
                                robotConnected ? 'bg-green-100' : 'bg-gray-200'
                            }`}>
                                <Bot size={20} className={robotConnected ? 'text-green-600' : 'text-gray-400'} />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="text-sm font-semibold text-text-primary">
                                    {robotConnected ? 'Connected' : 'ConePilot'}
                                </div>
                                <div className="text-xs text-text-secondary truncate">
                                    {robotConnected ? urlInput : 'Not connected'}
                                </div>
                            </div>
                            {robotConnected && (
                                <button
                                    onClick={disconnectRobot}
                                    className="h-11 px-4 bg-red-50 text-red-600 border border-red-200 rounded-xl text-sm font-semibold hover:bg-red-100 active:bg-red-200 transition-colors flex items-center gap-2"
                                >
                                    <WifiOff size={16} />
                                    <span className="hidden sm:inline">Disconnect</span>
                                </button>
                            )}
                        </div>
                        {!robotConnected && (
                            <div className="flex gap-2 mt-2">
                                <input
                                    type="text"
                                    value={urlInput}
                                    onChange={(e) => setUrlInput(e.target.value)}
                                    placeholder="http://..."
                                    className="flex-1 min-w-0 px-3 py-2.5 text-sm border border-border rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30"
                                />
                                <button
                                    onClick={handleConnect}
                                    disabled={isConnecting}
                                    className="h-11 px-4 bg-green-50 text-green-600 border border-green-200 rounded-xl text-sm font-semibold hover:bg-green-100 active:bg-green-200 transition-colors disabled:opacity-50 flex items-center gap-2 flex-shrink-0"
                                >
                                    {isConnecting ? '...' : <Wifi size={16} />}
                                </button>
                            </div>
                        )}
                    </>
                )}

                {/* Debug Mode Toggle */}
                <div className={`flex items-center justify-between mt-3 pt-3 border-t border-border ${robotConnected && !debugMode ? 'opacity-40 pointer-events-none' : ''}`}>
                    <div className="flex items-center gap-2 text-sm text-text-secondary">
                        <Bug size={16} />
                        Debug Mode
                    </div>
                    <button
                        onClick={() => setDebugMode(!debugMode)}
                        disabled={robotConnected && !debugMode}
                        className={`relative w-11 h-6 rounded-full transition-colors ${
                            debugMode ? 'bg-purple-500' : 'bg-gray-300'
                        }`}
                    >
                        <div className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                            debugMode ? 'translate-x-5' : 'translate-x-0'
                        }`} />
                    </button>
                </div>
            </div>
        </div>
    );
};

// ─── Reusable sub-components ────────────────────────────────────────────────

const DpadButton: React.FC<{
    label: string;
    sublabel: string;
    active: boolean;
    onTouchStart: () => void;
    onTouchEnd: () => void;
}> = ({ label, sublabel, active, onTouchStart, onTouchEnd }) => (
    <button
        onTouchStart={(e) => { e.preventDefault(); onTouchStart(); }}
        onTouchEnd={(e) => { e.preventDefault(); onTouchEnd(); }}
        onMouseDown={onTouchStart}
        onMouseUp={onTouchEnd}
        onMouseLeave={onTouchEnd}
        className={`w-20 h-20 rounded-2xl flex flex-col items-center justify-center gap-0.5 border-2 font-bold text-lg select-none transition-all active:scale-95 ${
            active
                ? 'bg-primary text-white border-primary shadow-lg scale-95'
                : 'bg-white text-text-primary border-gray-300 shadow-sm hover:bg-gray-50'
        }`}
    >
        <span>{label}</span>
        <span className={`text-[10px] font-medium ${active ? 'text-white/70' : 'text-text-secondary'}`}>{sublabel}</span>
    </button>
);

const CameraSection: React.FC<{
    robotUrl: string;
    showCamera: boolean;
    setShowCamera: (v: boolean) => void;
    coneChaseActive: boolean;
    lockOnActive: boolean;
}> = ({ robotUrl, showCamera, setShowCamera, coneChaseActive, lockOnActive }) => (
    <div className="p-3.5 bg-gray-50 rounded-xl border border-border">
        <button
            onClick={() => setShowCamera(!showCamera)}
            className="w-full h-11 flex items-center justify-center gap-2 text-sm font-semibold text-text-secondary hover:text-text-primary transition-colors rounded-lg"
        >
            {showCamera ? <CameraOff size={18} /> : <Camera size={18} />}
            {showCamera ? 'Hide Camera' : 'Show Camera'}
        </button>
        {showCamera && (
            <img
                src={`${robotUrl}/camera`}
                alt="Robot camera feed"
                className="w-full rounded-lg border border-gray-200 mt-2"
                style={{ aspectRatio: '4/3', objectFit: 'cover', background: '#000' }}
            />
        )}
    </div>
);
