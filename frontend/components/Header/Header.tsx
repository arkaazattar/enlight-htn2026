"use client";

import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import styles from "./Header.module.css";
import { useEffect, useState } from "react";

export function Header() {
    const { theme, setTheme } = useTheme();
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        const id = setTimeout(() => setMounted(true), 0);
        return () => clearTimeout(id);
    }, []);

    return (
        <header className="flex items-center justify-between p-4 sticky top-0 z-10 w-full max-w-2xl mx-auto">
            <div className="flex items-center gap-3">
                <div className={`w-10 h-10 flex items-center justify-center ${styles.logo}`}>
                    R
                </div>
                <h1 className={styles.title}>Remi</h1>
            </div>

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
        </header>
    );
}
