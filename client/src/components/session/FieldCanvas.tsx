import React, { useRef, useState, useEffect, useCallback } from 'react';
import { Stage, Layer, Rect, Line, Text, Image as KonvaImage, Group, Circle, Wedge } from 'react-konva';
import useImage from 'use-image';
import { useSessionStore } from '../../store/useSessionStore';
import { ConeNode } from './ConeNode';
import { Grid3x3 } from 'lucide-react';
import { rosBridge } from '../../services/rosbridge';

// Pulsating cone shown while placement API call is in flight
const PlacingConeGhost = ({ x, y, size }: { x: number; y: number; size: number }) => {
    const [image] = useImage('/cone.png');
    const [pulse, setPulse] = useState(0);
    const half = size / 2;

    useEffect(() => {
        let raf: number;
        const start = performance.now();
        const animate = (now: number) => {
            setPulse(Math.sin((now - start) * 0.006) * 0.5 + 0.5); // 0-1 pulsation
            raf = requestAnimationFrame(animate);
        };
        raf = requestAnimationFrame(animate);
        return () => cancelAnimationFrame(raf);
    }, []);

    const ringRadius = half * (1.0 + pulse * 0.6);
    const ringOpacity = 0.6 - pulse * 0.4;

    return (
        <Group x={x} y={y} listening={false}>
            {/* Pulsating ring */}
            <Circle
                radius={ringRadius}
                fill="transparent"
                stroke="#F59E0B"
                strokeWidth={2}
                opacity={ringOpacity}
            />
            {/* Cone image */}
            {image && (
                <KonvaImage
                    image={image}
                    width={size}
                    height={size}
                    offsetX={half}
                    offsetY={half}
                    opacity={0.5 + pulse * 0.3}
                />
            )}
        </Group>
    );
};

// Pulsating cyan ring for collection target cone
const CollectionTargetRing = ({ x, y, size }: { x: number; y: number; size: number }) => {
    const [pulse, setPulse] = useState(0);
    const half = size / 2;

    useEffect(() => {
        let raf: number;
        const start = performance.now();
        const animate = (now: number) => {
            setPulse(Math.sin((now - start) * 0.005) * 0.5 + 0.5);
            raf = requestAnimationFrame(animate);
        };
        raf = requestAnimationFrame(animate);
        return () => cancelAnimationFrame(raf);
    }, []);

    const ringRadius = half * (1.2 + pulse * 0.5);
    const ringOpacity = 0.8 - pulse * 0.4;

    return (
        <Group x={x} y={y} listening={false}>
            <Circle
                radius={ringRadius}
                fill="transparent"
                stroke="#06B6D4"
                strokeWidth={2.5}
                opacity={ringOpacity}
            />
            <Circle
                radius={half * 1.1}
                fill="transparent"
                stroke="#06B6D4"
                strokeWidth={1.5}
                opacity={0.6}
            />
        </Group>
    );
};

interface FieldCanvasProps {
    width: number;
    height: number;
}

// ── Ultrasonic radar overlay ─────────────────────────────
const ULTRASONIC_ANGLES: Record<string, number> = {
    FC: 0, FL: -40, FR: 40, L: -90, R: 90, BK: 180,
};
const US_BEAM_WIDTH = 30;          // degrees
const US_MAX_DISPLAY_CM = 100;     // cap visual at 1m — beyond this is noise

function usZoneColor(cm: number) {
    if (cm < 15)  return { fill: 'rgba(220,107,26,0.25)', stroke: 'rgba(220,107,26,0.6)' };  // orange — hard stop
    if (cm < 40)  return { fill: 'rgba(234,179,8,0.18)', stroke: 'rgba(234,179,8,0.5)' };    // yellow — slowing
    return { fill: 'rgba(37,99,235,0.10)', stroke: 'rgba(37,99,235,0.3)' };                   // blue — clear
}

const SCALE = 120; // 120px/m — high resolution for small fields
const ZOOM_STEP = 0.25;
const MIN_ZOOM = 1;
const MAX_ZOOM = 5;
const SNAP_OPTIONS = [0, 0.125, 0.25, 0.5];
const BOUNDARY_MARGIN = 0.25; // 25cm margin from field edges

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
    const { currentSession, addCone, updateConePosition, removeCone, robotPose, robotConnected, missionConeIds, toggleMissionCone, isReadOnly, isPlacingCone, pendingCone, collectionActive, collectionTargetConeId, collectionPhase, collectionResults, ultrasonicReadings, navAvoidanceState } = useSessionStore();
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

    // Cone size: real cone base is ~15cm diameter, render to scale
    const coneSize = 0.15 * SCALE;

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

        // Clamp to boundary margin zone for cone placement
        const minX = BOUNDARY_MARGIN;
        const maxX = fW - BOUNDARY_MARGIN;
        const minY = BOUNDARY_MARGIN;
        const maxY = fH - BOUNDARY_MARGIN;

        if (rawX >= 0 && rawX <= fW && rawY >= 0 && rawY <= fH) {
            const clampedX = Math.max(minX, Math.min(maxX, rawX));
            const clampedY = Math.max(minY, Math.min(maxY, rawY));
            return {
                raw: { x: clampedX, y: clampedY },
                snapped: {
                    x: Math.max(minX, Math.min(maxX, snapVal(clampedX, snapSize))),
                    y: Math.max(minY, Math.min(maxY, snapVal(clampedY, snapSize))),
                },
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
        if (isReadOnly || isPlacingCone) return;
        if (e.target.attrs.draggable || e.target.parent?.attrs.draggable) return;

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

    // Fine sub-grid lines (0.25m intervals) for small fields
    if (showSubGrid) {
        for (let i = 0.25; i < fW; i += 0.25) {
            // Skip whole-meter lines (drawn separately as major/minor)
            if (Math.abs(i - Math.round(i)) < 0.01) continue;
            const isHalf = Math.abs((i % 1) - 0.5) < 0.01;
            gridLines.push(
                <Line key={`sv${i}`} points={[i * SCALE, 0, i * SCALE, fieldHeightPx]}
                    stroke={isHalf ? "#B0B0B8" : "#CCCCD0"}
                    strokeWidth={Math.max(0.3, (isHalf ? 0.5 : 0.3) * strokeScale)} />
            );
        }
        for (let i = 0.25; i < fH; i += 0.25) {
            if (Math.abs(i - Math.round(i)) < 0.01) continue;
            const isHalf = Math.abs((i % 1) - 0.5) < 0.01;
            gridLines.push(
                <Line key={`sh${i}`} points={[0, i * SCALE, fieldWidthPx, i * SCALE]}
                    stroke={isHalf ? "#B0B0B8" : "#CCCCD0"}
                    strokeWidth={Math.max(0.3, (isHalf ? 0.5 : 0.3) * strokeScale)} />
            );
        }
    }

    // Major/minor grid lines
    for (let i = 0; i <= fW; i += 1) {
        const isMajor = i % majorStep === 0;
        gridLines.push(
            <Line key={`v${i}`} points={[i * SCALE, 0, i * SCALE, fieldHeightPx]} stroke={isMajor ? "#8B8B94" : "#A1A1AA"} strokeWidth={Math.max(0.5, (isMajor ? 1 : 0.75) * strokeScale)} dash={isMajor ? [] : [4, 4]} />
        );
        if (isMajor) labels.push(<Text key={`lx${i}`} x={i * SCALE - 10} y={fieldHeightPx + labelOffset * 0.4} text={`${i}m`} fontSize={labelFontSize} fill="#52525B" />);
    }
    for (let i = 0; i <= fH; i += 1) {
        const isMajor = i % majorStep === 0;
        gridLines.push(
            <Line key={`h${i}`} points={[0, i * SCALE, fieldWidthPx, i * SCALE]} stroke={isMajor ? "#8B8B94" : "#A1A1AA"} strokeWidth={Math.max(0.5, (isMajor ? 1 : 0.75) * strokeScale)} dash={isMajor ? [] : [4, 4]} />
        );
        // Y labels: flipped — canvas row i shows field value (fH - i)
        if (isMajor) labels.push(<Text key={`ly${i}`} x={-labelOffset} y={i * SCALE - 6} text={`${fH - i}m`} fontSize={labelFontSize} fill="#52525B" />);
    }

    const stageWidth = containerSize.width || totalWidth;
    const stageHeight = containerSize.height || totalHeight;

    const snapLabel = snapSize > 0
        ? (snapSize < 1 ? `${parseFloat((snapSize * 100).toFixed(1))}cm` : `${snapSize}m`)
        : 'OFF';

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
                    {/* Secret top-left corner: stop all + beep */}
                    <Rect
                        x={0} y={0} width={36} height={36}
                        fill="transparent"
                        onClick={(e) => { e.cancelBubble = true; rosBridge.stop(); rosBridge.beep(5); }}
                        onTap={(e) => { e.cancelBubble = true; rosBridge.stop(); rosBridge.beep(5); }}
                    />
                    <Rect width={fieldWidthPx} height={fieldHeightPx} fill="#F4F4F5" stroke="#8B8B94" strokeWidth={Math.max(0.5, 1.5 * strokeScale)} />

                    {/* Boundary margin zone (50cm from edges) */}
                    {(() => {
                        const m = BOUNDARY_MARGIN * SCALE;
                        return (
                            <>
                                {/* Top margin */}
                                <Rect x={0} y={0} width={fieldWidthPx} height={m} fill="#E5E5E5" opacity={0.4} listening={false} />
                                {/* Bottom margin */}
                                <Rect x={0} y={fieldHeightPx - m} width={fieldWidthPx} height={m} fill="#E5E5E5" opacity={0.4} listening={false} />
                                {/* Left margin */}
                                <Rect x={0} y={m} width={m} height={fieldHeightPx - 2 * m} fill="#E5E5E5" opacity={0.4} listening={false} />
                                {/* Right margin */}
                                <Rect x={fieldWidthPx - m} y={m} width={m} height={fieldHeightPx - 2 * m} fill="#E5E5E5" opacity={0.4} listening={false} />
                                {/* Inner boundary line */}
                                <Rect x={m} y={m} width={fieldWidthPx - 2 * m} height={fieldHeightPx - 2 * m} fill="transparent" stroke="#D4D4D8" strokeWidth={Math.max(0.5, 0.5 * strokeScale)} dash={[4, 4]} listening={false} />
                            </>
                        );
                    })()}

                    {gridLines}
                    {labels}

                    {/* Center crosshair */}
                    {(() => {
                        const cx = fieldWidthPx / 2;
                        const cy = fieldHeightPx / 2;
                        const arm = 0.15 * SCALE; // 15cm arms
                        const sw = Math.max(0.5, 0.75 * strokeScale);
                        return (
                            <>
                                <Line points={[cx - arm, cy, cx + arm, cy]} stroke="#A1A1AA" strokeWidth={sw} listening={false} />
                                <Line points={[cx, cy - arm, cx, cy + arm]} stroke="#A1A1AA" strokeWidth={sw} listening={false} />
                            </>
                        );
                    })()}


                    {/* Active Cones */}
                    {currentSession.cones.map((cone) => (
                        <ConeNode
                            key={cone.id}
                            cone={cone}
                            scale={SCALE}
                            fieldHeight={fH}
                            fieldWidth={fW}
                            snapSize={snapSize}
                            coneSize={coneSize}
                            onDragEnd={(id, x, y) => updateConePosition(currentSession.id, id, x, y)}
                            onDelete={(id) => removeCone(currentSession.id, id)}
                            imageMode={true}
                            opacity={0.8}
                            isSelected={missionConeIds.has(cone.id)}
                            onToggleSelect={robotConnected ? toggleMissionCone : undefined}
                            readOnly={isReadOnly}
                        />
                    ))}

                    {/* Collection Overlays */}
                    {collectionActive && collectionResults.length > 0 && currentSession.cones.map((cone) => {
                        const result = collectionResults.find(r => r.cone_id === cone.id);
                        if (!result) return null;
                        const cx = cone.x * SCALE;
                        const cy = fieldToCanvasY(cone.y);
                        const isTarget = cone.id === collectionTargetConeId;

                        if (isTarget) {
                            return <CollectionTargetRing key={`ct-${cone.id}`} x={cx} y={cy} size={coneSize} />;
                        }
                        if (result.status === 'collected') {
                            return (
                                <Group key={`cc-${cone.id}`} x={cx} y={cy} listening={false}>
                                    <Circle radius={coneSize * 0.6} fill="#2563EB" opacity={0.7} />
                                    {/* Checkmark */}
                                    <Line
                                        points={[-4, 0, -1, 3, 5, -4]}
                                        stroke="white"
                                        strokeWidth={2}
                                        lineCap="round"
                                        lineJoin="round"
                                    />
                                </Group>
                            );
                        }
                        if (result.status === 'missing') {
                            return (
                                <Group key={`cm-${cone.id}`} x={cx} y={cy} listening={false}>
                                    <Circle radius={coneSize * 0.6} fill="#DC6B1A" opacity={0.7} />
                                    {/* X mark */}
                                    <Line points={[-3, -3, 3, 3]} stroke="white" strokeWidth={2} lineCap="round" />
                                    <Line points={[3, -3, -3, 3]} stroke="white" strokeWidth={2} lineCap="round" />
                                </Group>
                            );
                        }
                        return null;
                    })}

                    {/* Placing Animation */}
                    {pendingCone && (
                        <PlacingConeGhost
                            x={pendingCone.x * SCALE}
                            y={fieldToCanvasY(pendingCone.y)}
                            size={coneSize}
                        />
                    )}

                    {/* Real Robot Position */}
                    {robotPose && robotConnected && (
                        <Group
                            x={robotPose.x * SCALE}
                            y={fieldToCanvasY(robotPose.y)}
                            rotation={-robotPose.theta * (180 / Math.PI)}
                        >
                            {/* Robot body */}
                            <Rect
                                width={12}
                                height={12}
                                offsetX={6}
                                offsetY={6}
                                fill="#3B82F6"
                                cornerRadius={6}
                                shadowBlur={4}
                                shadowOpacity={0.4}
                                shadowColor="#1D4ED8"
                            />
                            {/* Front direction indicator */}
                            <Line
                                points={[2, -3, 9, 0, 2, 3]}
                                fill="#93C5FD"
                                closed={true}
                            />
                            {/* Ultrasonic radar wedges */}
                            {ultrasonicReadings && Object.entries(ultrasonicReadings).map(([key, cm]) => {
                                if (cm <= 0 || cm > US_MAX_DISPLAY_CM) return null;
                                const angle = ULTRASONIC_ANGLES[key];
                                if (angle === undefined) return null;
                                const radiusPx = (cm / 100) * SCALE;
                                const { fill, stroke } = usZoneColor(cm);
                                return (
                                    <Wedge
                                        key={`us-${key}`}
                                        radius={radiusPx}
                                        angle={US_BEAM_WIDTH}
                                        rotation={angle - US_BEAM_WIDTH / 2}
                                        fill={fill}
                                        stroke={stroke}
                                        strokeWidth={1}
                                        listening={false}
                                    />
                                );
                            })}
                        </Group>
                    )}

                    {/* Obstacle avoidance state badge near robot */}
                    {robotPose && robotConnected && navAvoidanceState && navAvoidanceState !== 'clear' && (
                        <Text
                            x={robotPose.x * SCALE - 20}
                            y={fieldToCanvasY(robotPose.y) - 22}
                            text={
                                navAvoidanceState === 'hard_avoid' ? 'AVOID!' :
                                navAvoidanceState === 'steering_around' ? 'STEERING' :
                                navAvoidanceState === 'adjusting' ? 'ADJUST' : ''
                            }
                            fontSize={9}
                            fill={navAvoidanceState === 'hard_avoid' ? '#DC6B1A' : '#F59E0B'}
                            fontStyle="bold"
                            listening={false}
                        />
                    )}

                    {/* Collection phase label near robot */}
                    {robotPose && robotConnected && collectionActive && collectionPhase && (
                        <Text
                            x={robotPose.x * SCALE + 10}
                            y={fieldToCanvasY(robotPose.y) - 16}
                            text={
                                collectionPhase === 'navigating' ? 'NAV' :
                                collectionPhase === 'visual_servo' ? 'SERVO' :
                                collectionPhase === 'ramming' ? 'RAM!' :
                                collectionPhase === 'dwell' ? 'DONE' :
                                collectionPhase === 'missing' ? 'MISS' : ''
                            }
                            fontSize={10}
                            fill={collectionPhase === 'missing' ? '#DC6B1A' : '#2563EB'}
                            fontStyle="bold"
                            listening={false}
                        />
                    )}

                    {/* Ghost Cone Cursor (mousePos is in field coords, convert to canvas) */}
                    {mousePos && !isPlacingCone && (
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
                data-tour="snap-toggle"
                onClick={handleCycleSnap}
                className={`absolute bottom-3 left-3 z-10 flex items-center gap-2 px-3.5 py-2.5 rounded-xl shadow-md border text-sm font-semibold select-none transition-colors active:scale-95 ${
                    snapSize > 0
                        ? 'bg-primary/10 border-primary/30 text-primary hover:bg-primary/20'
                        : 'bg-white border-gray-300 text-gray-500 hover:bg-gray-50'
                }`}
                title="Click to cycle snap grid"
            >
                <Grid3x3 size={16} />
                <span>SNAP</span>
                <span className={`px-2 py-0.5 rounded-md text-xs font-bold ${
                    snapSize > 0 ? 'bg-primary/20 text-primary' : 'bg-gray-100 text-gray-400'
                }`}>
                    {snapLabel}
                </span>
            </button>

            {/* Bottom-right: Zoom controls */}
            <div data-tour="zoom-controls" className="absolute bottom-3 right-3 flex flex-col gap-2 z-10">
                <button
                    onClick={handleZoomIn}
                    disabled={zoom >= MAX_ZOOM}
                    className="w-12 h-12 bg-white border border-gray-300 rounded-xl shadow-md flex items-center justify-center text-2xl font-bold text-gray-700 hover:bg-gray-50 active:bg-gray-100 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed transition-all select-none"
                >
                    +
                </button>
                <button
                    onClick={handleZoomOut}
                    disabled={zoom <= MIN_ZOOM}
                    className="w-12 h-12 bg-white border border-gray-300 rounded-xl shadow-md flex items-center justify-center text-2xl font-bold text-gray-700 hover:bg-gray-50 active:bg-gray-100 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed transition-all select-none"
                >
                    −
                </button>
                <button
                    onClick={handleFitView}
                    className="w-12 h-12 bg-white border border-gray-300 rounded-xl shadow-md flex items-center justify-center text-xs font-bold text-gray-700 hover:bg-gray-50 active:bg-gray-100 active:scale-95 transition-all select-none"
                    title="Fit to view"
                >
                    FIT
                </button>
            </div>
        </div>
    );
};
