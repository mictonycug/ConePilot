import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

const BEACONS = [
    { id: 'UWB-A1', x: 10, y: 10 },
    { id: 'UWB-A2', x: 90, y: 10 },
    { id: 'UWB-A3', x: 90, y: 90 },
    { id: 'UWB-A4', x: 10, y: 90 },
];

// Inject keyframes once
const style = document.createElement('style');
style.textContent = `
@keyframes radar-ping {
  0% { transform: translate(-50%, -50%) scale(0.5); opacity: 0.7; }
  100% { transform: translate(-50%, -50%) scale(3.5); opacity: 0; }
}
@keyframes sweep {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
  50% { opacity: 0.5; transform: translate(-50%, -50%) scale(1.4); }
}
@keyframes fadeInUp {
  0% { opacity: 0; transform: translateY(16px); }
  100% { opacity: 1; transform: translateY(0); }
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
`;
if (!document.head.querySelector('[data-onboarding-styles]')) {
    style.setAttribute('data-onboarding-styles', '');
    document.head.appendChild(style);
}

type Phase =
    | 'welcome'
    | 'searching'
    | 'found'
    | 'calibrating'
    | 'calibrated'
    | 'locating-robot'
    | 'robot-found'
    | 'done';

const Spinner: React.FC<{ size?: number; color?: string }> = ({ size = 16, color = 'border-primary' }) => (
    <div
        className={`border-2 ${color} border-t-transparent rounded-full`}
        style={{ width: size, height: size, animation: 'sweep 0.8s linear infinite' }}
    />
);

export const OnboardingPage: React.FC = () => {
    const [phase, setPhase] = useState<Phase>('welcome');
    const [foundCount, setFoundCount] = useState(0);
    const [calibrationPct, setCalibrationPct] = useState(0);
    const [logLines, setLogLines] = useState<string[]>([]);
    const nav = useNavigate();

    const addLog = (line: string) => setLogLines((prev) => [...prev, line]);

    // Phase: searching → start finding beacons after sweep
    useEffect(() => {
        if (phase !== 'searching') return;
        addLog('> Scanning UWB frequency bands...');
        const t1 = setTimeout(() => addLog('> Listening on channel 5 (6489.6 MHz)...'), 1200);
        const t2 = setTimeout(() => {
            setFoundCount(1);
            setPhase('found');
        }, 2500);
        return () => { clearTimeout(t1); clearTimeout(t2); };
    }, [phase]);

    // Phase: found → discover beacons one by one
    useEffect(() => {
        if (phase !== 'found' || foundCount >= 4) return;
        const timer = setTimeout(() => setFoundCount((c) => c + 1), 1200);
        return () => clearTimeout(timer);
    }, [phase, foundCount]);

    // Log each beacon discovery
    useEffect(() => {
        if (phase !== 'found' || foundCount === 0) return;
        const b = BEACONS[foundCount - 1];
        addLog(`> Beacon ${b.id} responding (RSSI: -${(42 + foundCount * 3)}dBm)`);
    }, [foundCount, phase]);

    // After all 4 found → calibrating
    useEffect(() => {
        if (phase !== 'found' || foundCount < 4) return;
        const timer = setTimeout(() => {
            addLog('> All 4 anchors detected. Starting calibration...');
            setPhase('calibrating');
        }, 1500);
        return () => clearTimeout(timer);
    }, [phase, foundCount]);

    // Phase: calibrating → progress bar
    useEffect(() => {
        if (phase !== 'calibrating') return;
        const msgs = [
            { at: 15, msg: '> Measuring inter-anchor distances...' },
            { at: 40, msg: '> Computing coordinate frame...' },
            { at: 65, msg: '> Verifying geometry (3.5m x 3.0m)...' },
            { at: 90, msg: '> Applying position corrections...' },
        ];
        const interval = setInterval(() => {
            setCalibrationPct((p) => {
                const next = p + 2;
                const m = msgs.find((m) => m.at === next);
                if (m) addLog(m.msg);
                if (next >= 100) { clearInterval(interval); return 100; }
                return next;
            });
        }, 80);
        return () => clearInterval(interval);
    }, [phase]);

    // Calibration done → calibrated
    useEffect(() => {
        if (phase !== 'calibrating' || calibrationPct < 100) return;
        const timer = setTimeout(() => {
            addLog('> Calibration successful. Field locked.');
            setPhase('calibrated');
        }, 600);
        return () => clearTimeout(timer);
    }, [phase, calibrationPct]);

    // Calibrated → locate robot
    useEffect(() => {
        if (phase !== 'calibrated') return;
        const timer = setTimeout(() => {
            addLog('> Scanning for ConePilot robot...');
            setPhase('locating-robot');
        }, 2000);
        return () => clearTimeout(timer);
    }, [phase]);

    // Locating robot → found
    useEffect(() => {
        if (phase !== 'locating-robot') return;
        const t1 = setTimeout(() => addLog('> Pinging 192.168.4.1...'), 1000);
        const t2 = setTimeout(() => addLog('> TurtleBot3 responding on /odom'), 2200);
        const t3 = setTimeout(() => {
            addLog('> ConePilot connected. Firmware v2.4.1');
            setPhase('robot-found');
        }, 3500);
        return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
    }, [phase]);

    // Robot found → done
    useEffect(() => {
        if (phase !== 'robot-found') return;
        const timer = setTimeout(() => setPhase('done'), 1800);
        return () => clearTimeout(timer);
    }, [phase]);

    const handleFinish = () => {
        localStorage.setItem('conepilot_onboarding_done', 'true');
        nav('/dashboard');
    };

    // --- Welcome ---
    if (phase === 'welcome') {
        return (
            <div className="flex-1 flex flex-col items-center justify-center text-center px-4 bg-background">
                <div className="mb-6 w-20 h-20 rounded-2xl bg-white shadow-sm border border-border flex items-center justify-center">
                    <span className="text-4xl">🔶</span>
                </div>
                <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-3 text-text-primary">
                    Welcome to ConePilot
                </h1>
                <p className="text-lg text-text-secondary max-w-md mb-10 font-light">
                    Let's set up your field and connect to your robot.
                </p>
                <button
                    onClick={() => setPhase('searching')}
                    className="px-10 py-4 bg-primary text-white rounded-lg font-medium text-lg hover:bg-opacity-90 transition-all shadow-lg hover:shadow-xl"
                >
                    Begin Setup
                </button>
            </div>
        );
    }

    // --- All scanning phases ---
    const isSearching = phase === 'searching';
    const isCalibrating = phase === 'calibrating';
    const isCalibrated = phase === 'calibrated' || phase === 'locating-robot' || phase === 'robot-found' || phase === 'done';
    const isLocating = phase === 'locating-robot';
    const isRobotFound = phase === 'robot-found' || phase === 'done';
    const isDone = phase === 'done';
    const visibleBeacons = phase === 'searching' ? 0 : Math.min(foundCount, 4);
    const showField = isCalibrated;
    const beaconColor = isCalibrated ? 'bg-success' : 'bg-primary';
    const beaconTextColor = isCalibrated ? 'text-success' : 'text-primary';
    const beaconPingColor = isCalibrated ? 'bg-success/20' : 'bg-primary/20';

    return (
        <div className="flex-1 flex flex-col items-center justify-center px-4 py-8 bg-background">
            <div className="w-full max-w-lg">
                {/* Status header */}
                <div className="text-center mb-5" key={phase} style={{ animation: 'fadeInUp 0.4s ease-out' }}>
                    {isSearching && (
                        <div className="flex items-center justify-center gap-2">
                            <Spinner />
                            <span className="text-lg text-text-secondary font-medium">Searching for beacons...</span>
                        </div>
                    )}
                    {phase === 'found' && (
                        <div>
                            <span className="text-2xl font-bold text-text-primary">
                                Found {foundCount} beacon{foundCount !== 1 ? 's' : ''}
                            </span>
                            {foundCount < 4 && (
                                <div className="flex items-center justify-center gap-2 mt-1">
                                    <Spinner size={12} />
                                    <span className="text-sm text-text-secondary">scanning...</span>
                                </div>
                            )}
                            {foundCount >= 4 && (
                                <p className="text-sm text-success mt-1 font-medium">All anchors detected</p>
                            )}
                        </div>
                    )}
                    {isCalibrating && (
                        <div>
                            <div className="flex items-center justify-center gap-2">
                                <Spinner />
                                <span className="text-lg font-medium text-text-primary">Running calibration...</span>
                            </div>
                            <div className="mt-3 w-64 mx-auto h-2 bg-gray-200 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-primary rounded-full transition-all duration-100"
                                    style={{ width: `${calibrationPct}%` }}
                                />
                            </div>
                            <span className="text-xs text-text-secondary mt-1 block">{Math.min(calibrationPct, 100)}%</span>
                        </div>
                    )}
                    {phase === 'calibrated' && (
                        <div>
                            <span className="text-2xl font-bold text-success">Calibration Complete</span>
                            <p className="text-sm text-text-secondary mt-1">Field configured — 3.5m x 3.0m</p>
                        </div>
                    )}
                    {isLocating && (
                        <div className="flex items-center justify-center gap-2">
                            <Spinner color="border-primary" />
                            <span className="text-lg font-medium text-text-primary">Locating ConePilot...</span>
                        </div>
                    )}
                    {phase === 'robot-found' && (
                        <div>
                            <span className="text-2xl font-bold text-success">ConePilot Connected</span>
                            <p className="text-sm text-text-secondary mt-1">TurtleBot3 online — firmware v2.4.1</p>
                        </div>
                    )}
                    {isDone && (
                        <div>
                            <span className="text-2xl font-bold text-success">You're all set!</span>
                            <p className="text-sm text-text-secondary mt-1">Field and robot ready to go</p>
                        </div>
                    )}
                </div>

                {/* Field canvas */}
                <div className={`w-full aspect-[7/6] bg-white rounded-2xl border-2 relative overflow-hidden transition-colors duration-700 ${
                    showField ? 'border-success/40' : 'border-border'
                }`}>
                    {/* Grid */}
                    <svg className="absolute inset-0 w-full h-full opacity-[0.06]">
                        {[...Array(8)].map((_, i) => (
                            <React.Fragment key={i}>
                                <line x1={`${(i + 1) * 11.1}%`} y1="0" x2={`${(i + 1) * 11.1}%`} y2="100%" stroke="#1F1F1F" strokeWidth="1" />
                                <line x1="0" y1={`${(i + 1) * 12.5}%`} x2="100%" y2={`${(i + 1) * 12.5}%`} stroke="#1F1F1F" strokeWidth="1" />
                            </React.Fragment>
                        ))}
                    </svg>

                    {/* Scanning sweep */}
                    {isSearching && (
                        <div className="absolute inset-0 flex items-center justify-center">
                            <div
                                className="w-52 h-52 rounded-full"
                                style={{
                                    background: 'conic-gradient(from 0deg, transparent 0deg, rgba(217,119,6,0.15) 60deg, transparent 120deg)',
                                    animation: 'sweep 2.5s linear infinite',
                                }}
                            />
                        </div>
                    )}

                    {/* Field outline after calibration */}
                    {showField && (
                        <div
                            className="absolute border-2 border-success/30 rounded-lg bg-success/[0.03]"
                            style={{ left: '10%', top: '10%', right: '10%', bottom: '10%', animation: 'fadeInUp 0.6s ease-out' }}
                        >
                            <span className="absolute -bottom-6 left-1/2 -translate-x-1/2 text-[11px] text-text-secondary font-mono">3.5 m</span>
                            <span className="absolute -right-10 top-1/2 -translate-y-1/2 text-[11px] text-text-secondary font-mono rotate-90">3.0 m</span>
                        </div>
                    )}

                    {/* Beacon markers */}
                    {BEACONS.slice(0, visibleBeacons).map((beacon, i) => (
                        <div
                            key={beacon.id}
                            className="absolute"
                            style={{ left: `${beacon.x}%`, top: `${beacon.y}%`, animation: 'fadeInUp 0.4s ease-out' }}
                        >
                            {/* Ping rings */}
                            <div
                                className={`absolute w-6 h-6 rounded-full ${beaconPingColor}`}
                                style={{ left: '50%', top: '50%', animation: 'radar-ping 2.5s ease-out infinite', animationDelay: `${i * 0.6}s` }}
                            />
                            <div
                                className={`absolute w-6 h-6 rounded-full ${beaconPingColor}`}
                                style={{ left: '50%', top: '50%', animation: 'radar-ping 2.5s ease-out infinite', animationDelay: `${i * 0.6 + 1.25}s` }}
                            />
                            {/* Dot */}
                            <div
                                className={`absolute w-4 h-4 rounded-full shadow-lg -translate-x-1/2 -translate-y-1/2 flex items-center justify-center ${beaconColor}`}
                                style={{ left: '50%', top: '50%', animation: isCalibrated ? undefined : 'pulse-dot 2s ease-in-out infinite' }}
                            >
                                <span className="text-[7px] font-bold text-white">{i + 1}</span>
                            </div>
                            {/* Label */}
                            <span
                                className={`absolute text-[9px] font-mono font-medium whitespace-nowrap ${beaconTextColor}`}
                                style={{
                                    left: '50%', transform: 'translateX(-50%)',
                                    ...(beacon.y < 50 ? { top: '100%', marginTop: 8 } : { bottom: '100%', marginBottom: 8 }),
                                }}
                            >
                                {beacon.id}
                            </span>
                        </div>
                    ))}

                    {/* Connection lines */}
                    {visibleBeacons >= 2 && (
                        <svg className="absolute inset-0 w-full h-full pointer-events-none">
                            {BEACONS.slice(0, visibleBeacons).map((b, i) => {
                                const next = BEACONS[(i + 1) % 4];
                                if (i >= visibleBeacons - 1 && visibleBeacons < 4) return null;
                                return (
                                    <line key={i} x1={`${b.x}%`} y1={`${b.y}%`} x2={`${next.x}%`} y2={`${next.y}%`}
                                        stroke={isCalibrated ? '#10B981' : '#D97706'} strokeWidth="1.5"
                                        strokeDasharray={isCalibrated ? 'none' : '6 4'} opacity={isCalibrated ? 0.4 : 0.25}
                                    />
                                );
                            })}
                        </svg>
                    )}

                    {/* Robot icon (appears during locating phase) */}
                    {(isLocating || isRobotFound) && (
                        <div
                            className="absolute"
                            style={{ left: '50%', top: '50%', animation: 'fadeInUp 0.5s ease-out' }}
                        >
                            <div
                                className={`absolute -translate-x-1/2 -translate-y-1/2 w-10 h-10 rounded-full flex items-center justify-center shadow-lg ${
                                    isRobotFound ? 'bg-success' : 'bg-gray-400'
                                }`}
                                style={{ animation: isLocating ? 'blink 1.5s ease-in-out infinite' : undefined }}
                            >
                                <span className="text-lg">🤖</span>
                            </div>
                            <span
                                className={`absolute text-[9px] font-mono font-medium whitespace-nowrap left-1/2 -translate-x-1/2 ${
                                    isRobotFound ? 'text-success' : 'text-text-secondary'
                                }`}
                                style={{ top: '100%', marginTop: 24 }}
                            >
                                {isRobotFound ? 'ConePilot' : 'searching...'}
                            </span>
                        </div>
                    )}
                </div>

                {/* Console log */}
                <div className="mt-4 bg-gray-900 rounded-lg p-3 h-28 overflow-y-auto font-mono text-[11px] leading-relaxed">
                    {logLines.map((line, i) => (
                        <div key={i} className={`${i === logLines.length - 1 ? 'text-green-400' : 'text-gray-500'}`}>
                            {line}
                        </div>
                    ))}
                    {!isDone && (
                        <span className="text-green-400" style={{ animation: 'blink 1s step-end infinite' }}>_</span>
                    )}
                </div>

                {/* Action button */}
                <div className="flex justify-center mt-6">
                    {isDone && (
                        <button
                            onClick={handleFinish}
                            className="px-10 py-4 bg-primary text-white rounded-lg font-medium text-lg hover:bg-opacity-90 transition-all shadow-lg hover:shadow-xl"
                            style={{ animation: 'fadeInUp 0.5s ease-out' }}
                        >
                            Go to Dashboard
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};
