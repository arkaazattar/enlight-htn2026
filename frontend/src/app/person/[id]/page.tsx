"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Header } from "../../../../components/Header/Header";
import { PersonPortrait } from "../../../../components/PersonPortrait";
import { NoteDetailsModal } from "../../../../components/ViewNotes/NoteDetailsModal";
import { PostsGrid } from "../../../../components/Timeline/PostsGrid";
import { type Person, type Post, type TimelineNote } from "../../../../lib/api";
import { SERVER_URL } from "../../../../lib/config";
import styles from "./Person.module.css";

type PersonResult = {
    id: string;
    attempt: number;
    person?: Person;
    error?: string;
};

function evidenceForFact(person: Person, fact: string): string[] {
    const grouped = person.context.fact_evidence;
    if (!grouped || typeof grouped !== "object" || Array.isArray(grouped)) return [];
    const entries = (grouped as Record<string, unknown>)[fact];
    if (!Array.isArray(entries)) return [];
    const texts = entries.flatMap((entry: unknown) => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
        const source = entry as Record<string, unknown>;
        if (source.person_id !== person.id || typeof source.text !== "string") return [];
        const text = source.text.trim();
        return text ? [text] : [];
    });
    return [...new Set(texts)];
}

export default function PersonPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = use(params);
    const [attempt, setAttempt] = useState(0);
    const [result, setResult] = useState<PersonResult | null>(null);
    const [posts, setPosts] = useState<Post[]>([]);
    const [postsError, setPostsError] = useState("");
    const [detailsLoading, setDetailsLoading] = useState(true);
    const [selectedNote, setSelectedNote] = useState<TimelineNote | null>(null);
    const [editingName, setEditingName] = useState(false);
    const [nameDraft, setNameDraft] = useState("");
    const [savingName, setSavingName] = useState(false);
    const [saveError, setSaveError] = useState("");
    const [relatedPeople, setRelatedPeople] = useState<{person_id: string, name: string}[]>([]);
    
    const router = useRouter();

    const handleDeletePerson = async () => {
        if (!confirm("Are you sure you want to delete this person? This action cannot be undone.")) return;
        try {
            const res = await fetch(`${SERVER_URL}/people/${encodeURIComponent(id)}`, { method: "DELETE" });
            if (!res.ok) throw new Error("Failed to delete person.");
            router.push("/");
        } catch (err) {
            alert(err instanceof Error ? err.message : "Could not delete person.");
        }
    };

    useEffect(() => {
        const controller = new AbortController();
        fetch(`${SERVER_URL}/people/${encodeURIComponent(id)}`, { signal: controller.signal, cache: "no-store" })
            .then(async res => {
                if (!res.ok) {
                    let msg = "Failed";
                    try { const data = await res.json(); if (data.detail) msg = data.detail; } catch (e) { }
                    const error = new Error(msg) as any;
                    error.status = res.status;
                    throw error;
                }
                return res.json();
            })
            .then((person) => {
                if (controller.signal.aborted) return;
                if (person.id !== id) {
                    setResult({ id, attempt, error: "Could not verify this person's record." });
                    return;
                }
                setResult({ id, attempt, person });
            })
            .catch((error: any) => {
                if (!controller.signal.aborted) {
                    setResult({
                        id,
                        attempt,
                        error: error.status === 404
                            ? "This person was not found."
                            : `Could not load this person: ${error.message}`,
                    });
                }
            });
            
        // Fetch related people
        const nodeId = parseInt(id, 16);
        if (!isNaN(nodeId)) {
            fetch(`${SERVER_URL}/graph/${nodeId}/closest?limit=2`)
                .then(res => res.ok ? res.json() : { related: [] })
                .then(data => {
                    setRelatedPeople(data.related || []);
                })
                .catch(console.error);
        }
            
        return () => controller.abort();
    }, [id, attempt]);

    useEffect(() => {
        const controller = new AbortController();
        setPosts([]); setPostsError(""); setDetailsLoading(true);
        Promise.allSettled([
            fetch(`${SERVER_URL}/people/${encodeURIComponent(id)}/posts`, { signal: controller.signal, cache: "no-store" })
                .then(async res => {
                    if (!res.ok) {
                        let msg = "Failed";
                        try { const data = await res.json(); if (data.detail) msg = data.detail; } catch (e) { }
                        const err = new Error(msg) as any;
                        err.status = res.status;
                        throw err;
                    }
                    return res.json();
                })
        ]).then(([postResult]) => {
            if (controller.signal.aborted) return;
            if (postResult.status === "fulfilled") setPosts(postResult.value.posts);
            else {
                if (postResult.reason?.status === 404) {
                    setPostsError("Person not found.");
                } else {
                    setPostsError(`Could not load memories: ${postResult.reason?.message || "Unknown error"}`);
                }
            }
            setDetailsLoading(false);
        });
        return () => controller.abort();
    }, [id, attempt]);

    // The route can change before an earlier request resolves. Never render a
    // result associated with another stable ID or retry attempt.
    const current = result?.id === id && result.attempt === attempt ? result : null;
    const person = current?.person;

    return (
        <div className={styles.container}>
            <Header />
            <div className={styles.mainContent}>
                <div className={styles.backButtonContainer}>
                    <Link href="/" className={styles.backButton}>
                        <ArrowLeft className="w-4 h-4" /> Back
                    </Link>
                    {person && (
                        <button 
                            onClick={handleDeletePerson}
                            className="inline-flex items-center gap-2 px-6 py-3 rounded-full font-semibold bg-red-600 text-white hover:bg-red-700 transition shadow-md"
                        >
                            <Trash2 className="w-5 h-5" /> Delete Person
                        </button>
                    )}
                </div>

                {!current && <p className={styles.statePanel} role="status">Loading person…</p>}
                {current?.error && (
                    <div className={styles.statePanel} role="alert">
                        <p>{current.error}</p>
                        <button type="button" className={styles.retryButton} onClick={() => setAttempt(value => value + 1)}>
                            Try again
                        </button>
                    </div>
                )}

                {person && (
                    <>
                        <div className={styles.topSplit}>
                            <div className={styles.leftColumn}>
                                <div className={styles.profileHeader}>
                                    <div className={styles.avatarWrapper}>
                                        <PersonPortrait
                                            person={person}
                                            className={styles.avatarContainer}
                                            imageClassName={styles.avatarImage}
                                            fallbackClassName={styles.avatarIcon}
                                        />
                                        
                                        {relatedPeople.length > 0 && (
                                            <div className={styles.relatedStack}>
                                                <div className="text-[10px] uppercase font-bold text-zinc-500 tracking-wider bg-black/40 px-2 py-1 rounded-md mb-1 whitespace-nowrap">
                                                    Closest Friend{relatedPeople.length > 1 ? 's' : ''}
                                                </div>
                                                <div className="flex flex-col gap-2 items-end">
                                                    {relatedPeople.map(rp => (
                                                        <Link key={rp.person_id} href={`/person/${rp.person_id}`} title={rp.name}>
                                                            <div className={styles.relatedBubble}>
                                                                <img 
                                                                    src={`${SERVER_URL}/people/${rp.person_id}/image`} 
                                                                    alt={rp.name} 
                                                                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                                                />
                                                            </div>
                                                        </Link>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                    <h1 className={styles.name}>{person.label}</h1>
                                </div>
                            </div>

                            <div className={styles.rightColumn}>
                                <section className={styles.factsSection} aria-labelledby="saved-facts-heading">
                                    <h2 id="saved-facts-heading" className={styles.sectionHeading}>Saved facts</h2>
                                    {person.facts.length === 0 ? (
                                        <p className={styles.empty}>No saved facts yet.</p>
                                    ) : (
                                        <ul className={styles.factList}>
                                            {person.facts.map((fact, index) => {
                                                const evidence = evidenceForFact(person, fact);
                                                return (
                                                    <li key={`${fact}:${index}`} className={styles.factCard}>
                                                        <p>{fact}</p>
                                                        {evidence.length > 0 && (
                                                            <div className={styles.evidence}>
                                                                <span className={styles.evidenceLabel}>Supporting conversation</span>
                                                                {evidence.map((text) => (
                                                                    <blockquote key={text} className={styles.evidenceQuote}>{text}</blockquote>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </li>
                                                );
                                            })}
                                        </ul>
                                    )}
                                </section>
                            </div>
                        </div>

                        <div className={styles.bottomSection}>
                            <section className={styles.factsSection} aria-labelledby="memories-heading">
                                <h2 id="memories-heading" className={styles.sectionHeading}>Memories</h2>
                                {postsError && <p role="alert">{postsError} <button type="button" className="underline" onClick={() => setAttempt(value => value + 1)}>Retry</button></p>}
                                {detailsLoading && <p role="status">Loading memories…</p>}
                                {posts.length === 0 && !postsError && !detailsLoading ? <p className={styles.empty}>No linked memories.</p> :
                                    <div className="mt-4"><PostsGrid posts={posts} onSaved={() => setAttempt(value => value + 1)} /></div>
                                }
                            </section>
                        </div>
                    </>
                )}
                {selectedNote && <NoteDetailsModal note={selectedNote} onClose={() => setSelectedNote(null)} onSaved={() => { setSelectedNote(null); setAttempt(value => value + 1); }} />}
            </div>
        </div>
    );
}
