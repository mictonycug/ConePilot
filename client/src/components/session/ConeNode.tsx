import React from 'react';
import { Circle, Text, Group, Image as KonvaImage, Rect } from 'react-konva';
import useImage from 'use-image';
import type { ConeData } from '../../store/useSessionStore';

const BOUNDARY_MARGIN = 0.5; // 50cm margin from field edges

interface ConeNodeProps {
    cone: ConeData;
    scale: number; // pixels per meter
    fieldHeight: number; // field height in meters (for Y-flip)
    fieldWidth: number;  // field width in meters (for boundary clamping)
    onDragEnd: (id: string, x: number, y: number) => void;
    onDelete: (id: string) => void;
    imageMode?: boolean;
    opacity?: number;
    snapSize?: number; // meters (0 = no snap)
    coneSize?: number; // pixel diameter of the cone visual (in canvas coords)
    isSelected?: boolean;
    onToggleSelect?: (id: string) => void;
    readOnly?: boolean;
}

export const ConeNode: React.FC<ConeNodeProps> = ({ cone, scale, fieldHeight, fieldWidth, onDragEnd, onDelete, imageMode, opacity = 1, snapSize = 0, coneSize = 34, isSelected, onToggleSelect, readOnly }) => {
    const pixelX = cone.x * scale;
    const pixelY = (fieldHeight - cone.y) * scale;
    const [image] = useImage('/cone.png');

    const snapPx = snapSize * scale;
    const half = coneSize / 2;
    // Hit area should match cone size closely (coneSize is in field coordinate pixels)
    // Just slightly larger for easier clicking (1.2x), but not too big
    const hitSize = coneSize * 1.2;
    const badgeOffset = half * 0.7;

    return (
        <Group
            x={pixelX}
            y={pixelY}
            opacity={opacity}
            draggable={!readOnly}
            onDragMove={(e) => {
                // Clamp to boundary margin (in canvas pixel coords)
                const minPx = BOUNDARY_MARGIN * scale;
                const maxPxX = (fieldWidth - BOUNDARY_MARGIN) * scale;
                const maxPxY = (fieldHeight - BOUNDARY_MARGIN) * scale;
                let x = Math.max(minPx, Math.min(maxPxX, e.target.x()));
                let y = Math.max(minPx, Math.min(maxPxY, e.target.y()));
                if (snapPx > 0) {
                    x = Math.round(x / snapPx) * snapPx;
                    y = Math.round(y / snapPx) * snapPx;
                    x = Math.max(minPx, Math.min(maxPxX, x));
                    y = Math.max(minPx, Math.min(maxPxY, y));
                }
                e.target.x(x);
                e.target.y(y);
            }}
            onDragEnd={(e) => {
                let newX = e.target.x() / scale;
                let newY = fieldHeight - (e.target.y() / scale);
                if (snapSize > 0) {
                    newX = Math.round(newX / snapSize) * snapSize;
                    newY = Math.round(newY / snapSize) * snapSize;
                }
                // Clamp to boundary margin
                newX = Math.max(BOUNDARY_MARGIN, Math.min(fieldWidth - BOUNDARY_MARGIN, newX));
                newY = Math.max(BOUNDARY_MARGIN, Math.min(fieldHeight - BOUNDARY_MARGIN, newY));
                onDragEnd(cone.id, newX, newY);
            }}
            onClick={(e) => {
                e.cancelBubble = true;
                if (readOnly) return;
                if (onToggleSelect) {
                    onToggleSelect(cone.id);
                } else if (window.confirm('Delete this cone?')) {
                    onDelete(cone.id);
                }
            }}
            onContextMenu={(e) => {
                e.evt.preventDefault();
                if (readOnly) return;
                if (onToggleSelect) {
                    onToggleSelect(cone.id);
                } else {
                    onDelete(cone.id);
                }
            }}
            onMouseEnter={(e) => {
                const container = e.target.getStage()?.container();
                if (container) container.style.cursor = 'pointer';
            }}
            onMouseLeave={(e) => {
                const container = e.target.getStage()?.container();
                if (container) container.style.cursor = 'default';
            }}
        >
            {/* Selection Area / Hit Area - sized to match cone image */}
            <Rect
                x={-hitSize / 2}
                y={-hitSize / 2}
                width={hitSize}
                height={hitSize}
                fill="transparent"
            />

            {imageMode && image ? (
                <KonvaImage
                    image={image}
                    width={coneSize}
                    height={coneSize}
                    offsetX={half}
                    offsetY={half}
                    shadowColor="black"
                    shadowBlur={3}
                    shadowOpacity={0.25}
                />
            ) : (
                <Circle
                    radius={half * 0.5}
                    fill={cone.status === 'PLACED' ? '#D97706' : '#FFFFFF'}
                    stroke="#D97706"
                    strokeWidth={1.5}
                    shadowColor="black"
                    shadowBlur={3}
                    shadowOpacity={0.2}
                />
            )}

            {/* Selection Ring */}
            {isSelected && (
                <>
                    <Circle
                        radius={half * 0.85}
                        fill="transparent"
                        stroke="#22C55E"
                        strokeWidth={2.5}
                    />
                    <Group x={-badgeOffset} y={-badgeOffset}>
                        <Circle radius={Math.max(5, half * 0.35)} fill="#22C55E" />
                        <Text
                            text="✓"
                            fontSize={Math.max(6, half * 0.45)}
                            fill="#FFFFFF"
                            offsetX={Math.max(2, half * 0.15)}
                            offsetY={Math.max(3, half * 0.2)}
                            align="center"
                            fontStyle="bold"
                        />
                    </Group>
                </>
            )}

            {/* Index Badge */}
            {cone.orderIndex !== undefined && cone.orderIndex !== null && (
                <Group x={badgeOffset} y={-badgeOffset}>
                    <Circle radius={Math.max(5, half * 0.4)} fill="#1F1F1F" />
                    <Text
                        text={(cone.orderIndex + 1).toString()}
                        fontSize={Math.max(6, half * 0.5)}
                        fill="#FFFFFF"
                        offsetX={Math.max(2, half * 0.15)}
                        offsetY={Math.max(3, half * 0.2)}
                        align="center"
                    />
                </Group>
            )}
        </Group>
    );
};
