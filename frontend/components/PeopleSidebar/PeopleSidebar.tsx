"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchPeople, type Person } from "../../lib/api";
import { PersonPortrait } from "../PersonPortrait";
import styles from "./PeopleSidebar.module.css";

type PeopleResult = {
    requestKey: string;
    people?: Person[];
    error?: string;
};

export function PeopleSidebar({ refreshKey = 0 }: { refreshKey?: number }) {
    const [retryKey, setRetryKey] = useState(0);
    const [result, setResult] = useState<PeopleResult | null>(null);
    const requestKey = `${refreshKey}:${retryKey}`;

    useEffect(() => {
        const controller = new AbortController();
        fetchPeople(controller.signal)
            .then((people) => {
                if (!controller.signal.aborted) setResult({ requestKey, people });
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    setResult({ requestKey, error: "Could not load people. Check the backend and try again." });
                }
            });
        return () => controller.abort();
    }, [requestKey]);

    const current = result?.requestKey === requestKey ? result : null;
    if (!current) {
        return <p className={styles.status} role="status">Loading people…</p>;
    }
    if (current.error) {
        return (
            <div className={styles.status} role="alert">
                <p>{current.error}</p>
                <button type="button" className={styles.retry} onClick={() => setRetryKey(value => value + 1)}>
                    Try again
                </button>
            </div>
        );
    }
    if (!current.people?.length) {
        return <p className={styles.status}>No enrolled people yet.</p>;
    }

    return (
        <div className={`w-full h-full overflow-y-auto ${styles.sidebar}`}>
            <div className={`grid grid-cols-3 w-full ${styles.grid}`}>
                {current.people.map((person) => (
                    <Link
                        key={person.id}
                        href={`/person/${encodeURIComponent(person.id)}`}
                        title={person.label}
                        aria-label={`View ${person.label}`}
                        className={`relative w-full aspect-square overflow-hidden ${styles.person}`}
                    >
                        <PersonPortrait
                            person={person}
                            className={styles.portrait}
                            imageClassName={styles.image}
                            fallbackClassName={styles.icon}
                        />
                        <span className={styles.name}>
                            <span className={styles.namePrimary}>{person.name || "Unnamed person"}</span>
                            {!person.name && <span className={styles.nameId}>#{person.id.slice(-6)}</span>}
                        </span>
                    </Link>
                ))}
            </div>
        </div>
    );
}
