import React from 'react';
import { Circle, Text, Group, Image as KonvaImage } from 'react-konva';
import useImage from 'use-image';
import type { ConeData } from '../../store/useSessionStore';

interface ConeNodeProps {
    cone: ConeData;
    scale: number; // pixels per meter
    onDragEnd: (id: string, x: number, y: number) => void;
    onDelete: (id: string) => void;
    imageMode?: boolean;
    opacity?: number;
}

export const ConeNode: React.FC<ConeNodeProps> = ({ cone, scale, onDragEnd, onDelete, imageMode, opacity = 1 }) => {
    const pixelX = cone.x * scale;
    const pixelY = cone.y * scale;
    const [image] = useImage('/cone.png');

    return (
        <Group
            x={pixelX}
            y={pixelY}
            opacity={opacity}
            draggable
            onDragEnd={(e) => {
                const newX = e.target.x() / scale;
                const newY = e.target.y() / scale;
                onDragEnd(cone.id, newX, newY);
            }}
            onClick={(e) => {
                if (e.evt.button === 2) { // Right click
                    onDelete(cone.id);
                }
            }}
            onContextMenu={(e) => {
                e.evt.preventDefault(); // Prevent native menu
                onDelete(cone.id);
            }}
        >
            {/* Selection Area / Hit Area */}
            <Circle radius={20} fill="transparent" />

            {imageMode && image ? (
                <KonvaImage
                    image={image}
                    width={34}
                    height={34}
                    offsetX={17}
                    offsetY={17}
                    shadowColor="black"
                    shadowBlur={5}
                    shadowOpacity={0.3}
                />
            ) : (
                /* Fallback Cone Body */
                <Circle
                    radius={8}
                    fill={cone.status === 'PLACED' ? '#D97706' : '#FFFFFF'}
                    stroke="#D97706"
                    strokeWidth={2}
                    shadowColor="black"
                    shadowBlur={5}
                    shadowOpacity={0.2}
                />
            )}

            {/* Index Badge */}
            {cone.orderIndex !== undefined && cone.orderIndex !== null && (
                <Group x={12} y={-12}>
                    <Circle radius={8} fill="#1F1F1F" />
                    <Text
                        text={(cone.orderIndex + 1).toString()}
                        fontSize={10}
                        fill="#FFFFFF"
                        offsetX={3}
                        offsetY={4}
                        align="center"
                    />
                </Group>
            )}
        </Group>
    );
};
