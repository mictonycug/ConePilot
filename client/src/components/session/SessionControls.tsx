import React from 'react';
import { Play, Square, Trash2 } from 'lucide-react';

interface SessionControlsProps {
    onStart: () => void;
    onStop: () => void;
    onClearAll: () => void;
    isSimulating: boolean;
    coneCount: number;
}

export const SessionControls: React.FC<SessionControlsProps> = ({ onStart, onStop, onClearAll, isSimulating, coneCount }) => {
    return (
        <div className="flex flex-col gap-2 w-full">
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
                    onClick={onStop}
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
        </div>
    );
};
