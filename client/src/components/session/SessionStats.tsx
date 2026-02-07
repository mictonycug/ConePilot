
import React from 'react';

interface SessionStatsProps {
    stats: {
        conesPlaced: number;
        distanceTraveled: number;
        etaSeconds: number;
    };
    totalCones: number;
}

export const SessionStats: React.FC<SessionStatsProps> = ({ stats, totalCones }) => {
    return (
        <div>
            <h3 className="font-bold text-black mb-1">Stats</h3>
            <div className="space-y-4">
                <div>
                    <div className="font-bold text-xl">{stats.conesPlaced}/{totalCones}</div>
                    <div className="text-sm text-gray-800">Cones Placed</div>
                </div>
                <div>
                    <div className="font-bold text-xl">{stats.distanceTraveled.toFixed(1)}m</div>
                    <div className="text-sm text-gray-800">Distance</div>
                </div>
            </div>
        </div>
    );
};
