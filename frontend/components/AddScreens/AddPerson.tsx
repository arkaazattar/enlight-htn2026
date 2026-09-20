"use client";

import { useState, useEffect } from "react";
import { X, Image as ImageIcon } from "lucide-react";
import styles from "./AddScreens.module.css";
import { SERVER_URL } from "../../lib/config";

interface AddPersonProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export function AddPerson({ isOpen, onClose, onSuccess }: AddPersonProps) {
    const [loading, setLoading] = useState(false);
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [image, setImage] = useState<File | null>(null);
    const [hasDraft, setHasDraft] = useState(false);
    const [showDraftPrompt, setShowDraftPrompt] = useState(false);

    useEffect(() => {
        if (isOpen) {
            const draftName = localStorage.getItem("draft_person_name");
            const draftDesc = localStorage.getItem("draft_person_description");

            if (draftName || draftDesc) {
                setHasDraft(true);
                setShowDraftPrompt(true);
            }
        } else {
            setHasDraft(false);
            setShowDraftPrompt(false);
            setName("");
            setDescription("");
            setImage(null);
        }
    }, [isOpen]);

    const loadDraft = () => {
        const draftName = localStorage.getItem("draft_person_name");
        const draftDesc = localStorage.getItem("draft_person_description");

        if (draftName) setName(draftName);
        if (draftDesc) setDescription(draftDesc);
        setHasDraft(false);
        setShowDraftPrompt(false);
    };

    const discardDraft = () => {
        localStorage.removeItem("draft_person_name");
        localStorage.removeItem("draft_person_description");
        setHasDraft(false);
        setShowDraftPrompt(false);
    };

    useEffect(() => {
        if (!isOpen) return;
        if (name || description) {
            localStorage.setItem("draft_person_name", name);
            localStorage.setItem("draft_person_description", description);
            if (hasDraft) setHasDraft(false);
        } else if (!hasDraft) {
            localStorage.removeItem("draft_person_name");
            localStorage.removeItem("draft_person_description");
        }
    }, [name, description, isOpen, hasDraft]);

    if (!isOpen) return null;

    const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            setImage(e.target.files[0]);
        }
    };

    const handleSave = async () => {
        if (!name.trim()) return;
        setLoading(true);

        try {
            const res = await fetch(`${SERVER_URL}/people`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: name.trim(), description: description.trim() || "" }),
            });
            if (!res.ok) {
                let msg = "Failed to create person";
                try {
                    const data = await res.json();
                    if (data.detail) msg = data.detail;
                } catch {}
                throw new Error(msg);
            }
            const created = await res.json();

            if (image) {
                const formData = new FormData();
                formData.append("file", image);
                const uploadRes = await fetch(`${SERVER_URL}/people/${encodeURIComponent(created.id)}/pictures`, {
                    method: "POST",
                    body: formData,
                });
                if (!uploadRes.ok) {
                    let msg = "Failed to upload person picture";
                    try {
                        const data = await uploadRes.json();
                        if (data.detail) msg = data.detail;
                    } catch {}
                    throw new Error(msg);
                }
            }

            localStorage.removeItem("draft_person_name");
            localStorage.removeItem("draft_person_description");

            onSuccess();
            onClose();
            setName("");
            setDescription("");
            setImage(null);
        } catch (error: any) {
            console.error("Failed to save person:", error);
            alert(error.message || "Something went wrong saving the person.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className={`fixed inset-0 z-50 flex flex-col overflow-y-auto ${styles.screen}`}>
            {showDraftPrompt && (
                <div className={`fixed inset-0 z-[60] flex items-center justify-center p-4 ${styles.draftBackdrop}`}>
                    <div className={`w-full max-w-sm p-6 flex flex-col gap-4 ${styles.draftModal}`}>
                        <h3 className={styles.draftTitle}>Unfinished Draft</h3>
                        <p className={styles.draftText}>You have an unsaved person draft. Would you like to load it or start fresh?</p>
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
                <h2 className={styles.title}>New Person</h2>
                <button onClick={handleSave} disabled={loading || !name.trim()} className={styles.saveBtn}>
                    {loading ? "Saving..." : "Save"}
                </button>
            </div>

            <div className="p-4 flex flex-col gap-6 max-w-2xl mx-auto w-full pb-20">
                <div>
                    <label className={`block mb-2 ${styles.label}`}>Name *</label>
                    <input
                        required
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className={`w-full p-3 ${styles.input}`}
                        placeholder="e.g. Jane Doe"
                        autoFocus
                    />
                </div>

                <div>
                    <label className={`block mb-2 ${styles.label}`}>Description</label>
                    <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        className={`w-full p-3 min-h-[100px] resize-y ${styles.input}`}
                        placeholder="e.g. Software engineer, loves hiking and coffee..."
                    />
                </div>

                <div>
                    <label className={`block mb-2 ${styles.label}`}>Picture <span className="text-xs font-normal opacity-70">(Optional)</span></label>

                    {image ? (
                        <div className="w-32 h-32 relative overflow-hidden rounded-xl border border-[var(--border)]">
                            <img
                                src={URL.createObjectURL(image)}
                                alt="Person portrait"
                                className="w-full h-full object-cover"
                            />
                            <button
                                type="button"
                                onClick={() => setImage(null)}
                                className={`absolute top-1.5 right-1.5 w-6 h-6 flex items-center justify-center ${styles.removeImage}`}
                                aria-label="Remove picture"
                            >
                                <X className="w-3.5 h-3.5" />
                            </button>
                        </div>
                    ) : (
                        <label className={`w-full p-6 flex flex-col items-center justify-center gap-2 ${styles.fileDrop}`}>
                            <ImageIcon className="w-8 h-8 opacity-50" />
                            <span className="text-sm font-medium">Add Portrait Photo</span>
                            <span className="text-xs opacity-70">PNG, JPG, or WebP</span>
                            <input
                                type="file"
                                accept="image/*"
                                onChange={handleImageChange}
                                className="hidden"
                            />
                        </label>
                    )}
                </div>
            </div>
        </div>
    );
}
