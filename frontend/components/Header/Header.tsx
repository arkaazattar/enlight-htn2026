"use client";

import { useTheme } from "next-themes";
import { Moon, Sun, Video } from "lucide-react";
import { AddPost } from "../AddScreens/AddPost";
import styles from "./Header.module.css";
import { useEffect, useState } from "react";
import Link from "next/link";

export function Header() {
    const { theme, setTheme } = useTheme();
    const [mounted, setMounted] = useState(false);
    const [showAddNote, setShowAddNote] = useState(false);

    useEffect(() => {
        const id = setTimeout(() => setMounted(true), 0);
        return () => clearTimeout(id);
    }, []);

    return (
        <header className="flex items-start justify-between sticky top-0 z-10 w-full">
            <div className="flex items-center gap-3">
                <img src="/poster.png" alt="Logo" className="h-25 w-auto object-contain" />
            </div>

            <div className="flex items-center gap-3 mt-4 mr-4">
                <Link
                    href="/cam_view"
                    className="flex items-center gap-2 px-4 py-2 rounded-full border border-[var(--border)] bg-[var(--muted)] text-[var(--foreground)] hover:scale-105 transition shadow-sm"
                >
                    <Video className="w-4 h-4" />
                    <span className="text-sm font-semibold">Cam View</span>
                </Link>

                <button
                    onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                    className={`p-2 flex items-center justify-center ${styles.themeToggle}`}
                    aria-label="Toggle theme"
                >
                    {mounted ? (
                        theme === "dark" ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />
                    ) : (
                        <div className="w-5 h-5" />
                    )}
                </button>
            </div>
        </header>
    );
}
