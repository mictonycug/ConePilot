import React from 'react';
import { Play, Square } from 'lucide-react';
import { useSessionStore } from '../../store/useSessionStore';
import { calculateOptimalPath } from '../../services/tsp';

export const ControlPanel: React.FC = () => {
    const { currentSession, setOptimizedPath, setIsSimulating, isSimulating, simulationStats, resetSimulationStats } = useSessionStore();

    if (!currentSession) return null;

    const handleStartPlacing = () => {
        // Calculate Path
        const points = currentSession.cones.map(c => ({ id: c.id, x: c.x, y: c.y }));
        // Add start path (0,0)
        const path = calculateOptimalPath(points, { id: 'start', x: 0, y: 0 });

        // Convert to simple points for store
        const simplePath = [{ x: 0, y: 0 }, ...path.map(p => ({ x: p.x, y: p.y }))];
        setOptimizedPath(simplePath);

        // Start Simulation
        resetSimulationStats();
        setIsSimulating(true);
    };

    const handleStop = () => {
        setIsSimulating(false);
    };

    return (
        <div className="w-80 bg-white border-l border-border p-6 flex flex-col gap-6 font-sans">
            <div>
                <h2 className="text-lg font-bold text-text-primary mb-1">Controls</h2>
                <div className="flex items-center gap-2 text-sm text-text-secondary">
                    <span className={`w-2 h-2 rounded-full ${isSimulating ? 'bg-green-500 animate-pulse' : 'bg-orange-500'}`}></span>
                    {isSimulating ? 'PLACING CONES' : currentSession.status}
                </div>
            </div>

            <div className="space-y-3">
                <button
                    onClick={handleStartPlacing}
                    className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-primary text-white rounded-lg hover:bg-opacity-90 transition-colors shadow-sm disabled:opacity-50"
                    disabled={isSimulating}
                >
                    <Play size={18} />
                    Start Placing
                </button>


                <button
                    onClick={handleStop}
                    className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-white border border-border rounded-lg hover:bg-gray-50 text-text-primary transition-colors"
                >
                    <Square size={18} />
                    Stop
                </button>
            </div>

            <div className="pt-6 border-t border-border">
                <h3 className="text-sm font-semibold text-text-secondary mb-3 uppercase tracking-wider">Stats</h3>
                <div className="grid grid-cols-2 gap-4">
                    <div className="bg-gray-50 p-3 rounded-lg">
                        <div className="text-2xl font-bold text-text-primary">{simulationStats.conesPlaced} / {currentSession.cones.length}</div>
                        <div className="text-xs text-text-secondary">Cones Placed</div>
                    </div>
                    <div className="bg-gray-50 p-3 rounded-lg">
                        <div className="text-2xl font-bold text-text-primary">{simulationStats.distanceTraveled.toFixed(1)}m</div>
                        <div className="text-xs text-text-secondary">Distance</div>
                    </div>
                    {isSimulating && (
                        <div className="bg-gray-50 p-3 rounded-lg col-span-2">
                            <div className="text-2xl font-bold text-text-primary">{simulationStats.etaSeconds}s</div>
                            <div className="text-xs text-text-secondary">Est. Time Remaining</div>
                        </div>
                    )}
                </div>
            </div>

            {/* Placement History */}
            <div className="flex-1 min-h-0 flex flex-col border-t border-border pt-6">
                <h3 className="text-sm font-semibold text-text-secondary mb-3 uppercase tracking-wider">Placement History</h3>
                <div className="flex-1 overflow-auto space-y-2 pr-2">
                    {useSessionStore.getState().placementHistory.map((entry, idx) => (
                        <HistoryItem key={idx} entry={entry} />
                    ))}
                    {useSessionStore.getState().placementHistory.length === 0 && (
                        <div className="text-gray-400 text-xs italic text-center py-4">No history yet</div>
                    )}
                </div>
            </div>
        </div>
    );
};

// Sub-component for individual history items to manage open state efficiently
const HistoryItem: React.FC<{ entry: { coneIndex: number; totalTime: number; logs: { step: string; timeTaken: number }[] } }> = ({ entry }) => {
    const [isOpen, setIsOpen] = React.useState(false);

    return (
        <div className="bg-gray-50 border border-gray-100 rounded text-xs overflow-hidden">
            <div
                className="flex justify-between items-center p-2 cursor-pointer hover:bg-gray-100 transition-colors select-none"
                onClick={() => setIsOpen(!isOpen)}
            >
                <div className="flex items-center gap-2">
                    <span className={`transform transition-transform ${isOpen ? 'rotate-90' : ''} text-gray-400 text-[10px]`}>▶</span>
                    <span className="font-semibold text-gray-700">Cone #{entry.coneIndex}</span>
                </div>
                <span className="font-semibold text-gray-700">{entry.totalTime.toFixed(1)}s</span>
            </div>

            {isOpen && (
                <div className="px-2 pb-2 mt-1 space-y-0.5 border-t border-gray-100 pt-1 bg-white">
                    {entry.logs.map((log, lIdx) => (
                        <div key={lIdx} className="flex justify-between text-gray-500 font-mono text-[10px]">
                            <span>{log.step.split('_')[0]}...</span>
                            <span>{log.timeTaken.toFixed(1)}s</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
