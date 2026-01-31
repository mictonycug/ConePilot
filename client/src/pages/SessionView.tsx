import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useSessionStore } from '../store/useSessionStore';
import { Navbar } from '../components/layout/Navbar';
import { FieldCanvas } from '../components/session/FieldCanvas';
import { ControlPanel } from '../components/session/ControlPanel';
import { SimulationOverlay } from '../components/session/SimulationOverlay';

export const SessionView: React.FC = () => {
    const { id } = useParams<{ id: string }>();
    const { loadSessionById, currentSession, isLoading } = useSessionStore();

    useEffect(() => {
        if (id) {
            loadSessionById(id);
        }
    }, [id, loadSessionById]);

    if (isLoading || !currentSession) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-background">
                <div className="animate-pulse text-primary">Loading Session...</div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Navbar />
            <main className="flex-1 flex overflow-hidden">
                <div className="flex-1 p-6 relative flex items-center justify-center bg-background overflow-auto">
                    <SimulationOverlay />
                    <div className="max-w-full max-h-full">
                        <FieldCanvas width={800} height={600} />
                    </div>
                </div>
                <ControlPanel />
            </main>
        </div>
    );
};
