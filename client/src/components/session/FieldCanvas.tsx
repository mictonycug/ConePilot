import React, { useRef, useState, useEffect } from 'react';
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
const ZOOM_STEP = 0.5;
const MIN_ZOOM = 1;
const MAX_ZOOM = 4;

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
    const containerRef = useRef<HTMLDivElement>(null);
    const [mousePos, setMousePos] = useState<{ x: number, y: number } | null>(null);
    const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
    const [zoom, setZoom] = useState(1);
    const [stagePos, setStagePos] = useState({ x: 0, y: 0 });

    // Measure container size
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        const observer = new ResizeObserver(entries => {
            const { width, height } = entries[0].contentRect;
            setContainerSize({ width, height });
        });
        observer.observe(container);
        return () => observer.disconnect();
    }, []);

    // Reset pan position when zooming back to fit
    useEffect(() => {
        if (zoom === MIN_ZOOM) {
            setStagePos({ x: 0, y: 0 });
        }
    }, [zoom]);

    if (!currentSession) return null;

    const fieldWidthPx = currentSession.fieldWidth * SCALE;
    const fieldHeightPx = currentSession.fieldHeight * SCALE;
    const totalWidth = fieldWidthPx + PADDING * 2;
    const totalHeight = fieldHeightPx + PADDING * 2;

    // Fit scale: shrink to fit container, but never upscale past 1:1
    const fitScale = containerSize.width > 0
        ? Math.min(containerSize.width / totalWidth, containerSize.height / totalHeight, 1)
        : 1;

    const actualScale = zoom * fitScale;
    const scaledWidth = totalWidth * actualScale;
    const scaledHeight = totalHeight * actualScale;

    // Center content when smaller than container
    const centerX = Math.max(0, (containerSize.width - scaledWidth) / 2);
    const centerY = Math.max(0, (containerSize.height - scaledHeight) / 2);

    const canDrag = scaledWidth > containerSize.width || scaledHeight > containerSize.height;

    // Clamp stage position so content can't be dragged off-screen
    const clampStagePos = (pos: { x: number, y: number }) => {
        let x: number, y: number;
        if (scaledWidth <= containerSize.width) {
            x = centerX;
        } else {
            const minX = containerSize.width - scaledWidth;
            x = Math.max(minX, Math.min(0, pos.x));
        }
        if (scaledHeight <= containerSize.height) {
            y = centerY;
        } else {
            const minY = containerSize.height - scaledHeight;
            y = Math.max(minY, Math.min(0, pos.y));
        }
        return { x, y };
    };

    const effectivePos = canDrag ? clampStagePos(stagePos) : { x: centerX, y: centerY };

    // Zoom handlers
    const handleZoomIn = () => setZoom(prev => Math.min(prev + ZOOM_STEP, MAX_ZOOM));
    const handleZoomOut = () => setZoom(prev => Math.max(prev - ZOOM_STEP, MIN_ZOOM));
    const handleFitView = () => {
        setZoom(MIN_ZOOM);
        setStagePos({ x: 0, y: 0 });
    };

    // Convert screen pointer to field coordinates (meters)
    const pointerToFieldCoords = (stage: any) => {
        const pointer = stage.getPointerPosition();
        if (!pointer) return null;

        const sx = stage.x();
        const sy = stage.y();
        const x = ((pointer.x - sx) / actualScale - PADDING) / SCALE;
        const y = ((pointer.y - sy) / actualScale - PADDING) / SCALE;

        if (x >= 0 && x <= currentSession.fieldWidth && y >= 0 && y <= currentSession.fieldHeight) {
            return { x, y };
        }
        return null;
    };

    const handleMouseMove = (e: any) => {
        const stage = e.target.getStage();
        if (!stage) return;
        setMousePos(pointerToFieldCoords(stage));
    };

    const handleStageClick = (e: any) => {
        if (e.target.attrs.draggable || e.target.parent?.attrs.draggable) return;
        if (isSimulating) return;

        const stage = e.target.getStage();
        if (!stage) return;

        const coords = pointerToFieldCoords(stage);
        if (coords) {
            addCone(currentSession.id, coords.x, coords.y);
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
    const pathPoints = optimizedPath.flatMap(p => [p.x * SCALE, p.y * SCALE]);

    const stageWidth = containerSize.width || totalWidth;
    const stageHeight = containerSize.height || totalHeight;

    return (
        <div
            ref={containerRef}
            className="bg-white rounded-xl shadow-sm border border-border relative w-full h-full overflow-hidden"
            style={{ touchAction: 'none' }}
        >
            <Stage
                width={stageWidth}
                height={stageHeight}
                scaleX={actualScale}
                scaleY={actualScale}
                x={effectivePos.x}
                y={effectivePos.y}
                draggable={canDrag}
                dragBoundFunc={(pos) => clampStagePos(pos)}
                onDragEnd={(e) => {
                    setStagePos({ x: e.target.x(), y: e.target.y() });
                }}
                onClick={handleStageClick}
                onTap={handleStageClick}
                onMouseMove={handleMouseMove}
                onTouchMove={handleMouseMove}
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
                            opacity={0.8}
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

            {/* Zoom Controls */}
            <div className="absolute bottom-3 right-3 flex flex-col gap-1.5 z-10">
                <button
                    onClick={handleZoomIn}
                    disabled={zoom >= MAX_ZOOM}
                    className="w-10 h-10 bg-white border border-gray-300 rounded-lg shadow-md flex items-center justify-center text-xl font-bold text-gray-700 hover:bg-gray-50 active:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors select-none"
                >
                    +
                </button>
                <button
                    onClick={handleZoomOut}
                    disabled={zoom <= MIN_ZOOM}
                    className="w-10 h-10 bg-white border border-gray-300 rounded-lg shadow-md flex items-center justify-center text-xl font-bold text-gray-700 hover:bg-gray-50 active:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors select-none"
                >
                    −
                </button>
                <button
                    onClick={handleFitView}
                    className="w-10 h-10 bg-white border border-gray-300 rounded-lg shadow-md flex items-center justify-center text-xs font-bold text-gray-700 hover:bg-gray-50 active:bg-gray-100 transition-colors select-none"
                    title="Fit to view"
                >
                    FIT
                </button>
            </div>

            {/* Zoom Level Indicator */}
            <div className="absolute top-3 left-3 bg-white/90 border border-gray-200 rounded-md px-2 py-1 text-xs font-medium text-gray-500 shadow-sm z-10 select-none pointer-events-none">
                {Math.round(actualScale * 100)}%
            </div>
        </div>
    );
};
