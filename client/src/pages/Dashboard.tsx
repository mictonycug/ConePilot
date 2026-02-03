
import React, { useEffect } from 'react';
import { Navbar } from '../components/layout/Navbar';
import { Plus, Trash2, Pencil } from 'lucide-react';
import { useSessionStore } from '../store/useSessionStore';
import { useNavigate } from 'react-router-dom';

export const Dashboard: React.FC = () => {
    const { sessions, loadSessions, createSession, deleteSession, renameSession, isLoading } = useSessionStore();
    const navigate = useNavigate();

    console.log('Dashboard render. Sessions:', sessions.length, 'IsLoading:', isLoading);

    useEffect(() => {
        console.log('Dashboard mounting, loading sessions...');
        loadSessions();
    }, [loadSessions]);

    const handleCreateSession = async () => {
        try {
            const id = await createSession('New Session');
            navigate(`/session/${id}`);
        } catch (e) {
            console.error(e);
        }
    };

    const handleDeleteSession = async (e: React.MouseEvent, id: string) => {
        e.stopPropagation();
        if (window.confirm('Are you sure you want to delete this session?')) {
            try {
                await deleteSession(id);
            } catch (err) {
                console.error("Failed to delete session", err);
            }
        }
    };

    const handleRenameSession = async (e: React.MouseEvent, id: string, currentName: string) => {
        e.stopPropagation();
        const newName = window.prompt("Enter new session name:", currentName);
        if (newName && newName !== currentName) {
            try {
                await renameSession(id, newName);
            } catch (err) {
                console.error("Failed to rename session", err);
            }
        }
    };

    return (
        <div className="min-h-screen bg-background">
            <Navbar />

            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-2xl font-bold text-text-primary">Your Sessions</h1>
                        <p className="text-text-secondary mt-1">Manage and track your autonomous training drills</p>
                    </div>

                    <button
                        onClick={handleCreateSession}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg font-medium hover:bg-opacity-90 transition-all shadow-sm active:scale-95 disabled:opacity-50"
                    >
                        <Plus size={20} />
                        {isLoading ? 'Creating...' : 'New Session'}
                    </button>
                </div>

                {sessions.length === 0 ? (
                    /* Empty State */
                    <div className="text-center py-20 bg-white rounded-2xl border border-border border-dashed">
                        <div className="mx-auto w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
                            <span className="text-2xl text-gray-300">📋</span>
                        </div>
                        <h3 className="text-lg font-medium text-text-primary">No sessions yet</h3>
                        <p className="text-text-secondary mt-2 mb-6">Create your first session to start placing cones.</p>
                        <button onClick={handleCreateSession} className="text-primary font-medium hover:underline">
                            + Create New Session
                        </button>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {sessions.map(session => (
                            <div
                                key={session.id}
                                onClick={() => navigate(`/session/${session.id}`)}
                                className="bg-white p-6 rounded-xl shadow-sm border border-border hover:shadow-md transition-shadow cursor-pointer block"
                            >
                                <div className="flex justify-between items-start mb-4">
                                    <h3 className="font-semibold text-text-primary truncate">{session.name}</h3>
                                    <div className="flex items-center gap-2">
                                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${session.status === 'COMPLETED' ? 'bg-green-100 text-green-800' : 'bg-orange-100 text-orange-800'
                                            }`}>
                                            {session.status}
                                        </span>
                                        <button
                                            onClick={(e) => handleRenameSession(e, session.id, session.name)}
                                            className="p-1 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded transition-colors"
                                            title="Rename Session"
                                        >
                                            <Pencil size={16} />
                                        </button>
                                        <button
                                            onClick={(e) => handleDeleteSession(e, session.id)}
                                            className="p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                                            title="Delete Session"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    </div>
                                </div>
                                <div className="text-sm text-text-secondary">
                                    {session.cones?.length || 0} cones • {new Date(session.updatedAt || Date.now()).toLocaleDateString()}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </main>
        </div>
    );
};
