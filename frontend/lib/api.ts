import { SERVER_URL } from "./config";

export interface Person {
    id: string;
    name: string | null;
    label: string;
    facts: string[];
    context: Record<string, unknown>;
    image_paths: string[];
    note_paths: string[];
    image_url: string;
}

export interface PersonNote {
    id: string;
    path: string;
    content: string | null;
    missing: boolean;
    modified_at: string | null;
}

export interface TimelineNote extends PersonNote {
    person_id: string;
    person_label: string;
}

export interface Connection {
    event_id: string;
    title: string;
    event_date: string;
    kind: "planned" | "occurred";
    participants: Array<{ person_id: string; label: string }>;
    evidence: Array<{ source_kind: "note" | "speech"; source_id: string; person_id: string; excerpt: string; clip_id: string | null }>;
}

export class ApiError extends Error {
    constructor(message: string, readonly status: number) {
        super(message);
        this.name = "ApiError";
    }
}

async function responseError(response: Response): Promise<ApiError> {
    try {
        const body = await response.json();
        if (typeof body.detail === "string") {
            return new ApiError(body.detail, response.status);
        }
    } catch {}
    return new ApiError(`Request failed with status ${response.status}.`, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${SERVER_URL}${path}`, {
        cache: "no-store",
        ...init,
    });
    if (!response.ok) {
        throw await responseError(response);
    }
    return response.json() as Promise<T>;
}

export function personImageUrl(person: Person): string {
    const imagePath = person.image_paths[0];
    const version = imagePath ? `?v=${encodeURIComponent(imagePath)}` : "";
    return `${SERVER_URL}${person.image_url}${version}`;
}

export function fetchPeople(signal?: AbortSignal): Promise<Person[]> {
    return request<Person[]>("/people", { signal });
}

export function fetchPerson(personId: string, signal?: AbortSignal): Promise<Person> {
    return request<Person>(`/people/${encodeURIComponent(personId)}`, { signal });
}

export function fetchPersonNotes(personId: string): Promise<{ notes: PersonNote[] }> {
    return request<{ notes: PersonNote[] }>(`/people/${encodeURIComponent(personId)}/notes`);
}

export function fetchNotes(signal?: AbortSignal): Promise<{ notes: TimelineNote[] }> {
    return request<{ notes: TimelineNote[] }>("/notes", { signal });
}

export function fetchConnections(personId: string, signal?: AbortSignal): Promise<{ connections: Connection[]; excluded_count: number }> {
    return request(`/people/${encodeURIComponent(personId)}/connections`, { signal });
}

export function renamePerson(personId: string, name: string): Promise<Person> {
    return request<Person>(`/people/${encodeURIComponent(personId)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
    });
}

export function updateTextNote(personId: string, noteId: string, content: string): Promise<PersonNote> {
    return request<PersonNote>(`/people/${encodeURIComponent(personId)}/notes/${encodeURIComponent(noteId)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }),
    });
}

export function createTextNote(personId: string, content: string): Promise<Person> {
    return request<Person>(`/people/${encodeURIComponent(personId)}/notes/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
    });
}
