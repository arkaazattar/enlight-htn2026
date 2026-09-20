"use client";

import { useState } from "react";
import { User } from "lucide-react";
import { type Person } from "../lib/api";
import { SERVER_URL } from "../lib/config";

interface PersonPortraitProps {
    person: Person;
    className: string;
    imageClassName: string;
    fallbackClassName: string;
}

export function PersonPortrait({ person, className, imageClassName, fallbackClassName }: PersonPortraitProps) {
    const imagePath = person.picture_ids?.[0] || "";
    const version = imagePath ? `?v=${encodeURIComponent(imagePath)}` : "";
    const source = `${SERVER_URL}/people/${encodeURIComponent(person.id)}/image${version}`;

    const [failedSource, setFailedSource] = useState<string | null>(null);
    const showImage = person.picture_ids && person.picture_ids.length > 0 && failedSource !== source;

    return (
        <div className={className}>
            {showImage ? (
                <img
                    src={source}
                    alt={`Portrait of ${person.label}`}
                    className={imageClassName}
                    onError={() => setFailedSource(source)}
                />
            ) : (
                <User aria-hidden="true" className={fallbackClassName} />
            )}
        </div>
    );
}
