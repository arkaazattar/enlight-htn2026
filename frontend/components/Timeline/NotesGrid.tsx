"use client";

import { useState } from "react";
import { FileText } from "lucide-react";
import type { TimelineNote } from "../../lib/api";
import { NoteDetailsModal } from "../ViewNotes/NoteDetailsModal";

export function NotesGrid({ notes, onSaved }: { notes: TimelineNote[]; onSaved: () => void }) {
  const [selected, setSelected] = useState<TimelineNote | null>(null);
  return <>
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 pb-8">
      {notes.map(note => <button type="button" key={`${note.person_id}:${note.id}`}
        onClick={() => setSelected(note)} className="text-left rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 hover:shadow-md">
        <FileText className="mb-3 h-6 w-6" aria-hidden="true" />
        <span className="block font-semibold line-clamp-3">{note.missing ? "Missing note file" : note.content?.trim().split("\n")[0] || "Empty memory"}</span>
        <span className="mt-3 block text-sm text-[var(--muted-foreground)]">{note.person_label}</span>
      </button>)}
    </div>
    {selected && <NoteDetailsModal note={selected} onClose={() => setSelected(null)} onSaved={() => { setSelected(null); onSaved(); }} />}
    {notes.length === 0 && <p>No memories on this date.</p>}
  </>;
}
