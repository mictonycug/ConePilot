import React from 'react';
import { Link } from 'react-router-dom';

export const LandingPage: React.FC = () => {
    return (
        <div className="flex flex-col flex-1 bg-background text-text-primary">
            {/* Hero Section */}
            <header className="flex-1 flex flex-col items-center justify-center text-center px-4 py-20">
                <div className="mb-8 p-4 bg-white rounded-2xl shadow-sm border border-border inline-block">
                    <span className="text-4xl">🤖</span>
                </div>

                <h1 className="text-5xl md:text-7xl font-bold tracking-tighter mb-6 text-text-primary">
                    Welcome to the New Era
                    <br />
                    <span className="text-primary block mt-2">of Placing Cones</span>
                </h1>

                <p className="text-xl md:text-2xl text-text-secondary max-w-2xl mb-12 font-light">
                    Autonomous cone placement and retrieval for sports training.
                    Simple, precise, and effortless.
                </p>

                <div className="flex gap-4">
                    <Link
                        to="/login"
                        className="px-8 py-4 bg-primary text-white rounded-lg font-medium text-lg hover:bg-opacity-90 transition-all shadow-lg hover:shadow-xl"
                    >
                        Get Started
                    </Link>
                    <Link
                        to="/register"
                        className="px-8 py-4 bg-white text-text-primary border border-border rounded-lg font-medium text-lg hover:bg-gray-50 transition-all"
                    >
                        Sign Up
                    </Link>
                </div>
            </header>

            {/* Animation Placeholder - using CSS shapes for a "robot" effect */}
            <section className="h-64 md:h-96 relative overflow-hidden bg-white border-t border-border">
                <div className="absolute inset-0 flex items-center justify-center opacity-20">
                    <div className="grid grid-cols-6 gap-4 animate-pulse">
                        {[...Array(24)].map((_, i) => (
                            <div key={i} className="w-12 h-12 rounded-full bg-primary" />
                        ))}
                    </div>
                </div>
                <div className="absolute bottom-10 left-1/2 transform -translate-x-1/2 flex flex-col items-center">
                    <div className="w-16 h-16 bg-text-primary rounded-t-xl relative">
                        <div className="absolute top-4 left-4 w-2 h-2 bg-success rounded-full animate-ping"></div>
                    </div>
                    <div className="w-20 h-2 bg-text-secondary rounded-full mt-1"></div>
                </div>
            </section>

            <footer className="py-8 text-center text-text-secondary border-t border-border text-sm">
                <p>© 2026 ConePilot. Simple • Autonomous • Precise</p>
            </footer>
        </div>
    );
};
