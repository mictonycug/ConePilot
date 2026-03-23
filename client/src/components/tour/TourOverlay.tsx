import React, { useEffect, useState, useCallback } from 'react';
import type { TourStep } from './tourSteps';

interface TourOverlayProps {
    step: TourStep;
    currentIndex: number;
    totalSteps: number;
    onNext: () => void;
    onSkip: () => void;
}

interface Rect {
    top: number;
    left: number;
    width: number;
    height: number;
}

const PAD = 8; // spotlight padding around target element

export const TourOverlay: React.FC<TourOverlayProps> = ({ step, currentIndex, totalSteps, onNext, onSkip }) => {
    const [targetRect, setTargetRect] = useState<Rect | null>(null);

    const measure = useCallback(() => {
        if (step.isModal || !step.target) {
            setTargetRect(null);
            return;
        }
        const el = document.querySelector(step.target);
        if (!el) {
            setTargetRect(null);
            return;
        }
        const r = el.getBoundingClientRect();
        setTargetRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    }, [step.target, step.isModal]);

    useEffect(() => {
        measure();
        window.addEventListener('resize', measure);
        window.addEventListener('scroll', measure, true);
        return () => {
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
        };
    }, [measure]);

    // Auto-advance when user clicks the target element
    useEffect(() => {
        if (!step.advanceOn || !step.target) return;
        const el = document.querySelector(step.target);
        if (!el) return;
        const handler = () => {
            // Small delay so the click action itself completes first
            setTimeout(onNext, 50);
        };
        el.addEventListener('click', handler, true);
        return () => el.removeEventListener('click', handler, true);
    }, [step.target, step.advanceOn, onNext]);

    const isLast = currentIndex === totalSteps - 1;

    // ── Modal step (no target) ──
    if (step.isModal || !targetRect) {
        return (
            <div className="fixed inset-0 z-[70] flex items-center justify-center pointer-events-none">
                <div className="bg-white rounded-2xl shadow-2xl p-6 max-w-sm w-[90vw] mx-4 pointer-events-auto">
                    <p className="text-xs text-gray-400 mb-2">{currentIndex + 1} of {totalSteps}</p>
                    <h3 className="text-lg font-bold text-gray-900 mb-2">{step.title}</h3>
                    <p className="text-sm text-gray-600 leading-relaxed mb-5">{step.body}</p>
                    <div className="flex items-center justify-between">
                        <button onClick={onSkip} className="text-sm text-gray-400 hover:text-gray-600 transition-colors">
                            Skip tour
                        </button>
                        <button
                            onClick={onNext}
                            className="px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:bg-opacity-90 transition-colors"
                        >
                            {isLast ? 'Got it' : 'Next'}
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // ── Spotlight step ──
    const spot = {
        top: targetRect.top - PAD,
        left: targetRect.left - PAD,
        width: targetRect.width + PAD * 2,
        height: targetRect.height + PAD * 2,
    };

    // Tooltip positioning
    const tooltip = computeTooltipPos(spot, step.placement);

    return (
        <>
            {/* Tooltip */}
            <div
                className="fixed z-[70] bg-white rounded-xl shadow-xl p-4 max-w-xs w-[85vw]"
                style={{
                    top: tooltip.top,
                    left: tooltip.left,
                    transition: 'top 300ms ease, left 300ms ease',
                }}
            >
                <p className="text-xs text-gray-400 mb-1">{currentIndex + 1} of {totalSteps}</p>
                <h3 className="text-base font-bold text-gray-900 mb-1">{step.title}</h3>
                <p className="text-sm text-gray-600 leading-relaxed mb-4">{step.body}</p>
                <div className="flex items-center justify-between">
                    <button onClick={onSkip} className="text-sm text-gray-400 hover:text-gray-600 transition-colors">
                        Skip tour
                    </button>
                    <button
                        onClick={onNext}
                        className="px-5 py-2 bg-primary text-white text-sm font-semibold rounded-lg hover:bg-opacity-90 transition-colors"
                    >
                        {isLast ? 'Got it' : 'Next'}
                    </button>
                </div>
            </div>
        </>
    );
};

function computeTooltipPos(spot: Rect, placement: TourStep['placement']): { top: number; left: number } {
    const GAP = 12;
    const TOOLTIP_W = 300; // approximate max width
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let top = 0;
    let left = 0;

    switch (placement) {
        case 'bottom':
            top = spot.top + spot.height + GAP;
            left = spot.left + spot.width / 2 - TOOLTIP_W / 2;
            break;
        case 'top':
            top = spot.top - GAP - 200; // approximate tooltip height
            left = spot.left + spot.width / 2 - TOOLTIP_W / 2;
            break;
        case 'left':
            top = spot.top + spot.height / 2 - 80;
            left = spot.left - TOOLTIP_W - GAP;
            break;
        case 'right':
            top = spot.top + spot.height / 2 - 80;
            left = spot.left + spot.width + GAP;
            break;
    }

    // Clamp to viewport
    left = Math.max(8, Math.min(left, vw - TOOLTIP_W - 8));
    top = Math.max(8, Math.min(top, vh - 200));

    return { top, left };
}
