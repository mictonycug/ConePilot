// Basic Nearest Neighbor TSP implementation

export interface Point {
    id: string;
    x: number;
    y: number;
}

function distance(a: Point, b: Point): number {
    return Math.sqrt(Math.pow(a.x - b.x, 2) + Math.pow(a.y - b.y, 2));
}

export function calculateOptimalPath<T extends Point>(
    points: T[],
    startPosition: Point = { id: 'start', x: 0, y: 0 }
): T[] {
    if (points.length === 0) return [];
    if (points.length === 1) return points;

    const result: T[] = [];
    const remaining = [...points];
    let current = startPosition;

    while (remaining.length > 0) {
        let nearestIndex = 0;
        let nearestDistance = distance(current, remaining[0]);

        for (let i = 1; i < remaining.length; i++) {
            const d = distance(current, remaining[i]);
            if (d < nearestDistance) {
                nearestDistance = d;
                nearestIndex = i;
            }
        }

        current = remaining[nearestIndex];
        result.push(remaining[nearestIndex]);
        remaining.splice(nearestIndex, 1);
    }

    return result;
}
