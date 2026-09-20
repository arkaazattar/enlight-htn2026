"use client";

import { useEffect, useRef, useState } from 'react';
import { setOptions, importLibrary } from '@googlemaps/js-api-loader';
import { useTheme } from 'next-themes';
import { darkMapStyles, lightMapStyles } from './mapStyles';

const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;

export function GoogleMapIntegration(){
    const mapElement = useRef<HTMLDivElement>(null);
    const map = useRef<google.maps.Map | null>(null);
    const { resolvedTheme } = useTheme();
    const [error, setError] = useState<string | null>(
        API_KEY ? null : 'Google Maps API key is missing.'
    );

    useEffect(() => {
        map.current?.setOptions({ styles: resolvedTheme === 'dark' ? darkMapStyles : lightMapStyles });
    }, [resolvedTheme]);

    useEffect(() => {
        if (!API_KEY) return;
        if (!mapElement.current) return;

        let active = true;
        setOptions({ key: API_KEY });

        void importLibrary('maps')
            .then(({ Map }) => {
                if (active && mapElement.current) {
                    map.current = new Map(mapElement.current, {
                        center: { lat: 48.8566, lng: 2.3522 },
                        zoom: 3,
                        styles: document.documentElement.classList.contains('dark') ? darkMapStyles : lightMapStyles,
                    });
                }
            })
            .catch(() => {
                if (active) setError('Google Maps could not load.');
            });

        return () => {
            active = false;
            map.current = null;
        };
    }, []);

    if (error) return <div role="alert" className="flex h-full items-center justify-center p-4 text-sm">{error}</div>;

    return <div ref={mapElement} className="h-full w-full" />;
}
