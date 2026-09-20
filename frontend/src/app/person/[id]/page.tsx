"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Header } from "../../../../components/Header/Header";
import { PersonPortrait } from "../../../../components/PersonPortrait";
import { NoteDetailsModal } from "../../../../components/ViewNotes/NoteDetailsModal";
import { type Person, type PersonNote, type TimelineNote } from "../../../../lib/api";
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
    const [notes, setNotes] = useState<PersonNote[]>([]);
    // const [connections, setConnections] = useState<Connection[]>([]);
    const [notesError, setNotesError] = useState("");
    // const [connectionsError, setConnectionsError] = useState("");
    const [detailsLoading, setDetailsLoading] = useState(true);
    const [selectedNote, setSelectedNote] = useState<TimelineNote | null>(null);
    // const [nameDraft, setNameDraft] = useState("");
    // const [editingName, setEditingName] = useState(false);
    // const [saveError, setSaveError] = useState("");
    // const [savingName, setSavingName] = useState(false);

    useEffect(() => {
        const controller = new AbortController();
        fetch(`${SERVER_URL}/people/${encodeURIComponent(id)}`, { signal: controller.signal, cache: "no-store" })
            .then(async res => {
                if (!res.ok) {
                    let msg = "Failed";
                    try { const data = await res.json(); if (data.detail) msg = data.detail; } catch(e) {}
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
        return () => controller.abort();
    }, [id, attempt]);

    useEffect(() => {
        const controller = new AbortController();
        setNotes([]); setNotesError(""); setDetailsLoading(true);
        Promise.allSettled([
            fetch(`${SERVER_URL}/people/${encodeURIComponent(id)}/notes`, { signal: controller.signal, cache: "no-store" })
                .then(async res => {
                    if (!res.ok) {
                        let msg = "Failed";
                        try { const data = await res.json(); if (data.detail) msg = data.detail; } catch(e) {}
                        const err = new Error(msg) as any;
                        err.status = res.status;
                        throw err;
                    }
                    return res.json();
                })
        ]).then(([noteResult]) => {
            if (controller.signal.aborted) return;
            if (noteResult.status === "fulfilled") setNotes(noteResult.value.notes);
            else {
                if (noteResult.reason?.status === 404) {
                    setNotesError("Person not found.");
                } else {
                    setNotesError(`Could not load memories: ${noteResult.reason?.message || "Unknown error"}`);
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
                    <Link href="/memories" className={styles.backButton}>
                        <ArrowLeft className="w-4 h-4" /> Back to Timeline
                    </Link>
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
                        <div className={styles.profileHeader}>
                            <PersonPortrait
                                person={person}
                                className={styles.avatarContainer}
                                imageClassName={styles.avatarImage}
                                fallbackClassName={styles.avatarIcon}
                            />
                            <h1 className={styles.name}>{person.label}</h1>
                            {/* 
                            {editingName ? <form className="mt-4 flex flex-wrap justify-center gap-2" onSubmit={async event => {
                                event.preventDefault(); setSavingName(true); setSaveError("");
                                try {
                                    const updated = await renamePerson(id, nameDraft);
                                    setResult({ id, attempt, person: updated });
                                    setEditingName(false); setAttempt(value => value + 1);
                                } catch (cause) { setSaveError(cause instanceof Error ? cause.message : "Could not save name."); }
                                finally { setSavingName(false); }
                            }}>
                                <input aria-label="Person name" value={nameDraft} onChange={event => setNameDraft(event.target.value)} className="rounded-lg border bg-[var(--background)] px-3 py-2" />
                                <button type="submit" disabled={savingName} className={styles.retryButton}>{savingName ? "Saving…" : "Save name"}</button>
                                <button type="button" onClick={() => setEditingName(false)} className={styles.retryButton}>Cancel</button>
                            </form> : <button type="button" className={styles.retryButton} onClick={() => { setNameDraft(person.name || ""); setEditingName(true); }}>Correct name</button>}
                            {saveError && <p role="alert">{saveError}</p>}
                            */}
                        </div>

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
                        <section className={styles.factsSection} aria-labelledby="memories-heading">
                            <h2 id="memories-heading" className={styles.sectionHeading}>Memories</h2>
                            {notesError && <p role="alert">{notesError} <button type="button" className="underline" onClick={() => setAttempt(value => value + 1)}>Retry</button></p>}
                            {detailsLoading && <p role="status">Loading memories…</p>}
                            {notes.length === 0 && !notesError && !detailsLoading ? <p className={styles.empty}>No linked memories.</p> :
                                <ul className={styles.factList}>{notes.map(note => <li key={note.id} className={styles.factCard}>
                                    <button type="button" className="w-full text-left" onClick={() => setSelectedNote({ ...note, person_id: person.id, person_label: person.label })}>
                                        {note.missing ? "Missing note file" : note.content || "Empty memory"}
                                    </button>
                                </li>)}</ul>}
                        </section>
                        {/*
                        <section className={styles.factsSection} aria-labelledby="connections-heading">
                            <h2 id="connections-heading" className={styles.sectionHeading}>Shared events</h2>
                            {connectionsError && <p role="alert">{connectionsError} <button type="button" className="underline" onClick={() => setAttempt(value => value + 1)}>Retry</button></p>}
                            {detailsLoading && <p role="status">Loading shared events…</p>}
                            {connections.length === 0 && !connectionsError && !detailsLoading ? <p className={styles.empty}>No supported shared events yet.</p> :
                                <ul className={styles.factList}>{connections.map(connection => <li key={connection.event_id} className={styles.factCard}>
                                    <h3 className="font-semibold">{connection.title} · {connection.event_date}</h3>
                                    <p className="text-sm">{connection.kind === "planned" ? "Shared plan" : "Occurred event"} with {connection.participants.filter(item => item.person_id !== person.id).map(item => item.label).join(", ")}</p>
                                    {connection.evidence.map(source => <blockquote key={`${source.source_kind}:${source.source_id}`} className={styles.evidenceQuote}>{source.excerpt}
                                        <span className="block text-xs opacity-70">{source.source_kind === "note" ? "Saved note" : "Attributed speech"} · {source.source_id}</span>
                                    </blockquote>)}
                                </li>)}</ul>}
                        </section>
                        */}
                    </>
                )}
                {selectedNote && <NoteDetailsModal note={selectedNote} onClose={() => setSelectedNote(null)} onSaved={() => { setSelectedNote(null); setAttempt(value => value + 1); }} />}
            </div>
        </div>
    );
}
