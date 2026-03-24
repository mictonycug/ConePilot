export interface TourStep {
    target: string;       // CSS selector (data-tour attribute)
    title: string;
    body: string;
    placement: 'top' | 'bottom' | 'left' | 'right';
    isModal?: boolean;    // true = centered card, no DOM target
    advanceOn?: 'click';
}

export const DASHBOARD_TOUR: TourStep[] = [
    {
        target: '[data-tour="new-layout"]',
        title: 'Create a Layout',
        body: 'Tap here to create a new cone layout. Give it a name and you\'re ready to start placing cones.',
        placement: 'bottom',
        advanceOn: 'click',
    },
];

export const SESSION_TOUR: TourStep[] = [
    {
        target: '[data-tour="snap-toggle"]',
        title: 'Snap Grid',
        body: 'Tap to cycle the snap grid (OFF \u2192 10cm \u2192 25cm \u2192 50cm). Snapping helps you place cones at precise positions.',
        placement: 'top',
    },
    {
        target: '[data-tour="zoom-controls"]',
        title: 'Zoom Controls',
        body: 'Use + / \u2212 to zoom in and out, or FIT to reset the view.',
        placement: 'left',
    },
    {
        target: '',
        title: 'Place a Cone',
        body: 'Tap anywhere on the field canvas to place a cone.',
        placement: 'bottom',
        isModal: true,
    },
    {
        target: '',
        title: 'Move a Cone',
        body: 'Drag any cone to reposition it on the field.',
        placement: 'bottom',
        isModal: true,
    },
    {
        target: '',
        title: 'Delete a Cone',
        body: 'Tap a cone to delete it from the field.',
        placement: 'bottom',
        isModal: true,
    },
    {
        target: '[data-tour="start-placing"]',
        title: 'Start Placing',
        body: 'When you\u2019re ready, tap here to send the robot along the optimized path to place each cone.',
        placement: 'top',
    },
    {
        target: '[data-tour="collect-cones"]',
        title: 'Collect Cones',
        body: 'After a drill, tap here to have the robot drive back and collect all the cones.',
        placement: 'top',
    },
];
