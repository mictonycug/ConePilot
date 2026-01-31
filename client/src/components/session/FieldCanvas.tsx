import React, { useRef, useState } from 'react';
import { Stage, Layer, Rect, Line, Text, Image as KonvaImage, Group } from 'react-konva';
import useImage from 'use-image';
import { useSessionStore } from '../../store/useSessionStore';
import { ConeNode } from './ConeNode';
import { RobotNode } from './RobotNode';

interface FieldCanvasProps {
    width: number;
    height: number;
}

const SCALE = 40; // 40px/m
const PADDING = 60;

// Inner component to handle image loading hook
const ConeImage = ({ x, y, opacity = 1, rotation = 0 }: { x: number, y: number, opacity?: number, rotation?: number }) => {
    const [image] = useImage('/cone.png');
    return <KonvaImage
        image={image}
        x={x}
        y={y}
        width={30}
        height={30}
        offsetX={15}
        offsetY={15}
        opacity={opacity}
        rotation={rotation}
    />;
};

export const FieldCanvas: React.FC<FieldCanvasProps> = ({ width: _width, height: _height }) => {
    const { currentSession, addCone, updateConePosition, removeCone, optimizedPath, isSimulating } = useSessionStore();
    const stageRef = useRef<any>(null);
    const [mousePos, setMousePos] = useState<{ x: number, y: number } | null>(null);

    if (!currentSession) return null;

    const fieldWidthPx = currentSession.fieldWidth * SCALE;
    const fieldHeightPx = currentSession.fieldHeight * SCALE;

    const handleMouseMove = (e: any) => {
        const stage = e.target.getStage();
        if (!stage) return;

        const pointer = stage.getPointerPosition();
        if (!pointer) return;

        const x = (pointer.x - PADDING) / SCALE;
        const y = (pointer.y - PADDING) / SCALE;

        if (x >= 0 && x <= currentSession.fieldWidth && y >= 0 && y <= currentSession.fieldHeight) {
            setMousePos({ x, y });
        } else {
            setMousePos(null);
        }
    };

    const handleStageClick = (e: any) => {
        if (e.target.attrs.draggable || e.target.parent?.attrs.draggable) return;
        if (mousePos && !isSimulating) {
            addCone(currentSession.id, mousePos.x, mousePos.y);
        }
    };

    // Grid & Labels
    const gridLines = [];
    const labels = [];
    for (let i = 0; i <= currentSession.fieldWidth; i += 1) {
        gridLines.push(
            <Line key={`v${i}`} points={[i * SCALE, 0, i * SCALE, fieldHeightPx]} stroke={i % 5 === 0 ? "#D4D4D8" : "#E5E5E5"} strokeWidth={1} dash={i % 5 === 0 ? [] : [4, 4]} />
        );
        if (i % 5 === 0) labels.push(<Text key={`lx${i}`} x={i * SCALE - 10} y={-25} text={`${i}m`} fontSize={12} fill="#6B6B6B" />);
    }
    for (let i = 0; i <= currentSession.fieldHeight; i += 1) {
        gridLines.push(
            <Line key={`h${i}`} points={[0, i * SCALE, fieldWidthPx, i * SCALE]} stroke={i % 5 === 0 ? "#D4D4D8" : "#E5E5E5"} strokeWidth={1} dash={i % 5 === 0 ? [] : [4, 4]} />
        );
        if (i % 5 === 0) labels.push(<Text key={`ly${i}`} x={-35} y={i * SCALE - 6} text={`${i}m`} fontSize={12} fill="#6B6B6B" />);
    }

    // Path Line Points
    // optimizedPath is {x, y}[]. Flatten to [x1, y1, x2, y2...]
    const pathPoints = optimizedPath.flatMap(p => [p.x * SCALE, p.y * SCALE]);

    return (
        <div className="bg-white rounded-xl shadow-sm border border-border flex items-center justify-center p-4 overflow-auto">
            <Stage
                width={fieldWidthPx + PADDING * 2}
                height={fieldHeightPx + PADDING * 2}
                onMouseDown={handleStageClick}
                onMouseMove={handleMouseMove}
                onMouseLeave={() => setMousePos(null)}
                ref={stageRef}
            >
                <Layer x={PADDING} y={PADDING}>
                    <Rect width={fieldWidthPx} height={fieldHeightPx} fill="#F4F4F5" stroke="#D4D4D8" strokeWidth={2} />
                    {gridLines}
                    {labels}

                    {/* Path Lines */}
                    {pathPoints.length > 0 && (
                        <Line
                            points={pathPoints}
                            stroke="#000000"
                            strokeWidth={3}
                            dash={[10, 5]}
                            lineCap="round"
                            lineJoin="round"
                            opacity={0.8}
                        />
                    )}

                    {/* Active Cones */}
                    {currentSession.cones.map((cone) => (
                        <ConeNode
                            key={cone.id}
                            cone={cone}
                            scale={SCALE}
                            onDragEnd={(id, x, y) => updateConePosition(currentSession.id, id, x, y)}
                            onDelete={(id) => removeCone(currentSession.id, id)}
                            imageMode={true}
                            opacity={0.8} // Faded placed cones
                        />
                    ))}

                    {/* Robot Layer (On Top) */}
                    <RobotNode
                        x={0}
                        y={0}
                        scale={SCALE}
                        path={isSimulating ? optimizedPath : []}
                    />

                    {/* Ghost Cone Cursor */}
                    {mousePos && !isSimulating && (
                        <Group x={mousePos.x * SCALE} y={mousePos.y * SCALE} opacity={0.6} listening={false}>
                            <ConeImage x={0} y={0} />
                        </Group>
                    )}
                </Layer>
            </Stage>
        </div>
    );
};
