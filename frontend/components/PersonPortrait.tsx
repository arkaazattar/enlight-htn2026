"use client";

import { useState } from "react";
import { User } from "lucide-react";
import { Person, personImageUrl } from "../lib/api";

interface PersonPortraitProps {
    person: Person;
    className: string;
    imageClassName: string;
    fallbackClassName: string;
}

export function PersonPortrait({ person, className, imageClassName, fallbackClassName }: PersonPortraitProps) {
    const source = personImageUrl(person);
    const [failedSource, setFailedSource] = useState<string | null>(null);
    const showImage = person.image_paths.length > 0 && failedSource !== source;

    return (
        <div className={className}>
            {showImage ? (
                // The image is served by the separate backend and can disappear after a record is loaded.
                // eslint-disable-next-line @next/next/no-img-element
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
