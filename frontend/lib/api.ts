const API_BASE_URL = "http://localhost:4000";

export interface Person {
    id: string;
    name: string;
    relationship: string | null;
    createdAt: string;
}

export async function fetchPeople(): Promise<Person[]> {
    const res = await fetch(`${API_BASE_URL}/people`);
    if (!res.ok) throw new Error("Failed to fetch people");
    return res.json();
}

export async function createPerson(name: string, relationship?: string, nicknames?: string[]): Promise<Person> {
    const res = await fetch(`${API_BASE_URL}/people`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, relationship }),
    });

    if (!res.ok) throw new Error("Failed to create person");
    const data = await res.json();
    const person = data.person;

    if (nicknames && nicknames.length > 0) {
        for (const nick of nicknames) {
            if (!nick.trim()) continue;
            await fetch(`${API_BASE_URL}/people/${person.id}/nicknames`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ nickname: nick }),
            });
        }
    }

    return person;
}

export interface Note {
    id: string;
    content: string;
    pictureId: string | null;
    createdAt: string;
}

export interface PopulatedNote extends Note {
    taggedPeople: Person[];
}

export async function fetchNotes(): Promise<PopulatedNote[]> {
    const res = await fetch(`${API_BASE_URL}/notes`);
    if (!res.ok) throw new Error("Failed to fetch notes");
    const notes: Note[] = await res.json();

    const populatedNotes = await Promise.all(
        notes.map(async (note) => {
            const pplRes = await fetch(`${API_BASE_URL}/notes/${note.id}/people`);
            const taggedPeople = pplRes.ok ? await pplRes.json() : [];
            return { ...note, taggedPeople };
        })
    );

    return populatedNotes;
}

export async function createNote(content: string, pictureId?: string, taggedPersonIds?: string[]): Promise<Note> {
    const res = await fetch(`${API_BASE_URL}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, pictureId }),
    });

    if (!res.ok) throw new Error("Failed to create note");
    const note = await res.json();

    if (taggedPersonIds && taggedPersonIds.length > 0) {
        for (const personId of taggedPersonIds) {
            await fetch(`${API_BASE_URL}/notes/${note.id}/people/${personId}`, {
                method: "POST",
            });
        }
    }

    return note;
}
