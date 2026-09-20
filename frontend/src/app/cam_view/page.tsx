"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { ArrowLeft, RefreshCw, Maximize, Video, Mic, MicOff, Activity, MapPin } from "lucide-react";
import styles from "./cam_view.module.css";
import { GoogleMapIntegration } from "../../../components/Map/Map";
import { checkWandering, checkIdle, distanceToPolyline } from "../../../lib/tracking";

const DESTINATIONS = [
    { name: "UWaterloo Pearl", lat: 43.4735, lng: -80.5373 },
    { name: "Lazaridis Building", lat: 43.4741, lng: -80.5284 },
    { name: "Sobeys", lat: 43.4800, lng: -80.5212 }
];

export default function CamViewPage() {
    const [isStreaming, setIsStreaming] = useState(true);
    const [fps, setFps] = useState(0);
    const [micOn, setMicOn] = useState(true);

    // Map & Tracking State
    const [currentPos, setCurrentPos] = useState<{lat: number, lng: number} | null>(null);
    const [destination, setDestination] = useState<{name: string, lat: number, lng: number} | null>(null);
    const [route, setRoute] = useState<{lat: number, lng: number}[] | null>(null);
    const [history, setHistory] = useState<{lat: number, lng: number}[]>([]);
    
    const [trackingStatus, setTrackingStatus] = useState("");
    const [trackingData, setTrackingData] = useState({ heading: 0, accel: "Idle" });

    // Simulate backend connection for demo purposes
    useEffect(() => {
        const interval = setInterval(() => {
            setFps(Math.floor(Math.random() * 5) + 25); // Simulate 25-30 FPS
        }, 1000);
        return () => clearInterval(interval);
    }, []);

    // Connect to WebSocket for UDP location data
    useEffect(() => {
        const ws = new WebSocket("ws://localhost:8000/ws/location");
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.lat !== undefined && data.lon !== undefined) {
                    const pos = { lat: data.lat, lng: data.lon };
                    
                    if (data.lat === 0.0 && data.lon === 0.0) {
                        setTrackingStatus("");
                        setTrackingData({ heading: data.heading || 0, accel: data.accel || "Acquiring..." });
                        return;
                    }
                    
                    setCurrentPos(pos);
                    setTrackingData({ heading: data.heading || 0, accel: data.accel || "Moving" });
                    
                    setHistory(prev => {
                        const next = [...prev, pos];
                        if (next.length > 20) next.shift(); // keep last 20 points
                        return next;
                    });
                }
            } catch (e) {
                console.error("Failed to parse location data", e);
            }
        };
        return () => ws.close();
    }, []);

    // Tracking Logic
    useEffect(() => {
        if (!currentPos) return;

        const destName = destination ? destination.name : "your destination";

        if (checkIdle(history)) {
            setTrackingStatus(`You are not moving. Did you change your mind about going to ${destName}?`);
            return;
        }

        if (checkWandering(history)) {
            setTrackingStatus(`You seem to be wandering. Are you lost trying to find ${destName}?`);
            return;
        }

        if (route && route.length > 0) {
            const dist = distanceToPolyline(currentPos, route);
            if (dist > 35) {
                setTrackingStatus(`You are not on the right way to ${destName}. Need a re-route?`);
            } else {
                setTrackingStatus(""); // On Route, show nothing
            }
        } else {
            setTrackingStatus(""); // No destination, show nothing
        }
    }, [currentPos, route, history, destination]);

    const handleRefresh = () => {
        setIsStreaming(false);
        setFps(0);
        setTimeout(() => setIsStreaming(true), 800);
    };

    const handleSelectDestination = (dest: typeof DESTINATIONS[0]) => {
        setDestination({ name: dest.name, lat: dest.lat, lng: dest.lng });
        // In a real app, you would fetch from Google Routes API here and setRoute()
        // For now, we just draw a straight line route for demonstration
        if (currentPos) {
            setRoute([currentPos, { lat: dest.lat, lng: dest.lng }]);
        }
    };

    return (
        <div className={styles.container}>
            <header className={styles.header}>
                <Link href="/" className={styles.backButton}>
                    <ArrowLeft className="w-5 h-5" />
                    <span>Back to Main</span>
                </Link>
            </header>

            <div className={styles.mainContent}>
                <div className={styles.streamWrapper}>
                    {isStreaming ? (
                        <>
                            <img 
                                src="http://localhost:8001/video_feed" 
                                className={styles.videoElement} 
                                alt="Live Tracking Stream" 
                                onError={(e) => {
                                    (e.target as HTMLImageElement).style.display = 'none';
                                }}
                            />

                            <div className={styles.hudOverlay}>
                                <div className={styles.hudLeft}>
                                    <div className={styles.badge}>
                                        <div className={styles.activeDot} />
                                        <span>Tracker Active</span>
                                    </div>
                                    <div className={styles.badge}>
                                        <Activity className="w-4 h-4 text-emerald-400" />
                                        <span>{fps} FPS</span>
                                    </div>
                                </div>
                                <div className={styles.hudRight}>
                                    <div className={styles.badge}>
                                        {micOn ? (
                                            <Mic className="w-4 h-4 text-emerald-400" />
                                        ) : (
                                            <MicOff className="w-4 h-4 text-red-400" />
                                        )}
                                        <span>MIC: {micOn ? 'ON' : 'OFF'}</span>
                                    </div>
                                </div>
                            </div>
                            
                            {trackingStatus && (
                                <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-black/70 backdrop-blur-md px-8 py-4 rounded-full border border-red-500/50 z-20 pointer-events-none shadow-2xl">
                                    <span className="text-xl font-bold tracking-wide text-red-400">
                                        {trackingStatus}
                                    </span>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className={styles.placeholderStream}>
                            <div className={styles.offlineDot} />
                            <p>Connecting to tracker engine...</p>
                        </div>
                    )}

                    <div className={styles.controlPanel}>
                        <button onClick={handleRefresh} className={styles.controlButton} title="Refresh Stream">
                            <RefreshCw className="w-5 h-5" />
                        </button>
                        <button onClick={() => setMicOn(!micOn)} className={styles.controlButton} title="Toggle Mic Status">
                            {micOn ? <Mic className="w-5 h-5" /> : <MicOff className="w-5 h-5" />}
                        </button>
                        <button className={styles.controlButton} title="Fullscreen">
                            <Maximize className="w-5 h-5" />
                        </button>
                    </div>
                </div>

                <div className={styles.sidebar}>
                    <div className={styles.sidebarHeader}>
                        Map & Navigation
                    </div>
                    
                    <div className="h-64 border-b border-[var(--border)] shrink-0">
                        <GoogleMapIntegration 
                            currentPos={currentPos} 
                            destination={destination}
                            route={route}
                        />
                    </div>

                    <div className={styles.sidebarContent}>
                        <div className="bg-zinc-800 p-4 rounded-lg border border-zinc-700 shadow-sm text-sm">
                            <h3 className="font-semibold text-white mb-2 flex items-center gap-2">
                                <Activity className="w-4 h-4 text-blue-400" />
                                Live Status
                            </h3>
                            <div className="flex justify-between items-center mb-1">
                                <span className="text-zinc-400">Status:</span>
                                <span className={`font-medium ${trackingStatus.includes('Wandering') || trackingStatus.includes('Off Course') ? 'text-red-400' : 'text-emerald-400'}`}>
                                    {trackingStatus}
                                </span>
                            </div>
                            <div className="flex justify-between items-center mb-1">
                                <span className="text-zinc-400">Heading:</span>
                                <span className="text-zinc-200">{trackingData.heading.toFixed(1)}°</span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-zinc-400">Accel:</span>
                                <span className="text-zinc-200">{trackingData.accel}</span>
                            </div>
                        </div>

                        <div>
                            <h3 className="font-semibold text-zinc-300 mb-3 mt-2">Destinations</h3>
                            <div className="flex flex-col gap-2">
                                {DESTINATIONS.map(dest => (
                                    <button 
                                        key={dest.name}
                                        onClick={() => handleSelectDestination(dest)}
                                        className="flex items-center gap-3 p-3 bg-[var(--background)] hover:bg-zinc-800 border border-[var(--border)] rounded-md transition text-left"
                                    >
                                        <MapPin className="w-4 h-4 text-red-500 shrink-0" />
                                        <span className="text-sm font-medium">{dest.name}</span>
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
