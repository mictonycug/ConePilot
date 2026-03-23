import { useState, useCallback } from 'react';
import type { TourStep } from '../components/tour/tourSteps';

export function useTour(storageKey: string, steps: TourStep[]) {
    const [active, setActive] = useState(() => {
        try {
            return !localStorage.getItem(storageKey);
        } catch {
            return false;
        }
    });
    const [currentIndex, setCurrentIndex] = useState(0);

    const finish = useCallback(() => {
        setActive(false);
        try {
            localStorage.setItem(storageKey, '1');
        } catch { /* quota exceeded – silently ignore */ }
    }, [storageKey]);

    const next = useCallback(() => {
        if (currentIndex < steps.length - 1) {
            setCurrentIndex(i => i + 1);
        } else {
            finish();
        }
    }, [currentIndex, steps.length, finish]);

    const skip = useCallback(() => {
        finish();
    }, [finish]);

    return {
        active,
        currentStep: steps[currentIndex] as TourStep | undefined,
        currentIndex,
        totalSteps: steps.length,
        next,
        skip,
    };
}
