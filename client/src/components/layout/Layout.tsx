import React from 'react';
import { Outlet } from 'react-router-dom';
import { Navbar } from './Navbar';

export const Layout: React.FC = () => {
    return (
        <div className="min-h-screen bg-background text-text-primary font-sans flex flex-col">
            <Navbar />
            <main className="flex-1 flex flex-col min-h-0">
                <Outlet />
            </main>
        </div>
    );
};
