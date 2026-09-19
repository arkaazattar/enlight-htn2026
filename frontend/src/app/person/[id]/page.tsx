"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Image as ImageIcon } from "lucide-react";
import { Header } from "../../../../components/Header/Header";
import { NotesGrid } from "../../../../components/Timeline/NotesGrid";
import styles from "./Person.module.css";

// MOCK DATA
const MOCK_PERSON_DATA = {
    p1: { name: "Alice", relationship: "Sister", image: null, stats: { stories: 12, photos: 45 } },
    p2: { name: "Bob", relationship: "Friend", image: null, stats: { stories: 8, photos: 22 } },
    p3: { name: "Charlie", relationship: "Colleague", image: null, stats: { stories: 3, photos: 1 } },
    p4: { name: "Diana", relationship: "Mentor", image: null, stats: { stories: 24, photos: 109 } },
    p5: { name: "Eve", relationship: "Friend", image: null, stats: { stories: 5, photos: 12 } },
    p6: { name: "Frank", relationship: "Cousin", image: null, stats: { stories: 2, photos: 8 } },
};

const MOCK_NOTES = [
    {
        id: "n1",
        title: "Coffee with Alice",
        content: "Had a great time catching up with Alice at the new downtown cafe.",
        image: "https://images.unsplash.com/photo-1541167760496-1628856ab772?auto=format&fit=crop&q=80&w=400",
        type: "picture",
        date: "Oct 1, 2023",
        taggedPeople: [{ id: "p1", name: "Alice" }],
    },
    { id: "n2", title: "Read a book", content: "Alice lent me a great sci-fi novel.", image: null, type: "silhouette", date: "Oct 1, 2023", taggedPeople: [{ id: "p1", name: "Alice" }] },
    {
        id: "n3",
        title: "Hiking Trip",
        content: "Bob and I went hiking up the local trail.",
        image: "https://images.unsplash.com/photo-1551632811-561732d1e306?auto=format&fit=crop&q=80&w=400",
        type: "picture",
        date: "Oct 5, 2023",
        taggedPeople: [{ id: "p2", name: "Bob" }],
    },
];

export default function PersonPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = use(params);

    const person = MOCK_PERSON_DATA[id as keyof typeof MOCK_PERSON_DATA] || {
        name: "Unknown Person",
        relationship: "Connection",
        image: null,
        stats: { stories: 0, photos: 0 }
    };

    // Filter notes that have this person tagged (using mock data logic for now)
    const personNotes = MOCK_NOTES.filter(note =>
        note.taggedPeople.some(p => p.id === id) ||
        note.title.includes(person.name)
    );

    return (
        <div className={styles.container}>
            <Header />

            <div className={styles.mainContent}>
                {/* Back Button */}
                <div className={styles.backButtonContainer}>
                    <Link href="/" className={styles.backButton}>
                        <ArrowLeft className="w-4 h-4" /> Back to Timeline
                    </Link>
                </div>

                {/* Profile Header */}
                <div className={styles.profileHeader}>
                    <div className={styles.avatarContainer}>
                        {person.image ? (
                            <img src={person.image} alt={person.name} className={styles.avatarImage} />
                        ) : (
                            person.name.charAt(0)
                        )}
                    </div>
                    <h1 className={styles.name}>{person.name}</h1>
                    <span className={styles.relationship}>{person.relationship}</span>

                    <div className={styles.statsContainer}>
                        <div className={styles.statItem}>
                            <span className={styles.statValue}>{person.stats.stories}</span>
                            <span className={styles.statLabel}>Stories</span>
                        </div>
                        <div className={styles.statItem}>
                            <span className={styles.statValue}>{person.stats.photos}</span>
                            <span className={styles.statLabel}>Photos</span>
                        </div>
                    </div>
                </div>

                {/* Feed / Notes Grid */}
                <div className={styles.feedContainer}>
                    <div className={styles.feedHeader}>
                        <h2>Stories with {person.name}</h2>
                    </div>

                    <NotesGrid notesForDay={personNotes} />
                </div>
            </div>
        </div>
    );
}
