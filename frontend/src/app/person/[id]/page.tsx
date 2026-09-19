"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Image as ImageIcon } from "lucide-react";
import { Header } from "../../../../components/Header/Header";
import { NotesGrid } from "../../../../components/Timeline/NotesGrid";
import styles from "./Person.module.css";

// TEMPLATE DATA
const MOCK_PERSON_DATA: Record<string, any> = {};
const MOCK_NOTES: any[] = [];

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
