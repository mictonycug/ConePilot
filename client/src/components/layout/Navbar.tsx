import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../store/useAuthStore';
import { LogOut, User as UserIcon } from 'lucide-react';

export const Navbar: React.FC = () => {
    const { user, logout } = useAuthStore();
    const navigate = useNavigate();

    const handleLogout = () => {
        logout();
        navigate('/');
    };

    return (
        <nav className="h-16 border-b border-border bg-background-secondary flex items-center justify-between px-6 shadow-sm">
            <div className="flex items-center gap-2">
                <Link to="/dashboard" className="text-xl font-semibold tracking-tight text-text-primary">
                    ConePilot
                </Link>
            </div>

            <div className="flex items-center gap-4">
                {user && (
                    <>
                        <div className="flex items-center gap-2 text-text-secondary text-sm">
                            <UserIcon size={16} />
                            <span>{user.name}</span>
                        </div>
                        <button
                            onClick={handleLogout}
                            className="text-text-secondary hover:text-text-primary transition-colors"
                            title="Logout"
                        >
                            <LogOut size={20} />
                        </button>
                    </>
                )}
            </div>
        </nav>
    );
};
