export interface Person {
    id: string;
    name: string | null;
    label: string;
    facts: string[];
    context: Record<string, unknown>;
    picture_ids: string[];
    note_ids: string[];
    post_ids: string[];
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

export interface Post {
    id: string;
    created_at: string;
    note_content: string | null;
    picture_url: string | null;
    tagged_people: {
        id: string;
        label: string;
        image_url: string;
    }[];
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


