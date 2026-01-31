import React from 'react';
import { useSessionStore } from '../../store/useSessionStore';
import { Activity, Zap } from 'lucide-react';

export const SimulationOverlay: React.FC = () => {
    const { simulationStatus, robotTelemetry, currentSequenceLogs, simulationStats } = useSessionStore();

    // Only show during PLACING
    if (simulationStatus !== 'PLACING') return null;

    return (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]">
            <div className="bg-[#0F172A] border border-gray-700 rounded-lg shadow-2xl w-[500px] overflow-hidden flex flex-col font-mono text-green-400">
                {/* Header */}
                <div className="bg-gray-900 px-4 py-2 border-b border-gray-800 flex justify-between items-center">
                    <span className="font-bold flex items-center gap-2">
                        <Activity size={16} className="text-green-500 animate-pulse" />
                        SYSTEM_ACTIVE :: CONE_PLACEMENT_SEQUENCE
                    </span>
                    <span className="text-xs text-gray-500">PID: 8732</span>
                </div>

                {/* Gauges */}
                <div className="p-4 grid grid-cols-2 gap-4 border-b border-gray-800 bg-[#0B1120]">
                    <div className="bg-gray-900/50 p-3 rounded border border-gray-800">
                        <div className="text-xs text-gray-400 mb-1 flex items-center gap-1">
                            <Zap size={12} /> DRIVE_VELOCITY
                        </div>
                        <div className="text-xl font-bold">{robotTelemetry.velocity.toFixed(2)} m/s</div>
                        <div className="w-full h-1 bg-gray-800 mt-2 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-blue-500 transition-all duration-100"
                                style={{ width: `${Math.min(100, (robotTelemetry.velocity / 2) * 100)}%` }}
                            />
                        </div>
                    </div>
                    <div className="bg-gray-900/50 p-3 rounded border border-gray-800">
                        <div className="text-xs text-gray-400 mb-1 flex items-center gap-1">
                            <Zap size={12} /> MECH_VELOCITY
                        </div>
                        <div className="text-xl font-bold">{robotTelemetry.mechanismVelocity.toFixed(2)} m/s</div>
                        <div className="w-full h-1 bg-gray-800 mt-2 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-orange-500 transition-all duration-100"
                                style={{ width: `${Math.min(100, (robotTelemetry.mechanismVelocity / 1) * 100)}%` }}
                            />
                        </div>
                    </div>
                </div>

                {/* Terminal Logs */}
                <div className="p-4 h-64 overflow-y-auto bg-black font-mono text-sm space-y-2">
                    {currentSequenceLogs.map((log, i) => (
                        <div key={i} className="flex justify-between items-start border-b border-gray-900/50 pb-1 last:border-0 last:pb-0 fade-in">
                            <span className="text-green-400 pointer-events-none select-none text-opacity-80">
                                {'>'} {log.step}
                            </span>
                            <span className="text-gray-500 text-xs font-semibold">
                                {log.timeTaken.toFixed(1)}s
                            </span>
                        </div>
                    ))}
                    {currentSequenceLogs.length === 0 && (
                        <div className="text-gray-700 italic text-center py-10">Initializing sequence...</div>
                    )}
                </div>

                {/* Footer */}
                <div className="bg-gray-900 px-4 py-2 border-t border-gray-800 text-xs text-gray-500 flex justify-between">
                    <span>CONES PLACED: {simulationStats.conesPlaced}</span>
                    <span>STATUS: {simulationStatus}</span>
                </div>
            </div>
        </div>
    );
};
