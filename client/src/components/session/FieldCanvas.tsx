import React, { useRef, useState, useEffect, useMemo } from 'react';
import { Stage, Layer, Rect, Line, Text, Image as KonvaImage, Group } from 'react-konva';
import useImage from 'use-image';
import { useSessionStore } from '../../store/useSessionStore';
import { ConeNode } from './ConeNode';
import { RobotNode } from './RobotNode';
import { Grid3x3 } from 'lucide-react';

interface FieldCanvasProps {
    width: number;
    height: number;
}

const SCALE = 40; // 40px/m
const ZOOM_STEP = 0.5;
const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const SNAP_OPTIONS = [0, 0.25, 0.5, 1];

const snapVal = (v: number, size: number) => size > 0 ? Math.round(v / size) * size : v;

// Inner component to handle image loading hook
const ConeImage = ({ x, y, opacity = 1, rotation = 0, size = 30 }: { x: number, y: number, opacity?: number, rotation?: number, size?: number }) => {
    const [image] = useImage('/cone.png');
    const half = size / 2;
    return <KonvaImage
        image={image}
        x={x}
        y={y}
        width={size}
        height={size}
        offsetX={half}
        offsetY={half}
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
    const [snapIndex, setSnapIndex] = useState(2); // default to 0.5m

    const snapSize = SNAP_OPTIONS[snapIndex];

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

    const fW = currentSession.fieldWidth;
    const fH = currentSession.fieldHeight;
    const fieldWidthPx = fW * SCALE;
    const fieldHeightPx = fH * SCALE;

    // Dynamic padding: smaller for small fields, larger for big ones
    const PADDING = Math.max(fW, fH) <= 5 ? 30 : 60;

    const totalWidth = fieldWidthPx + PADDING * 2;
    const totalHeight = fieldHeightPx + PADDING * 2;

    // Fit scale: shrink or grow to fit container
    const fitScale = containerSize.width > 0
        ? Math.min(containerSize.width / totalWidth, containerSize.height / totalHeight)
        : 1;

    // Scale-aware stroke: divide by fitScale so strokes look consistent regardless of zoom level
    const strokeScale = 1 / fitScale;

    // Cone size: target ~30px visual on screen, but never exceed 0.3m in field coords
    const coneSize = Math.max(8, Math.min(30 / fitScale, 0.3 * SCALE));

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

    // Snap toggle: cycle through options
    const handleCycleSnap = () => setSnapIndex(prev => (prev + 1) % SNAP_OPTIONS.length);

    // --- Y-flip helper: canvas Y → field Y and vice versa ---
    // Field coords: origin (0,0) at bottom-left, Y increases upward
    // Canvas coords: origin (0,0) at top-left, Y increases downward
    const fieldToCanvasY = (fy: number) => (fH - fy) * SCALE;
    const canvasToFieldY = (cy: number) => fH - (cy / SCALE);

    // Convert screen pointer to field coordinates (meters), with optional snapping
    const pointerToFieldCoords = (stage: any): { raw: { x: number; y: number }; snapped: { x: number; y: number } } | null => {
        const pointer = stage.getPointerPosition();
        if (!pointer) return null;

        const sx = stage.x();
        const sy = stage.y();
        const canvasX = ((pointer.x - sx) / actualScale - PADDING) / SCALE;
        const canvasY = ((pointer.y - sy) / actualScale - PADDING) / SCALE;

        // Convert canvas coords to field coords (flip Y)
        const rawX = canvasX;
        const rawY = fH - canvasY;

        if (rawX >= 0 && rawX <= fW && rawY >= 0 && rawY <= fH) {
            return {
                raw: { x: rawX, y: rawY },
                snapped: { x: snapVal(rawX, snapSize), y: snapVal(rawY, snapSize) },
            };
        }
        return null;
    };

    const handleMouseMove = (e: any) => {
        const stage = e.target.getStage();
        if (!stage) return;
        const coords = pointerToFieldCoords(stage);
        setMousePos(coords ? coords.snapped : null);
    };

    const handleStageClick = (e: any) => {
        if (e.target.attrs.draggable || e.target.parent?.attrs.draggable) return;
        if (isSimulating) return;

        const stage = e.target.getStage();
        if (!stage) return;

        const coords = pointerToFieldCoords(stage);
        if (coords) {
            addCone(currentSession.id, coords.snapped.x, coords.snapped.y);
        }
    };

    // Dynamic grid interval: 1m labels for small fields, 5m for large
    const majorStep = Math.max(fW, fH) <= 10 ? 1 : 5;
    const showSubGrid = Math.max(fW, fH) <= 5; // 0.5m sub-grid for small fields

    // Scale-aware font & label offset
    const labelFontSize = Math.max(8, Math.round(12 * Math.min(1, strokeScale)));
    const labelOffset = Math.max(20, PADDING * 0.6);

    // Grid & Labels
    const gridLines = [];
    const labels = [];

    // Sub-grid lines (0.5m intervals)
    if (showSubGrid) {
        for (let i = 0.5; i < fW; i += 1) {
            gridLines.push(
                <Line key={`sv${i}`} points={[i * SCALE, 0, i * SCALE, fieldHeightPx]} stroke="#F0F0F0" strokeWidth={Math.max(0.5, 0.5 * strokeScale)} />
            );
        }
        for (let i = 0.5; i < fH; i += 1) {
            gridLines.push(
                <Line key={`sh${i}`} points={[0, i * SCALE, fieldWidthPx, i * SCALE]} stroke="#F0F0F0" strokeWidth={Math.max(0.5, 0.5 * strokeScale)} />
            );
        }
    }

    // Major/minor grid lines
    for (let i = 0; i <= fW; i += 1) {
        const isMajor = i % majorStep === 0;
        gridLines.push(
            <Line key={`v${i}`} points={[i * SCALE, 0, i * SCALE, fieldHeightPx]} stroke={isMajor ? "#D4D4D8" : "#E5E5E5"} strokeWidth={Math.max(0.5, (isMajor ? 0.75 : 0.5) * strokeScale)} dash={isMajor ? [] : [4, 4]} />
        );
        if (isMajor) labels.push(<Text key={`lx${i}`} x={i * SCALE - 10} y={fieldHeightPx + labelOffset * 0.4} text={`${i}m`} fontSize={labelFontSize} fill="#6B6B6B" />);
    }
    for (let i = 0; i <= fH; i += 1) {
        const isMajor = i % majorStep === 0;
        gridLines.push(
            <Line key={`h${i}`} points={[0, i * SCALE, fieldWidthPx, i * SCALE]} stroke={isMajor ? "#D4D4D8" : "#E5E5E5"} strokeWidth={Math.max(0.5, (isMajor ? 0.75 : 0.5) * strokeScale)} dash={isMajor ? [] : [4, 4]} />
        );
        // Y labels: flipped — canvas row i shows field value (fH - i)
        if (isMajor) labels.push(<Text key={`ly${i}`} x={-labelOffset} y={i * SCALE - 6} text={`${fH - i}m`} fontSize={labelFontSize} fill="#6B6B6B" />);
    }

    // Path Line Points (flip Y for canvas)
    const pathPoints = optimizedPath.flatMap(p => [p.x * SCALE, fieldToCanvasY(p.y)]);

    // Pre-transform path for RobotNode (flip Y into canvas field coords)
    // Memoized so the reference stays stable and doesn't restart the animation on every render
    const robotPath = useMemo(
        () => isSimulating ? optimizedPath.map(p => ({ x: p.x, y: fH - p.y })) : [],
        [isSimulating, optimizedPath, fH]
    );

    const stageWidth = containerSize.width || totalWidth;
    const stageHeight = containerSize.height || totalHeight;

    const snapLabel = snapSize > 0 ? `${snapSize}m` : 'OFF';

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
                    <Rect width={fieldWidthPx} height={fieldHeightPx} fill="#F4F4F5" stroke="#D4D4D8" strokeWidth={Math.max(0.5, 1 * strokeScale)} />
                    {gridLines}
                    {labels}

                    {/* Path Lines */}
                    {pathPoints.length > 0 && (
                        <Line
                            points={pathPoints}
                            stroke="#000000"
                            strokeWidth={Math.max(1, 2 * strokeScale)}
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
                            fieldHeight={fH}
                            snapSize={snapSize}
                            coneSize={coneSize}
                            onDragEnd={(id, x, y) => updateConePosition(currentSession.id, id, x, y)}
                            onDelete={(id) => removeCone(currentSession.id, id)}
                            imageMode={true}
                            opacity={0.8}
                        />
                    ))}

                    {/* Robot Layer (On Top) — path is pre-flipped to canvas coords */}
                    <RobotNode
                        x={0}
                        y={fH}
                        scale={SCALE}
                        path={robotPath}
                    />

                    {/* Ghost Cone Cursor (mousePos is in field coords, convert to canvas) */}
                    {mousePos && !isSimulating && (
                        <Group x={mousePos.x * SCALE} y={fieldToCanvasY(mousePos.y)} opacity={0.6} listening={false}>
                            <ConeImage x={0} y={0} size={coneSize} />
                        </Group>
                    )}
                </Layer>
            </Stage>

            {/* Top-left: Zoom level */}
            <div className="absolute top-3 left-3 bg-white/90 border border-gray-200 rounded-md px-2 py-1 text-xs font-medium text-gray-500 shadow-sm z-10 select-none pointer-events-none">
                {Math.round(actualScale * 100)}%
            </div>

            {/* Top-right: Live coordinate readout */}
            <div className="absolute top-3 right-3 bg-white/90 border border-gray-200 rounded-md px-2.5 py-1 text-xs font-mono text-gray-500 shadow-sm z-10 select-none pointer-events-none">
                {mousePos
                    ? <span><span className="text-gray-400">X</span> {mousePos.x.toFixed(2)}m &nbsp;<span className="text-gray-400">Y</span> {mousePos.y.toFixed(2)}m</span>
                    : <span className="text-gray-400">-- , --</span>
                }
            </div>

            {/* Bottom-left: Snap toggle */}
            <button
                onClick={handleCycleSnap}
                className={`absolute bottom-3 left-3 z-10 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg shadow-md border text-xs font-medium select-none transition-colors ${
                    snapSize > 0
                        ? 'bg-primary/10 border-primary/30 text-primary hover:bg-primary/20'
                        : 'bg-white border-gray-300 text-gray-500 hover:bg-gray-50'
                }`}
                title="Click to cycle snap grid"
            >
                <Grid3x3 size={14} />
                <span>SNAP</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                    snapSize > 0 ? 'bg-primary/20 text-primary' : 'bg-gray-100 text-gray-400'
                }`}>
                    {snapLabel}
                </span>
            </button>

            {/* Bottom-right: Zoom controls */}
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
        </div>
    );
};
