"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchNotes, type TimelineNote } from "../../lib/api";
import { NotesGrid } from "./NotesGrid";

function dayOf(note: TimelineNote): string {
  if (!note.modified_at) return "Unknown date";
  const date = new Date(note.modified_at);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function TimelineBoard({ refreshKey = 0 }: { refreshKey?: number }) {
  const [notes, setNotes] = useState<TimelineNote[]>([]);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchNotes(controller.signal).then(result => {
      if (controller.signal.aborted) return;
      setNotes(result.notes);
      setState("ready");
    }).catch(() => {
      if (!controller.signal.aborted) setState("error");
    });
    return () => controller.abort();
  }, [refreshKey, reload]);

  const days = useMemo(() => [...new Set(notes.map(dayOf))].sort((a, b) => b.localeCompare(a)), [notes]);
  const activeDay = selectedDay && days.includes(selectedDay) ? selectedDay : days[0];
  const visible = notes.filter(note => dayOf(note) === activeDay).sort((a, b) =>
    (b.modified_at || "").localeCompare(a.modified_at || "") || a.id.localeCompare(b.id));

  return <div className="w-full h-full flex flex-col">
    <div className="border-b border-[var(--border)] px-6 py-4">
      <h2 className="text-xl font-bold">Saved memories</h2>
      {days.length > 0 && <div className="flex gap-2 overflow-x-auto py-3" aria-label="Memory dates">
        {days.map(day => <button key={day} type="button" onClick={() => setSelectedDay(day)}
          aria-pressed={day === activeDay}
          className={`shrink-0 rounded-full px-4 py-2 text-sm ${day === activeDay ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "bg-[var(--muted)]"}`}>
          {day === "Unknown date" ? day : new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}
        </button>)}
      </div>}
    </div>
    <div className="flex-1 overflow-y-auto px-6 py-6">
      {state === "loading" && <p role="status">Loading memories…</p>}
      {state === "error" && <div role="alert">Could not load memories. <button type="button" onClick={() => { setState("loading"); setReload(value => value + 1); }} className="underline">Try again</button></div>}
      {state === "ready" && (notes.length === 0 ? <p>No saved memories yet. Add a note to start.</p> :
        <><h3 className="mb-5 font-semibold">{activeDay}</h3><NotesGrid notes={visible} onSaved={() => setReload(value => value + 1)} /></>)}
    </div>
  </div>;
}
