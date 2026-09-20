"use client";

import { useState, useEffect } from "react";
import { X } from "lucide-react";
import styles from "./AddScreens.module.css";
import { createTextNote, fetchPeople, Person } from "../../lib/api";

interface AddNoteProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export function AddNote({ isOpen, onClose, onSuccess }: AddNoteProps) {
    const [loading, setLoading] = useState(false);

    const [content, setContent] = useState("");
    const [allPeople, setAllPeople] = useState<Person[]>([]);
    const [taggedPeopleIds, setTaggedPeopleIds] = useState<string[]>([]);
    const [personSearch, setPersonSearch] = useState("");
    const [hasDraft, setHasDraft] = useState(false);
    const [showDraftPrompt, setShowDraftPrompt] = useState(false);

    useEffect(() => {
        if (isOpen) {
            fetchPeople().then(setAllPeople).catch(console.error);
            const savedDraft = localStorage.getItem("draft_note");
            if (savedDraft) {
                setHasDraft(true);
                setShowDraftPrompt(true);
            }
        } else {
            setHasDraft(false);
            setShowDraftPrompt(false);
            setPersonSearch("");
            setContent("");
            setTaggedPeopleIds([]);
        }
    }, [isOpen]);

    const loadDraft = () => {
        const savedDraft = localStorage.getItem("draft_note");
        if (savedDraft) {
            setContent(savedDraft);
        }
        setHasDraft(false);
        setShowDraftPrompt(false);
    };

    const discardDraft = () => {
        localStorage.removeItem("draft_note");
        setHasDraft(false);
        setShowDraftPrompt(false);
    };

    // Save draft when content changes
    useEffect(() => {
        if (!isOpen) return;
        if (content) {
            localStorage.setItem("draft_note", content);
            if (hasDraft) setHasDraft(false);
        } else if (!hasDraft) {
            localStorage.removeItem("draft_note");
        }
    }, [content, isOpen, hasDraft]);

    if (!isOpen) return null;

    const toggleTag = (id: string) => {
        setTaggedPeopleIds(prev =>
            prev.includes(id) ? [] : [id]
        );
    };

    const handleSave = async () => {
        if (!content.trim()) return;
        if (taggedPeopleIds.length !== 1) {
            alert("Choose one person for this note.");
            return;
        }
        setLoading(true);

        try {
            await createTextNote(taggedPeopleIds[0], content);

            // Clear draft on success
            localStorage.removeItem("draft_note");
            onSuccess();
            onClose();
            setContent(""); setTaggedPeopleIds([]);
        } catch (error) {
            console.error("Failed to save note:", error);
            alert("Something went wrong saving the note.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className={`fixed inset-0 z-50 flex flex-col overflow-y-auto ${styles.screen}`}>
            {showDraftPrompt && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
                    <div className={`w-full max-w-sm p-6 flex flex-col gap-4 ${styles.draftModal}`}>
                        <h3 className={styles.draftTitle}>Unfinished Draft</h3>
                        <p className={styles.draftText}>You have an unsaved note draft. Would you like to load it or start fresh?</p>
                        <div className="flex gap-3 justify-end mt-2">
                            <button
                                onClick={discardDraft}
                                className={`px-4 py-2 ${styles.draftBtnSecondary}`}
                            >
                                Start Fresh
                            </button>
                            <button
                                onClick={loadDraft}
                                className={`px-4 py-2 ${styles.draftBtnPrimary}`}
                            >
                                Load Draft
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <div className={`sticky top-0 z-10 flex items-center justify-between p-4 ${styles.header}`}>
                <button onClick={onClose} disabled={loading} className={styles.cancelBtn}>
                    Cancel
                </button>
                <h2 className={styles.title}>New Note</h2>
                <button onClick={handleSave} disabled={loading || !content.trim() || taggedPeopleIds.length !== 1} className={styles.saveBtn}>
                    {loading ? "Saving..." : "Save"}
                </button>
            </div>

            <div className="p-4 flex flex-col gap-6 max-w-2xl mx-auto w-full pb-20">
                <div>
                    <label className={`block mb-2 ${styles.label}`}>Note Content *</label>
                    <textarea
                        required
                        value={content}
                        onChange={(e) => setContent(e.target.value)}
                        rows={5}
                        className={`w-full p-3 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${styles.input}`}
                        placeholder="What's on your mind? e.g. Met John at the coffee shop today..."
                    />
                </div>

                <div>
                    <label className={`block mb-2 ${styles.label}`}>Person *</label>
                    <div className="flex flex-col gap-3">
                        {taggedPeopleIds.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {taggedPeopleIds.map(id => {
                                    const person = allPeople.find(p => p.id === id);
                                    if (!person) return null;
                                    return (
                                        <button
                                            key={person.id}
                                            type="button"
                                            onClick={() => toggleTag(person.id)}
                                            className={`px-3 py-1.5 flex items-center gap-1 ${styles.tagActive}`}
                                        >
                                            @{person.label} <X className="w-3 h-3" />
                                        </button>
                                    );
                                })}
                            </div>
                        )}

                        <input
                            value={personSearch}
                            onChange={(e) => setPersonSearch(e.target.value)}
                            className={`w-full p-2 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${styles.input}`}
                            placeholder="Search people..."
                        />

                        {personSearch && (
                            <div className="flex flex-wrap gap-2 mt-1">
                                {allPeople
                                    .filter(p => p.label.toLowerCase().includes(personSearch.toLowerCase()) && !taggedPeopleIds.includes(p.id))
                                    .map(person => (
                                        <button
                                            key={person.id}
                                            type="button"
                                            onClick={() => {
                                                toggleTag(person.id);
                                                setPersonSearch("");
                                            }}
                                            className={`px-3 py-1.5 ${styles.tagInactive}`}
                                        >
                                            @{person.label}
                                        </button>
                                    ))}
                                {allPeople.filter(p => p.label.toLowerCase().includes(personSearch.toLowerCase()) && !taggedPeopleIds.includes(p.id)).length === 0 && (
                                    <p className="text-xs opacity-70">No matching people found.</p>
                                )}
                            </div>
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}
