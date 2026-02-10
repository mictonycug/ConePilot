
import React, { useEffect, useState } from 'react';
import { Plus, Trash2, Pencil, X } from 'lucide-react';
import { useSessionStore } from '../store/useSessionStore';
import { useNavigate } from 'react-router-dom';

const CreateSessionModal: React.FC<{ onClose: () => void; onCreate: (name: string, w: number, h: number) => void; isLoading: boolean }> = ({ onClose, onCreate, isLoading }) => {
    const [name, setName] = useState('');
    const [width, setWidth] = useState('3');
    const [height, setHeight] = useState('3');

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const w = parseFloat(width);
        const h = parseFloat(height);
        if (!name.trim()) return;
        if (isNaN(w) || w <= 0 || isNaN(h) || h <= 0) return;
        onCreate(name.trim(), w, h);
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/40" />

            {/* Modal */}
            <div
                className="relative bg-white rounded-2xl shadow-xl border border-border w-full max-w-md"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-border">
                    <h2 className="text-lg font-semibold text-text-primary">New Session</h2>
                    <button
                        onClick={onClose}
                        className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                    >
                        <X size={18} />
                    </button>
                </div>

                {/* Body */}
                <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">
                    {/* Name */}
                    <div>
                        <label className="block text-sm font-medium text-text-secondary mb-1.5">Session Name</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                            placeholder="e.g. Training Drill #1"
                            autoFocus
                            required
                        />
                    </div>

                    {/* Field Size */}
                    <div>
                        <label className="block text-sm font-medium text-text-secondary mb-1.5">Field Size (metres)</label>
                        <div className="flex items-center gap-3">
                            <div className="flex-1">
                                <div className="text-xs text-gray-400 mb-1">Width</div>
                                <input
                                    type="number"
                                    value={width}
                                    onChange={(e) => setWidth(e.target.value)}
                                    min="1"
                                    max="100"
                                    step="0.5"
                                    className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                                    required
                                />
                            </div>
                            <span className="text-gray-400 font-medium mt-5">&times;</span>
                            <div className="flex-1">
                                <div className="text-xs text-gray-400 mb-1">Height</div>
                                <input
                                    type="number"
                                    value={height}
                                    onChange={(e) => setHeight(e.target.value)}
                                    min="1"
                                    max="100"
                                    step="0.5"
                                    className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                                    required
                                />
                            </div>
                        </div>
                        <p className="text-xs text-gray-400 mt-2">The robot starts at the bottom-left corner (0, 0).</p>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center justify-end gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-gray-100 rounded-lg transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={isLoading || !name.trim()}
                            className="px-5 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:bg-opacity-90 transition-all shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isLoading ? 'Creating...' : 'Create Session'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export const Dashboard: React.FC = () => {
    const { sessions, loadSessions, createSession, deleteSession, renameSession, isLoading } = useSessionStore();
    const navigate = useNavigate();
    const [showCreateModal, setShowCreateModal] = useState(false);

    console.log('Dashboard render. Sessions:', sessions.length, 'IsLoading:', isLoading);

    useEffect(() => {
        console.log('Dashboard mounting, loading sessions...');
        loadSessions();
    }, [loadSessions]);

    const handleCreateSession = async (name: string, fieldWidth: number, fieldHeight: number) => {
        try {
            const id = await createSession(name, fieldWidth, fieldHeight);
            setShowCreateModal(false);
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
        <div className="flex-1 bg-background">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-2xl font-bold text-text-primary">Your Sessions</h1>
                        <p className="text-text-secondary mt-1">Manage and track your autonomous training drills</p>
                    </div>

                    <button
                        onClick={() => setShowCreateModal(true)}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg font-medium hover:bg-opacity-90 transition-all shadow-sm active:scale-95 disabled:opacity-50"
                    >
                        <Plus size={20} />
                        New Session
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
                        <button onClick={() => setShowCreateModal(true)} className="text-primary font-medium hover:underline">
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
                                    {session.cones?.length || 0} cones • {session.fieldWidth}m &times; {session.fieldHeight}m • {new Date(session.updatedAt || Date.now()).toLocaleDateString()}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Create Session Modal */}
            {showCreateModal && (
                <CreateSessionModal
                    onClose={() => setShowCreateModal(false)}
                    onCreate={handleCreateSession}
                    isLoading={isLoading}
                />
            )}
        </div>
    );
};
