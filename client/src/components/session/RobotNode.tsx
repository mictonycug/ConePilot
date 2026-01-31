import React, { useEffect, useRef } from 'react';
import { Group, Rect } from 'react-konva';
import Konva from 'konva';
import { useSessionStore } from '../../store/useSessionStore';

interface RobotNodeProps {
    x: number;
    y: number;
    scale: number;
    path?: { x: number, y: number }[];
}

export const RobotNode: React.FC<RobotNodeProps> = ({ x, y, scale, path }) => {
    const groupRef = useRef<Konva.Group>(null);
    const { updateSimulationStats, updateTelemetry, addSequenceLog, clearSequenceLogs, addPlacementHistory, setSimulationStatus } = useSessionStore();

    // Keep track of tween refs and timeouts
    const activeTweens = useRef<Konva.Tween[]>([]);
    const timeouts = useRef<any[]>([]);

    const cleanupParams = () => {
        console.log('[RobotNode] CleanupParams called (clearing tweens/timeouts)');
        activeTweens.current.forEach(t => t.destroy());
        activeTweens.current = [];
        timeouts.current.forEach(t => clearTimeout(t));
        timeouts.current = [];
    };

    // Simulate Hardware Function
    const simulateHardwareStep = (name: string, durationMs: number, mechVelocity: number): Promise<void> => {
        return new Promise((resolve) => {
            let elapsed = 0;
            const stepInterval = 100;

            const interval = setInterval(() => {
                elapsed += stepInterval;
                updateTelemetry({ mechanismVelocity: mechVelocity + (Math.random() * 0.1 - 0.05) });

                if (elapsed >= durationMs) {
                    clearInterval(interval);
                    addSequenceLog({ step: name, timeTaken: durationMs / 1000 });
                    updateTelemetry({ mechanismVelocity: 0 });
                    resolve();
                }
            }, stepInterval);

            timeouts.current.push(interval);
        });
    };

    const runPlacementSequence = async (coneIndex: number) => {
        console.log('[RobotNode] Starting Placement Sequence for Cone', coneIndex);
        setSimulationStatus('PLACING');
        console.log('[RobotNode] Set Status to PLACING');
        clearSequenceLogs();
        const startTime = Date.now();

        // 1. Lowering Claw
        await simulateHardwareStep("LOWERING_CLAW_SERVO_A1", 1200, 0.4);

        // 2. Activating Claw
        await simulateHardwareStep("ENGAGING_GRIPPER_SOLENOID", 600, 0.1);

        // 3. Lifting Cone
        await simulateHardwareStep("LIFTING_PAYLOAD_Z_AXIS", 1000, 0.35);

        // 4. Activating Spiral
        await simulateHardwareStep("ACTIVATING_SPIRAL_GYRO", 800, 0.8);

        // 5. Secure
        await simulateHardwareStep("PAYLOAD_SECURED_CONFIRMED", 200, 0);

        const totalTime = (Date.now() - startTime) / 1000;
        console.log('[RobotNode] Placement Sequence Complete. Total Time:', totalTime);

        // Save History
        addPlacementHistory({
            coneIndex: coneIndex,
            totalTime: totalTime,
            logs: useSessionStore.getState().currentSequenceLogs
        });

        setSimulationStatus('MOVING');
        console.log('[RobotNode] Set Status back to MOVING');
    };


    // Path Movement Animation
    useEffect(() => {
        console.log('[RobotNode] Effect MOUNT/UPDATE. Path Length:', path?.length);
        cleanupParams();

        if (!path || path.length < 2 || !groupRef.current) {
            console.log('[RobotNode] Path invalid, aborting.');
            return;
        }

        const node = groupRef.current;
        const speed = 50;

        // Initialize position
        node.position({ x: path[0].x * scale, y: path[0].y * scale });
        setSimulationStatus('MOVING'); // Init status
        console.log('[RobotNode] Initial Status set to MOVING');

        const playNextSegment = async (index: number) => {
            console.log('[RobotNode] playNextSegment', index);
            if (index >= path.length - 1) {
                console.log('[RobotNode] Path Completed');
                setSimulationStatus('COMPLETED');
                updateSimulationStats({ etaSeconds: 0 });
                updateTelemetry({ velocity: 0 });
                return;
            }

            const p1 = path[index];
            const p2 = path[index + 1];
            const startPt = { x: p1.x * scale, y: p1.y * scale };
            const endPt = { x: p2.x * scale, y: p2.y * scale };
            const distPx = Math.sqrt(Math.pow(endPt.x - startPt.x, 2) + Math.pow(endPt.y - startPt.y, 2));

            // MOVEMENT TWEEN
            const angle = Math.atan2(endPt.y - startPt.y, endPt.x - startPt.x) * (180 / Math.PI);

            // Rotate
            console.log('[RobotNode] Rotating...');
            await new Promise<void>(resolve => {
                const t = new Konva.Tween({
                    node: node,
                    rotation: angle,
                    duration: 0.3,
                    onFinish: () => resolve()
                });
                activeTweens.current.push(t);
                t.play();
            });

            // Move
            console.log('[RobotNode] Moving...');
            const duration = distPx / speed;
            updateTelemetry({ velocity: (speed / scale) });

            await new Promise<void>(resolve => {
                const t = new Konva.Tween({
                    node: node,
                    x: endPt.x,
                    y: endPt.y,
                    duration: duration,
                    easing: Konva.Easings.Linear,
                    onFinish: () => resolve()
                });
                activeTweens.current.push(t);
                t.play();
            });

            // Arrived at destination
            console.log('[RobotNode] Arrived. Updating stats.');
            updateTelemetry({ velocity: 0 });
            updateSimulationStats({
                distanceTraveled: useSessionStore.getState().simulationStats.distanceTraveled + (distPx / scale),
                conesPlaced: index + 1
            });

            // RUN PLACEMENT SEQUENCE
            console.log('[RobotNode] Calling runPlacementSequence...');
            await runPlacementSequence(index + 1);

            // Continue
            playNextSegment(index + 1);
        };

        playNextSegment(0);

        return () => {
            console.log('[RobotNode] Effect UNMOUNT/CLEANUP');
            cleanupParams();
        };

    }, [path, scale]);

    return (
        <Group ref={groupRef} x={x * scale} y={y * scale}>
            <Group offsetX={20} offsetY={15}>
                <Rect x={0} y={0} width={10} height={6} fill="#333" cornerRadius={2} />
                <Rect x={30} y={0} width={10} height={6} fill="#333" cornerRadius={2} />
                <Rect x={0} y={24} width={10} height={6} fill="#333" cornerRadius={2} />
                <Rect x={30} y={24} width={10} height={6} fill="#333" cornerRadius={2} />
                <Rect x={4} y={3} width={32} height={24} fill="#059669" cornerRadius={4} shadowBlur={5} shadowOpacity={0.3} />
                <Rect x={26} y={6} width={6} height={18} fill="#A7F3D0" cornerRadius={1} />
            </Group>
        </Group>
    );
};
