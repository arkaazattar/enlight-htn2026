"use client";

import { X, Edit2, UserPlus } from "lucide-react";
import styles from "./ViewNotes.module.css";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

export interface DisplayNote {
    id: string;
    title: string;
    content?: string;
    image: string | null;
    type: string;
    date?: string;
    taggedPeople?: Array<{ id: string; name: string }>;
}

interface NoteDetailsModalProps {
    note: DisplayNote | null;
    isOpen: boolean;
    onClose: () => void;
}

export function NoteDetailsModal({ note, isOpen, onClose }: NoteDetailsModalProps) {
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
    }, []);

    // Prevent scrolling on background when modal is open
    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = "hidden";
        } else {
            document.body.style.overflow = "";
        }
        return () => {
            document.body.style.overflow = "";
        };
    }, [isOpen]);

    if (!isOpen || !note || !mounted) return null;

    return createPortal(
        <div className={`fixed inset-0 flex items-center justify-center p-4 sm:p-6 ${styles.backdrop}`}>
            <div className={`w-full max-w-2xl flex flex-col overflow-hidden ${styles.modalContent}`}>

                {/* Header */}
                <div className={`flex items-center justify-between p-4 ${styles.header}`}>
                    <div className="flex flex-col">
                        <h2 className={styles.title}>{note.title}</h2>
                        <span className={styles.date}>{note.date || "Unknown Date"}</span>
                    </div>
                    <button
                        onClick={onClose}
                        className={`p-2 flex items-center justify-center ${styles.closeButton}`}
                        aria-label="Close"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Scrollable Content */}
                <div className="flex-1 overflow-y-auto p-4 sm:p-6 flex flex-col gap-6">

                    {/* Images */}
                    {note.image && (
                        <div className={`w-full aspect-video relative ${styles.imageContainer}`}>
                            <img
                                src={note.image}
                                alt={note.title}
                                className={`w-full h-full ${styles.modalImage}`}
                            />
                        </div>
                    )}

                    {/* Content */}
                    <div>
                        <p className={styles.content}>
                            {note.content || "This is a placeholder for the full note content. You can write your memories here and they will be displayed when the note is clicked."}
                        </p>
                    </div>

                    {/* Tags */}
                    {note.taggedPeople && note.taggedPeople.length > 0 && (
                        <div className={`pt-4 ${styles.tagSection}`}>
                            <h4 className={styles.tagLabel}>With</h4>
                            <div className="flex flex-wrap gap-2">
                                {note.taggedPeople.map(person => (
                                    <span key={person.id} className={styles.tag}>
                                        @{person.name}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Actions Stub */}
                    <div className={`flex gap-3 pt-4 mt-auto ${styles.actionsContainer}`}>
                        <button className={`flex items-center gap-2 ${styles.actionButton}`}>
                            <Edit2 className="w-4 h-4" /> Edit
                        </button>
                        <button className={`flex items-center gap-2 ${styles.actionButton}`}>
                            <UserPlus className="w-4 h-4" /> Tag People
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
