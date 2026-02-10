import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useSessionStore } from '../store/useSessionStore';
import { FieldCanvas } from '../components/session/FieldCanvas';
import { SimulationOverlay } from '../components/session/SimulationOverlay';
import { SessionControls } from '../components/session/SessionControls';
import { SessionStats } from '../components/session/SessionStats';
import { PlacementHistory } from '../components/session/PlacementHistory';
import { calculateOptimalPath } from '../services/tsp';

export const SessionView: React.FC = () => {
    const { id } = useParams<{ id: string }>();
    const {
        loadSessionById,
        currentSession,
        isLoading,
        setOptimizedPath,
        setIsSimulating,
        isSimulating,
        simulationStats,
        resetSimulationStats,
        placementHistory,
        removeAllCones
    } = useSessionStore();

    useEffect(() => {
        if (id) {
            loadSessionById(id);
        }
    }, [id, loadSessionById]);

    if (isLoading || !currentSession) {
        return (
            <div className="flex-1 flex items-center justify-center bg-background">
                <div className="animate-pulse text-primary">Loading Session...</div>
            </div>
        );
    }

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
        <div className="flex-1 bg-background flex flex-col min-h-0">
            {/* Session Name - Mobile */}
            <div className="lg:hidden text-center py-2 bg-white border-b border-border flex-shrink-0">
                <h1 className="text-base font-semibold text-text-primary">{currentSession.name}</h1>
            </div>

            {/* Main Content */}
            <div className="flex-1 flex flex-col lg:flex-row overflow-hidden min-h-0">
                {/* Canvas Area */}
                <div className="relative bg-background overflow-hidden flex-shrink-0 h-[50vh] lg:flex-1 lg:h-auto p-4 lg:p-6 flex flex-col">
                    <SimulationOverlay />
                    <div className="flex-1 min-h-0">
                        <FieldCanvas width={800} height={600} />
                    </div>
                </div>

                {/* Controls Panel - Desktop Sidebar / Mobile Bottom */}
                <div className="lg:w-80 bg-white border-t lg:border-t-0 lg:border-l border-border p-4 lg:p-6 flex flex-col gap-4 lg:gap-6 flex-shrink-0">
                    {/* Desktop Session Name */}
                    <div className="hidden lg:block">
                        <h2 className="text-xl font-bold text-text-primary mb-1">{currentSession.name}</h2>
                        <div className="flex items-center gap-2 text-sm text-text-secondary">
                            <span className={`w-2 h-2 rounded-full ${isSimulating ? 'bg-green-500 animate-pulse' : 'bg-orange-500'}`}></span>
                            {isSimulating ? 'PLACING CONES' : currentSession.status}
                        </div>
                    </div>

                    {/* Controls */}
                    <div>
                        <h3 className="text-sm font-semibold text-text-secondary mb-3 uppercase tracking-wider lg:block hidden">Controls</h3>
                        <SessionControls
                            onStart={handleStartPlacing}
                            onStop={handleStop}
                            onClearAll={() => {
                                if (window.confirm('Delete all cones?')) {
                                    removeAllCones(currentSession.id);
                                }
                            }}
                            isSimulating={isSimulating}
                            coneCount={currentSession.cones.length}
                        />
                    </div>

                    {/* Stats and History Grid - Mobile */}
                    <div className="grid grid-cols-2 gap-4 lg:hidden">
                        <div>
                            <PlacementHistory history={placementHistory} />
                        </div>
                        <div>
                            <SessionStats
                                stats={simulationStats}
                                totalCones={currentSession.cones.length}
                            />
                        </div>
                    </div>

                    {/* Stats - Desktop */}
                    <div className="hidden lg:block pt-6 border-t border-border">
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

                    {/* Placement History - Desktop */}
                    <div className="hidden lg:flex flex-1 min-h-0 flex-col border-t border-border pt-6">
                        <h3 className="text-sm font-semibold text-text-secondary mb-3 uppercase tracking-wider">Placement History</h3>
                        <div className="flex-1 overflow-auto space-y-2 pr-2">
                            {placementHistory.map((entry, idx) => (
                                <HistoryItem key={idx} entry={entry} />
                            ))}
                            {placementHistory.length === 0 && (
                                <div className="text-gray-400 text-xs italic text-center py-4">No history yet</div>
                            )}
                        </div>
                    </div>
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
