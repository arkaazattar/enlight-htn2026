import styles from "./PeopleSidebar.module.css";
import { User } from "lucide-react";
import Link from "next/link";

const MOCK_PEOPLE = [
    { id: "1", name: "1", image: null },
    { id: "2", name: "2", image: null },
    { id: "3", name: "3", image: null },
    { id: "4", name: "4", image: null },
    { id: "5", name: "5", image: null },
    { id: "6", name: "6", image: null },
    { id: "7", name: "7", image: null },
    { id: "8", name: "8", image: null },
    { id: "9", name: "9", image: null },
    { id: "10", name: "10", image: null },
    { id: "11", name: "11", image: null },
    { id: "12", name: "12", image: null },
    { id: "13", name: "13", image: null },
    { id: "14", name: "14", image: null },
];

export function PeopleSidebar() {
    return (
        <div className={`w-full h-full overflow-y-auto ${styles.sidebar}`}>
            <div className={`grid grid-cols-3 w-full ${styles.grid}`}>
                {MOCK_PEOPLE.map((person) => (
                    <Link
                        key={person.id}
                        href={`/person/p${person.id}`}
                        className={`relative w-full aspect-square flex items-center justify-center overflow-hidden ${styles.person}`}
                    >
                        {person.image ? (
                            <img
                                src={person.image}
                                alt={person.name}
                                className={styles.image}
                            />
                        ) : (
                            <User className={styles.icon} />
                        )}

                        <span className={styles.name}>{person.name}</span>
                    </Link>
                ))}
            </div>
        </div>
    );
}