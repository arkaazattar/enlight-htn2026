"use client";

import { useState } from "react";
import Link from "next/link";
import type { TimelineNote } from "../../lib/api";
import { updateTextNote } from "../../lib/api";

export function NoteDetailsModal({ note, onClose, onSaved }: {
  note: TimelineNote; onClose: () => void; onSaved: () => void;
}) {
  const [content, setContent] = useState(note.content || "");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true); setError("");
    try {
      await updateTextNote(note.person_id, note.id, content);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the note.");
    } finally { setSaving(false); }
  }

  return <div role="dialog" aria-modal="true" aria-label="Memory details" className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl">
      <div className="flex justify-between gap-3"><div><h2 className="text-xl font-bold">Memory</h2>
        <p className="text-sm text-[var(--muted-foreground)]">{note.modified_at ? new Date(note.modified_at).toLocaleString() : "Date unavailable"}</p></div>
        <button type="button" onClick={onClose} aria-label="Close memory" className="text-2xl">×</button></div>
      <Link href={`/person/${encodeURIComponent(note.person_id)}`} className="my-4 inline-block underline">{note.person_label}</Link>
      {note.missing ? <p role="alert">The linked note file is missing.</p> : editing ?
        <textarea aria-label="Memory text" value={content} onChange={event => setContent(event.target.value)} rows={10} className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-3" /> :
        <p className="whitespace-pre-wrap break-words">{note.content || "Empty memory"}</p>}
      {error && <p role="alert" className="mt-3 text-red-600">{error}</p>}
      {!note.missing && <div className="mt-6 flex gap-3">
        {editing ? <><button type="button" disabled={saving} onClick={save} className="rounded-lg bg-[var(--primary)] px-4 py-2 text-[var(--primary-foreground)]">{saving ? "Saving…" : "Save"}</button>
          <button type="button" onClick={() => { setContent(note.content || ""); setEditing(false); }} className="rounded-lg border px-4 py-2">Cancel</button></> :
          <button type="button" onClick={() => setEditing(true)} className="rounded-lg border px-4 py-2">Edit memory</button>}
      </div>}
    </div>
  </div>;
}
