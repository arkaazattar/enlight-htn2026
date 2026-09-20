export function getDistance(p1: {lat: number, lng: number}, p2: {lat: number, lng: number}): number {
    const R = 6371e3; // metres
    const φ1 = p1.lat * Math.PI/180; // φ, λ in radians
    const φ2 = p2.lat * Math.PI/180;
    const Δφ = (p2.lat-p1.lat) * Math.PI/180;
    const Δλ = (p2.lng-p1.lng) * Math.PI/180;

    const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
            Math.cos(φ1) * Math.cos(φ2) *
            Math.sin(Δλ/2) * Math.sin(Δλ/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

    return R * c; // in metres
}

export function checkWandering(history: {lat: number, lng: number}[], thresholdRadius: number = 30, minDistance: number = 60): boolean {
    if (history.length < 5) return false;
    
    let totalDist = 0;
    for (let i = 1; i < history.length; i++) {
        totalDist += getDistance(history[i-1], history[i]);
    }
    
    const start = history[0];
    const end = history[history.length - 1];
    const netDist = getDistance(start, end);
    
    // Wandering if walked more than minDistance but net displacement is small
    return totalDist > minDistance && netDist < thresholdRadius;
}

export function checkIdle(history: {lat: number, lng: number}[], idleDistanceThreshold: number = 8): boolean {
    if (history.length < 15) return false;
    
    const startPos = history[0];
    let maxDisplacement = 0;
    
    for (let i = 1; i < history.length; i++) {
        const dist = getDistance(startPos, history[i]);
        if (dist > maxDisplacement) {
            maxDisplacement = dist;
        }
    }
    
    // If they haven't strayed more than 8 meters from where they were 15 updates ago
    return maxDisplacement < idleDistanceThreshold;
}

// Distance from point to polyline segment (basic approximation for small distances)
export function pointToSegmentDistance(p: {lat: number, lng: number}, v: {lat: number, lng: number}, w: {lat: number, lng: number}) {
    // Treat lat/lng as flat coords (ok for small distances) to find projection
    // Then use haversine to get actual distance to that projection.
    // Convert to meters approximation: 1 deg lat ≈ 111km, 1 deg lng ≈ 111km * cos(lat)
    const lat2m = 111320;
    const lng2m = 111320 * Math.cos(p.lat * Math.PI / 180);
    
    const px = p.lng * lng2m;
    const py = p.lat * lat2m;
    const vx = v.lng * lng2m;
    const vy = v.lat * lat2m;
    const wx = w.lng * lng2m;
    const wy = w.lat * lat2m;

    const l2 = Math.pow(wx - vx, 2) + Math.pow(wy - vy, 2);
    if (l2 === 0) return getDistance(p, v);
    
    let t = ((px - vx) * (wx - vx) + (py - vy) * (wy - vy)) / l2;
    t = Math.max(0, Math.min(1, t));
    
    const projLat = v.lat + t * (w.lat - v.lat);
    const projLng = v.lng + t * (w.lng - v.lng);
    
    return getDistance(p, {lat: projLat, lng: projLng});
}

export function distanceToPolyline(p: {lat: number, lng: number}, polyline: {lat: number, lng: number}[]): number {
    if (polyline.length === 0) return Infinity;
    if (polyline.length === 1) return getDistance(p, polyline[0]);
    
    let minDist = Infinity;
    for (let i = 0; i < polyline.length - 1; i++) {
        const d = pointToSegmentDistance(p, polyline[i], polyline[i+1]);
        if (d < minDist) minDist = d;
    }
    return minDist;
}
