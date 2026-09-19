"use client";

import { useState, useEffect } from "react";
import { X, Image as ImageIcon } from "lucide-react";
import styles from "./AddScreens.module.css";
import { createPerson } from "../../lib/api";

interface AddPersonProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export function AddPerson({ isOpen, onClose, onSuccess }: AddPersonProps) {
    const [loading, setLoading] = useState(false);

    const [name, setName] = useState("");
    const [relationship, setRelationship] = useState("");
    const [nicknames, setNicknames] = useState<string[]>([]);
    const [nicknameInput, setNicknameInput] = useState("");
    const [hasDraft, setHasDraft] = useState(false);
    const [showDraftPrompt, setShowDraftPrompt] = useState(false);

    const [images, setImages] = useState<File[]>([]);

    useEffect(() => {
        if (isOpen) {
            const draftName = localStorage.getItem("draft_person_name");
            const draftRelationship = localStorage.getItem("draft_person_relationship");
            const draftNicknames = localStorage.getItem("draft_person_nicknames");

            if (draftName || draftRelationship || draftNicknames) {
                setHasDraft(true);
                setShowDraftPrompt(true);
            }
        } else {
            setHasDraft(false);
            setShowDraftPrompt(false);
            setNicknameInput("");
            setName("");
            setRelationship("");
            setNicknames([]);
            setImages([]);
        }
    }, [isOpen]);

    const loadDraft = () => {
        const draftName = localStorage.getItem("draft_person_name");
        const draftRelationship = localStorage.getItem("draft_person_relationship");
        const draftNicknames = localStorage.getItem("draft_person_nicknames");

        if (draftName) setName(draftName);
        if (draftRelationship) setRelationship(draftRelationship);
        if (draftNicknames) {
            try {
                setNicknames(JSON.parse(draftNicknames));
            } catch {
                setNicknames(draftNicknames.split(",").map(n => n.trim()).filter(Boolean));
            }
        }
        setHasDraft(false);
        setShowDraftPrompt(false);
    };

    const discardDraft = () => {
        localStorage.removeItem("draft_person_name");
        localStorage.removeItem("draft_person_relationship");
        localStorage.removeItem("draft_person_nicknames");
        setHasDraft(false);
        setShowDraftPrompt(false);
    };

    useEffect(() => {
        if (!isOpen) return;
        if (name || relationship || nicknames.length > 0) {
            localStorage.setItem("draft_person_name", name);
            localStorage.setItem("draft_person_relationship", relationship);
            localStorage.setItem("draft_person_nicknames", JSON.stringify(nicknames));
            if (hasDraft) setHasDraft(false);
        } else if (!hasDraft) {
            localStorage.removeItem("draft_person_name");
            localStorage.removeItem("draft_person_relationship");
            localStorage.removeItem("draft_person_nicknames");
        }
    }, [name, relationship, nicknames, isOpen, hasDraft]);

    if (!isOpen) return null;

    const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            const newFiles = Array.from(e.target.files);
            if (images.length + newFiles.length > 6) {
                alert("You can only upload a maximum of 6 pictures.");
                return;
            }
            setImages(prev => [...prev, ...newFiles].slice(0, 6));
        }
    };

    const removeImage = (index: number) => {
        setImages(prev => prev.filter((_, i) => i !== index));
    };

    const handleAddNickname = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const val = nicknameInput.trim();
            if (val && !nicknames.includes(val)) {
                setNicknames(prev => [...prev, val]);
            }
            setNicknameInput("");
        }
    };

    const removeNickname = (nickname: string) => {
        setNicknames(prev => prev.filter(n => n !== nickname));
    };

    const handleSave = async () => {
        if (!name.trim()) return;
        setLoading(true);

        try {
            await createPerson(name, relationship, nicknames);

            // Clear drafts upon success
            localStorage.removeItem("draft_person_name");
            localStorage.removeItem("draft_person_relationship");
            localStorage.removeItem("draft_person_nicknames");

            onSuccess();
            onClose();
            setName(""); setRelationship(""); setNicknames([]); setImages([]);
        } catch (error) {
            console.error("Failed to save person:", error);
            alert("Something went wrong saving the person.");
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
                    />
                </div>

                <div>
                    <label className={`block mb-2 ${styles.label}`}>Relationship</label>
                    <input
                        value={relationship}
                        onChange={(e) => setRelationship(e.target.value)}
                        className={`w-full p-3 ${styles.input}`}
                        placeholder="e.g. Sister, Colleague"
                    />
                </div>

                <div>
                    <label className={`block mb-2 ${styles.label}`}>Nicknames</label>
                    <div className="flex flex-col gap-2">
                        {nicknames.length > 0 && (
                            <div className="flex flex-wrap gap-2 mb-1">
                                {nicknames.map(nickname => (
                                    <span key={nickname} className={`px-3 py-1.5 flex items-center gap-1 ${styles.tagActive}`}>
                                        {nickname}
                                        <button type="button" onClick={() => removeNickname(nickname)}>
                                            <X className="w-3 h-3 hover:opacity-70" />
                                        </button>
                                    </span>
                                ))}
                            </div>
                        )}
                        <input
                            value={nicknameInput}
                            onChange={(e) => setNicknameInput(e.target.value)}
                            onKeyDown={handleAddNickname}
                            className={`w-full p-3 ${styles.input}`}
                            placeholder="Type a nickname and press Enter"
                        />
                    </div>
                </div>

                <div>
                    <label className={`block mb-2 ${styles.label}`}>Photos <span className="text-xs font-normal opacity-70">({images.length}/6)</span></label>

                    <div className="grid grid-cols-3 gap-2 mb-3">
                        {images.map((img, index) => (
                            <div key={index} className={`aspect-square relative overflow-hidden ${styles.imagePreview}`}>
                                <img src={URL.createObjectURL(img)} alt={`Upload ${index}`} className="w-full h-full object-cover" />
                                <button
                                    onClick={() => removeImage(index)}
                                    className={`absolute top-1 right-1 w-6 h-6 flex items-center justify-center ${styles.removeImage}`}
                                >
                                    <X className="w-3 h-3" />
                                </button>
                            </div>
                        ))}
                    </div>

                    {images.length < 6 && (
                        <label className={`w-full p-4 flex flex-col items-center justify-center gap-2 ${styles.fileDrop}`}>
                            <ImageIcon className="w-8 h-8 opacity-50" />
                            <span className="text-sm font-medium">Add Photos</span>
                            <span className="text-xs opacity-70">Up to 6 pictures max</span>
                            <input
                                type="file"
                                multiple
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
