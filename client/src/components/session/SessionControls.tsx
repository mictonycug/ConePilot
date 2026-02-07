import React from 'react';
import { Play, Square } from 'lucide-react';

interface SessionControlsProps {
    onStart: () => void;
    onStop: () => void;
    isSimulating: boolean;
}

export const SessionControls: React.FC<SessionControlsProps> = ({ onStart, onStop, isSimulating }) => {
    return (
        <div className="flex gap-3 w-full">
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
    );
};
