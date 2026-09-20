"use client";

import { useEffect, useRef, useState } from 'react';
import { setOptions, importLibrary } from '@googlemaps/js-api-loader';
import { useTheme } from 'next-themes';
import { darkMapStyles, lightMapStyles } from './mapStyles';

const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;

interface MapProps {
    currentPos?: { lat: number; lng: number } | null;
    destination?: { lat: number; lng: number } | null;
    route?: { lat: number; lng: number }[] | null;
}

export function GoogleMapIntegration({ currentPos, destination, route }: MapProps) {
    const mapElement = useRef<HTMLDivElement>(null);
    const map = useRef<google.maps.Map | null>(null);
    const markerRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
    const destMarkerRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
    const polylineRef = useRef<google.maps.Polyline | null>(null);
    
    const { resolvedTheme } = useTheme();
    const [error, setError] = useState<string | null>(
        API_KEY ? null : 'Google Maps API key is missing.'
    );

    // Initialize Map
    useEffect(() => {
        if (!API_KEY) return;
        if (!mapElement.current) return;

        let active = true;
        setOptions({ key: API_KEY, v: "weekly" });

        Promise.all([
            importLibrary('maps'),
            importLibrary('marker')
        ])
        .then(([{ Map }, { AdvancedMarkerElement }]) => {
            if (active && mapElement.current && !map.current) {
                map.current = new Map(mapElement.current, {
                    center: currentPos || { lat: 43.4735, lng: -80.5373 }, // Default Waterloo
                    zoom: 16,
                    mapId: process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID || "4fa8b8f6998a55b3b359871e", // Required for AdvancedMarkerElement
                    styles: document.documentElement.classList.contains('dark') ? darkMapStyles : lightMapStyles,
                    disableDefaultUI: true,
                });
            }
        })
        .catch(() => {
            if (active) setError('Google Maps could not load.');
        });

        return () => {
            active = false;
        };
    }, []);

    // Handle Theme changes
    useEffect(() => {
        map.current?.setOptions({ styles: resolvedTheme === 'dark' ? darkMapStyles : lightMapStyles });
    }, [resolvedTheme]);

    // Handle Current Position Marker
    useEffect(() => {
        if (!map.current || !currentPos) return;
        
        const updateMarker = async () => {
            const { AdvancedMarkerElement } = await importLibrary('marker') as google.maps.MarkerLibrary;
            
            if (!markerRef.current) {
                const pinImg = document.createElement('div');
                pinImg.className = "w-4 h-4 bg-blue-500 rounded-full border-2 border-white shadow-[0_0_10px_rgba(59,130,246,0.8)]";
                
                markerRef.current = new AdvancedMarkerElement({
                    map: map.current,
                    position: currentPos,
                    content: pinImg,
                    title: "Current Location"
                });
            } else {
                markerRef.current.position = currentPos;
            }
            map.current?.panTo(currentPos);
        };
        updateMarker();
    }, [currentPos]);

    // Handle Destination Marker
    useEffect(() => {
        if (!map.current || !destination) {
            if (destMarkerRef.current) {
                destMarkerRef.current.map = null;
                destMarkerRef.current = null;
            }
            return;
        }
        
        const updateDestMarker = async () => {
            const { AdvancedMarkerElement } = await importLibrary('marker') as google.maps.MarkerLibrary;
            if (!destMarkerRef.current) {
                const pinImg = document.createElement('div');
                pinImg.className = "w-5 h-5 bg-red-500 rounded-full border-2 border-white flex items-center justify-center font-bold text-white text-[10px]";
                pinImg.innerText = "D";

                destMarkerRef.current = new AdvancedMarkerElement({
                    map: map.current,
                    position: destination,
                    content: pinImg,
                    title: "Destination"
                });
            } else {
                destMarkerRef.current.position = destination;
            }
        };
        updateDestMarker();
    }, [destination]);

    // Handle Route Polyline
    useEffect(() => {
        if (!map.current) return;
        
        if (!route || route.length === 0) {
            if (polylineRef.current) {
                polylineRef.current.setMap(null);
                polylineRef.current = null;
            }
            return;
        }
        
        const updatePolyline = async () => {
            const { Polyline } = await importLibrary('maps') as google.maps.MapsLibrary;
            if (!polylineRef.current) {
                polylineRef.current = new Polyline({
                    path: route,
                    geodesic: true,
                    strokeColor: '#3b82f6', // blue-500
                    strokeOpacity: 0.8,
                    strokeWeight: 4,
                    map: map.current
                });
            } else {
                polylineRef.current.setPath(route);
            }
        };
        updatePolyline();
    }, [route]);


    if (error) return <div role="alert" className="flex h-full items-center justify-center p-4 text-sm text-red-400 bg-zinc-900">{error}</div>;

    return <div ref={mapElement} className="h-full w-full rounded-md overflow-hidden" />;
}
