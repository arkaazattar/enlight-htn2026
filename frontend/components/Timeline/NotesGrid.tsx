"use client";

import { useState } from "react";
import styles from "./TimelineBoard.module.css";
import { Image as ImageIcon } from "lucide-react";
import { NoteDetailsModal } from "../ViewNotes/NoteDetailsModal";

export function NotesGrid({
    notesForDay,
}: {
    notesForDay: Array<{ id: string; title: string; image: string | null; type: string }>;
}) {
    const [selectedNote, setSelectedNote] = useState<typeof notesForDay[0] | null>(null);

    if (notesForDay.length === 0) {
        return (
            <div className="flex w-full h-[200px] items-center justify-center text-sm text-muted-foreground">
                No stories on this day.
            </div>
        );
    }

    return (
        <div className="columns-2 md:columns-3 lg:columns-3 gap-4 w-full pb-8">
            {notesForDay.map((note) => (
                <div
                    key={note.id}
                    onClick={() => setSelectedNote(note)}
                    className={`break-inside-avoid mb-4 overflow-hidden ${styles.noteCard}`}
                >
                    {note.type === "picture" && note.image ? (
                        <div className="relative w-full group">
                            <img
                                src={note.image}
                                alt={note.title}
                                className={`w-full h-auto object-cover ${styles.noteImage}`}
                            />
                            <div className={`absolute inset-0 pointer-events-none ${styles.imageGradient}`} />
                            <div className={`absolute bottom-0 left-0 p-3 w-full z-10 select-none ${styles.noteTitle}`}>
                                <span className="line-clamp-2">{note.title}</span>
                            </div>
                        </div>
                    ) : (
                        <div className={`relative w-full p-6 flex flex-col items-center justify-center min-h-[160px] ${styles.fallbackCard}`}>
                            <div className={`w-12 h-12 mb-3 flex items-center justify-center rounded-full ${styles.iconContainer}`}>
                                <ImageIcon className={`w-6 h-6 ${styles.icon}`} />
                            </div>
                            <span className={`text-center px-2 ${styles.fallbackTitle}`}>
                                {note.title}
                            </span>
                        </div>
                    )}
                </div>
            ))}

            <NoteDetailsModal
                note={selectedNote}
                isOpen={!!selectedNote}
                onClose={() => setSelectedNote(null)}
            />
        </div>
    );
}
