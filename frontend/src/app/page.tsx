"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Header } from "../../components/Header/Header";
import { PersonPortrait } from "../../components/PersonPortrait";
import { fetchPerson, type Person } from "../../lib/api";
import { SERVER_URL } from "../../lib/config";

interface LiveFrame {
  frame_id: number;
  received_at: number;
  width: number;
  height: number;
  image_base64: string;
  focused_person_id: string | null;
  observations: Array<{ x: number; y: number; w: number; h: number; person_id: string | null; stable: boolean }>;
}

export default function LivePage() {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [state, setState] = useState<"connecting" | "live" | "unavailable">("connecting");
  const [person, setPerson] = useState<Person | null>(null);
  const [personError, setPersonError] = useState(false);
  const focusId = frame?.focused_person_id || null;

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let activeRequest: AbortController | null = null;
    async function poll() {
      const requestController = new AbortController();
      activeRequest = requestController;
      const timeout = setTimeout(() => requestController.abort(), 2500);
      try {
        const response = await fetch(`${SERVER_URL}/camera/latest`, { cache: "no-store", signal: requestController.signal });
        if (!active) return;
        if (response.status === 204) {
          setFrame(null); setState("unavailable");
        } else if (response.ok) {
          const next = await response.json() as LiveFrame;
          if (!active) return;
          setFrame(current => current?.frame_id === next.frame_id ? current : next);
          setState("live");
        } else {
          setFrame(null); setState("unavailable");
        }
      } catch {
        if (active) { setFrame(null); setState("unavailable"); }
      } finally {
        clearTimeout(timeout);
        if (activeRequest === requestController) activeRequest = null;
        if (active) timer = setTimeout(poll, 220);
      }
    }
    poll();
    return () => { active = false; activeRequest?.abort(); clearTimeout(timer); };
  }, []);

  useEffect(() => {
    setPerson(null); setPersonError(false);
    if (!focusId) return;
    const controller = new AbortController();
    fetchPerson(focusId, controller.signal).then(value => {
      if (!controller.signal.aborted && value.id === focusId) setPerson(value);
    }).catch(() => { if (!controller.signal.aborted) setPersonError(true); });
    return () => controller.abort();
  }, [focusId]);

  const ratio = frame ? frame.width / frame.height : 4 / 3;
  return <div className="min-h-screen bg-[var(--background)] text-[var(--foreground)]">
    <Header />
    <main className="mx-auto max-w-6xl px-4 pb-10">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-3xl font-bold">Live</h1><p className="text-[var(--muted-foreground)]">People in view, with saved context nearby.</p></div>
        <Link href="/memories" className="rounded-full border border-[var(--border)] px-4 py-2 font-semibold">Browse Memories</Link>
      </div>
      <div className="rounded-2xl border border-[var(--border)] bg-black p-3 sm:p-5">
        <div className="mx-auto relative overflow-hidden rounded-lg bg-neutral-950" style={{ width: "100%", maxWidth: `calc(65vh * ${ratio})`, aspectRatio: `${frame?.width || 4} / ${frame?.height || 3}` }}>
          {frame ? <>
            {/* The live data URL is already a bounded JPEG from the camera process. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`data:image/jpeg;base64,${frame.image_base64}`} alt="Live camera view" className="absolute inset-0 h-full w-full object-contain" />
            {frame.observations.map((box, index) => <div key={`${frame.frame_id}:${index}`}
              aria-label={box.person_id && box.stable ? "Tracked person" : "Detected face"}
              className={`pointer-events-none absolute rounded-lg border-2 ${box.person_id === focusId && box.stable ? "border-emerald-400" : "border-white/80"}`}
              style={{ left: `${box.x / frame.width * 100}%`, top: `${box.y / frame.height * 100}%`, width: `${box.w / frame.width * 100}%`, height: `${box.h / frame.height * 100}%` }} />)}
          </> : <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-white/80" role="status">
            {state === "connecting" ? "Connecting to camera…" : "Camera unavailable or feed is stale. Reconnecting…"}
          </div>}
        </div>
      </div>
      <section className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5" aria-label="Focused person">
        {!focusId ? <p className="text-[var(--muted-foreground)]">No stable person is centered right now.</p> : person ?
          <div className="flex flex-wrap items-center gap-5"><PersonPortrait person={person} className="h-20 w-20 overflow-hidden rounded-full" imageClassName="h-full w-full object-cover" fallbackClassName="h-10 w-10" />
            <div className="min-w-0 flex-1"><h2 className="text-xl font-bold">{person.label}</h2><p className="mt-1 text-sm">{person.facts.length ? person.facts.slice(0, 3).join(" · ") : "No saved facts yet."}</p>
              <Link href={`/person/${encodeURIComponent(person.id)}`} className="mt-2 inline-block font-semibold underline">View person details</Link></div></div> :
          <p role="status">{personError ? "Could not load this person’s saved details." : "Loading saved details…"}</p>}
      </section>
    </main>
  </div>;
}
