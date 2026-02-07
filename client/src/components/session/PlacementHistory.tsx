
import React from 'react';

interface HistoryEntry {
    coneIndex: number;
    totalTime: number;
    logs: { step: string; timeTaken: number }[];
}

interface PlacementHistoryProps {
    history: HistoryEntry[];
}

export const PlacementHistory: React.FC<PlacementHistoryProps> = ({ history }) => {
    return (
        <div className="h-full flex flex-col">
            <h3 className="font-bold text-black mb-1">Placement History</h3>
            {history.length === 0 ? (
                <div className="text-gray-800 text-sm">No history yet.</div>
            ) : (
                <div className="flex-1 overflow-auto space-y-2">
                    {history.map((entry, idx) => (
                        <div key={idx} className="text-sm">
                            <span className="font-medium">Cone #{entry.coneIndex}</span> - {entry.totalTime.toFixed(1)}s
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
