import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useSessionStore } from '../store/useSessionStore';
import { FieldCanvas } from '../components/session/FieldCanvas';
import { SessionControls } from '../components/session/SessionControls';

export const SessionView: React.FC = () => {
    const { id } = useParams<{ id: string }>();
    const {
        loadSessionById,
        currentSession,
        isLoading,
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
                <div className="animate-pulse text-primary text-lg">Loading Session...</div>
            </div>
        );
    }

    return (
        <div className="flex-1 bg-background flex flex-col min-h-0">
            {/* Session Header - Mobile */}
            <div className="lg:hidden flex items-center justify-between py-2 px-4 bg-white border-b border-border flex-shrink-0">
                <h1 className="text-base font-semibold text-text-primary truncate">{currentSession.name}</h1>
                <div className="flex items-center gap-1.5 text-xs text-text-secondary flex-shrink-0">
                    <span className="font-semibold text-text-primary">{currentSession.cones.length}</span> cones
                    <span className="text-gray-400 ml-1">{currentSession.fieldWidth}x{currentSession.fieldHeight}m</span>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 flex flex-col lg:flex-row overflow-hidden min-h-0">
                {/* Canvas Area — bigger on mobile (60vh) */}
                <div className="relative bg-background overflow-hidden flex-shrink-0 h-[55vh] lg:flex-1 lg:h-auto p-3 lg:p-6 flex flex-col">
                    <div className="flex-1 min-h-0">
                        <FieldCanvas width={800} height={600} />
                    </div>
                </div>

                {/* Controls Panel */}
                <div className="lg:w-96 bg-white border-t lg:border-t-0 lg:border-l border-border p-4 lg:p-5 flex flex-col gap-4 flex-shrink-0 overflow-y-auto">
                    {/* Desktop Session Name */}
                    <div className="hidden lg:block">
                        <h2 className="text-xl font-bold text-text-primary mb-1">{currentSession.name}</h2>
                        <div className="flex items-center gap-2 text-sm text-text-secondary">
                            <span className="text-lg font-semibold">{currentSession.cones.length}</span> cones on field
                            <span className="text-xs text-gray-400">({currentSession.fieldWidth}m x {currentSession.fieldHeight}m)</span>
                        </div>
                    </div>

                    <SessionControls
                        onClearAll={() => {
                            if (window.confirm('Delete all cones?')) {
                                removeAllCones(currentSession.id);
                            }
                        }}
                        coneCount={currentSession.cones.length}
                    />
                </div>
            </div>
        </div>
    );
};
