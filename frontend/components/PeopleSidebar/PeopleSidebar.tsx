"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { type Person } from "../../lib/api";
import { SERVER_URL } from "../../lib/config";
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
        fetch(`${SERVER_URL}/people`, { signal: controller.signal, cache: "no-store" })
            .then(async (res) => {
                if (!res.ok) {
                    let msg = "Failed to fetch people";
                    try { const data = await res.json(); if (data.detail) msg = data.detail; } catch(e) {}
                    throw new Error(msg);
                }
                return res.json();
            })
            .then((people) => {
                if (!controller.signal.aborted) setResult({ requestKey, people });
            })
            .catch((e: any) => {
                if (!controller.signal.aborted) {
                    setResult({ requestKey, error: `Could not load people: ${e.message}` });
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
                {current.people.map((person) => {
                    const hasImage = person.picture_ids && person.picture_ids.length > 0;
                    return (
                    <Link
                        key={person.id}
                        href={`/person/${encodeURIComponent(person.id)}`}
                        title={person.label}
                        aria-label={`View ${person.label}`}
                        className={`relative w-full aspect-square overflow-hidden ${styles.person} ${!hasImage ? styles.personNoImage : ''}`}
                    >
                        <PersonPortrait
                            person={person}
                            className={styles.portrait}
                            imageClassName={styles.image}
                            fallbackClassName={styles.icon}
                        />
                        <span className={`${styles.name} ${!hasImage ? styles.nameNoImage : ''}`}>
                            <span className={styles.namePrimary}>{person.name || "Unnamed person"}</span>
                        </span>
                    </Link>
                )})}
            </div>
        </div>
    );
}
