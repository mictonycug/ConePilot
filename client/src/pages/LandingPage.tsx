import React from 'react';
import { Link } from 'react-router-dom';

export const LandingPage: React.FC = () => {
    return (
        <div className="flex flex-col h-screen overflow-hidden bg-background text-text-primary">
            {/* Hero — fills viewport minus footer */}
            <header className="flex-1 relative flex flex-col items-center justify-center text-center px-4 overflow-hidden">
                {/* Background decoration: cone-field grid */}
                <div className="absolute inset-0 flex items-end justify-center pointer-events-none">
                    <div className="grid grid-cols-8 gap-3 md:gap-5 opacity-[0.06] mb-12">
                        {[...Array(32)].map((_, i) => (
                            <div key={i} className="w-8 h-8 md:w-12 md:h-12 rounded-full bg-primary" />
                        ))}
                    </div>
                </div>

                {/* Foreground content */}
                <div className="relative z-10 flex flex-col items-center">
                    {/* Robot icon with ping indicator */}
                    <div className="mb-6 md:mb-8 p-4 bg-white rounded-2xl shadow-sm border border-border relative">
                        <span className="text-4xl">🤖</span>
                        <span className="absolute -top-1 -right-1 w-3 h-3 bg-success rounded-full animate-ping" />
                        <span className="absolute -top-1 -right-1 w-3 h-3 bg-success rounded-full" />
                    </div>

                    <h1 className="text-4xl sm:text-5xl md:text-7xl font-bold tracking-tighter mb-4 md:mb-6 text-text-primary">
                        Welcome to the New Era
                        <br />
                        <span className="text-primary block mt-2">of Placing Cones</span>
                    </h1>

                    <p className="text-lg md:text-2xl text-text-secondary max-w-2xl mb-8 md:mb-12 font-light">
                        Autonomous cone placement and retrieval for sports training.
                        Simple, precise, and effortless.
                    </p>

                    <div className="flex gap-4">
                        <Link
                            to="/login"
                            className="px-8 py-4 bg-primary text-white rounded-lg font-medium text-lg hover:bg-opacity-90 transition-all shadow-lg hover:shadow-xl"
                        >
                            Log In
                        </Link>
                        <Link
                            to="/register"
                            className="px-8 py-4 bg-white text-text-primary border border-border rounded-lg font-medium text-lg hover:bg-gray-50 transition-all"
                        >
                            Sign Up
                        </Link>
                    </div>
                </div>
            </header>

            <footer className="shrink-0 py-4 text-center text-text-secondary border-t border-border text-sm">
                <p>&copy; 2026 ConePilot. Simple &bull; Autonomous &bull; Precise</p>
            </footer>
        </div>
    );
};
