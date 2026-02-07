import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../store/useAuthStore';
import { LogOut, Home } from 'lucide-react';

export const Navbar: React.FC = () => {
    const { user, isAuthenticated, logout } = useAuthStore();
    const navigate = useNavigate();

    const handleLogout = () => {
        logout();
        navigate('/');
    };

    return (
        <nav className="h-14 border-b border-border bg-white flex items-center justify-between px-4 sm:px-6 flex-shrink-0">
            {/* Left — Brand */}
            <Link
                to={isAuthenticated ? '/dashboard' : '/'}
                className="flex items-center gap-2.5 group"
            >
                {isAuthenticated && (
                    <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                        <Home size={16} className="text-primary" />
                    </div>
                )}
                <span className="text-lg font-semibold tracking-tight text-text-primary">
                    ConePilot
                </span>
            </Link>

            {/* Right */}
            {isAuthenticated ? (
                <button
                    onClick={handleLogout}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-gray-100 rounded-lg transition-colors"
                >
                    <span>Log Out</span>
                    <LogOut size={16} />
                </button>
            ) : (
                <div className="flex items-center gap-3">
                    <Link
                        to="/login"
                        className="text-sm font-medium text-text-secondary hover:text-text-primary transition-colors"
                    >
                        Log In
                    </Link>
                    <Link
                        to="/register"
                        className="text-sm font-medium px-4 py-1.5 bg-primary text-white rounded-lg hover:bg-opacity-90 transition-all"
                    >
                        Sign Up
                    </Link>
                </div>
            )}
        </nav>
    );
};
