import React from 'react';
import { Outlet } from 'react-router-dom';

export const Layout: React.FC = () => {
    return (
        <div className="min-h-screen bg-background text-text-primary font-sans">
            <main>
                <Outlet />
            </main>
        </div>
    );
};
