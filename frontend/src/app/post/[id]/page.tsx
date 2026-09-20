"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Trash2, FileText, Users } from "lucide-react";
import { Header } from "../../../../components/Header/Header";
import type { Post } from "../../../../lib/api";
import { SERVER_URL } from "../../../../lib/config";
import styles from "../../person/[id]/Person.module.css";

type PostResult = {
    id: string;
    post?: Post;
    error?: string;
};

export default function PostPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = use(params);
    const [result, setResult] = useState<PostResult | null>(null);
    const [loading, setLoading] = useState(true);
    
    const router = useRouter();

    const handleDeletePost = async () => {
        if (!confirm("Are you sure you want to delete this memory? This action cannot be undone.")) return;
        try {
            const res = await fetch(`${SERVER_URL}/posts/${encodeURIComponent(id)}`, { method: "DELETE" });
            if (!res.ok) throw new Error("Failed to delete memory.");
            router.back();
        } catch (err) {
            alert(err instanceof Error ? err.message : "Could not delete memory.");
        }
    };

    useEffect(() => {
        let active = true;
        
        async function loadPost() {
            try {
                const res = await fetch(`${SERVER_URL}/posts/${encodeURIComponent(id)}`);
                if (!res.ok) {
                    if (res.status === 404) throw new Error("Memory not found");
                    throw new Error(`Failed to load memory: ${res.status}`);
                }
                const data = await res.json();
                if (active) setResult({ id, post: data });
            } catch (err) {
                if (active) setResult({ id, error: err instanceof Error ? err.message : "Unknown error" });
            } finally {
                if (active) setLoading(false);
            }
        }
        
        loadPost();
        
        return () => { active = false; };
    }, [id]);

    if (loading) {
        return (
            <div className={`flex min-h-screen flex-col ${styles.container}`}>
                <Header />
                <main className={`flex-1 overflow-hidden flex flex-col p-6 items-center justify-center`}>
                    <div className="w-8 h-8 rounded-full border-4 border-[var(--primary)] border-t-transparent animate-spin mx-auto" />
                </main>
            </div>
        );
    }

    if (result?.error || !result?.post) {
        return (
            <div className={`flex min-h-screen flex-col ${styles.container}`}>
                <Header />
                <main className={`flex-1 overflow-hidden flex flex-col p-6 items-center justify-center`}>
                    <p className="text-red-500 mb-4">{result?.error || "Unknown error occurred"}</p>
                    <button onClick={() => router.back()} className="px-4 py-2 bg-[var(--primary)] text-white rounded-lg">
                        Go Back
                    </button>
                </main>
            </div>
        );
    }

    const post = result.post;

    return (
        <div className={`flex min-h-screen flex-col ${styles.container}`}>
            <Header />
            <main className={`flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 flex flex-col items-center`}>
                <div className="w-full max-w-3xl flex flex-col gap-6">
                <div className={styles.backButtonContainer}>
                    <button
                        onClick={() => router.back()}
                        className={styles.backButton}
                    >
                        <ArrowLeft className="w-4 h-4" />
                        <span>Back</span>
                    </button>

                    <button
                        onClick={handleDeletePost}
                        className="inline-flex items-center gap-2 px-6 py-3 rounded-full font-semibold bg-red-600 text-white hover:bg-red-700 transition shadow-md"
                    >
                        <Trash2 className="w-5 h-5" />
                        <span>Delete Memory</span>
                    </button>
                </div>

                    {/* Post Content */}
                    <div className="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-6 sm:p-8 shadow-sm flex flex-col gap-6">
                        <div className="text-sm text-[var(--muted-foreground)]">
                            {new Date(post.created_at).toLocaleString()}
                        </div>

                        {post.picture_url && (
                            <div className="w-full rounded-xl overflow-hidden bg-black flex justify-center max-h-[60vh]">
                                <img 
                                    src={`${SERVER_URL}${post.picture_url}`} 
                                    alt="Memory picture" 
                                    className="max-w-full object-contain"
                                />
                            </div>
                        )}

                        {post.note_content && (
                            <div className="flex flex-col gap-3">
                                <div className="flex items-center gap-2 text-[var(--muted-foreground)] border-b border-[var(--border)] pb-2">
                                    <FileText className="w-5 h-5" />
                                    <h2 className="font-semibold text-lg text-[var(--foreground)]">Note</h2>
                                </div>
                                <div className="whitespace-pre-wrap text-[var(--foreground)] leading-relaxed">
                                    {post.note_content}
                                </div>
                            </div>
                        )}

                        {post.tagged_people.length > 0 && (
                            <div className="flex flex-col gap-3 pt-4 border-t border-[var(--border)] mt-2">
                                <div className="flex items-center gap-2 text-[var(--muted-foreground)]">
                                    <Users className="w-4 h-4" />
                                    <span className="font-medium text-sm">Tagged People</span>
                                </div>
                                <div className="flex flex-wrap gap-3">
                                    {post.tagged_people.map(p => (
                                        <Link 
                                            href={`/person/${p.id}`} 
                                            key={p.id}
                                            className="flex items-center gap-2 bg-[var(--background)] border border-[var(--border)] rounded-full pr-3 p-1 hover:bg-[var(--accent)] transition-colors"
                                        >
                                            <img 
                                                src={p.image_url ? `${SERVER_URL}${p.image_url}` : "/placeholder.png"} 
                                                alt={p.label}
                                                className="w-6 h-6 rounded-full border border-[var(--border)] object-cover"
                                            />
                                            <span className="text-sm font-medium">{p.label}</span>
                                        </Link>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
}
