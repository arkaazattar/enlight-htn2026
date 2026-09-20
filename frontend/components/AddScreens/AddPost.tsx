"use client";

import { useState, useEffect, useRef } from "react";
import { X, Image as ImageIcon, Users } from "lucide-react";
import styles from "./AddScreens.module.css";
import { type Person } from "../../lib/api";
import { SERVER_URL } from "../../lib/config";

interface AddPostProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export function AddPost({ isOpen, onClose, onSuccess }: AddPostProps) {
    const [loading, setLoading] = useState(false);

    const [content, setContent] = useState("");
    const [allPeople, setAllPeople] = useState<Person[]>([]);
    const [taggedPeopleIds, setTaggedPeopleIds] = useState<string[]>([]);
    const [personSearch, setPersonSearch] = useState("");
    
    // Image state
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [imageFile, setImageFile] = useState<File | null>(null);
    const [imagePreview, setImagePreview] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            fetch(`${SERVER_URL}/people`)
                .then(res => res.json())
                .then(setAllPeople)
                .catch(console.error);
        } else {
            setPersonSearch("");
            setContent("");
            setTaggedPeopleIds([]);
            setImageFile(null);
            if (imagePreview) {
                URL.revokeObjectURL(imagePreview);
                setImagePreview(null);
            }
        }
    }, [isOpen]);

    if (!isOpen) return null;

    const toggleTag = (id: string) => {
        setTaggedPeopleIds(prev =>
            prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]
        );
    };

    const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            const file = e.target.files[0];
            setImageFile(file);
            const url = URL.createObjectURL(file);
            if (imagePreview) URL.revokeObjectURL(imagePreview);
            setImagePreview(url);
        }
    };

    const handleSave = async () => {
        if (!content.trim() && !imageFile) {
            alert("Please add a note or an image.");
            return;
        }
        
        setLoading(true);

        try {
            let picture_id: string | null = null;
            
            // 1. Upload picture if exists
            if (imageFile) {
                const formData = new FormData();
                formData.append("file", imageFile);
                
                const picRes = await fetch(`${SERVER_URL}/posts/pictures`, {
                    method: "POST",
                    body: formData
                });
                
                if (!picRes.ok) throw new Error("Failed to upload image");
                const picData = await picRes.json();
                picture_id = picData.picture_id;
            }

            // 2. Create post
            const res = await fetch(`${SERVER_URL}/posts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 
                    text_content: content.trim() || null,
                    picture_id: picture_id,
                    person_ids: taggedPeopleIds
                })
            });
            if (!res.ok) throw new Error("Failed to create post");

            onSuccess();
            onClose();
        } catch (error) {
            console.error("Failed to save post:", error);
            alert("Something went wrong saving the post.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className={`fixed inset-0 z-50 flex flex-col overflow-y-auto ${styles.screen}`}>
            <div className={`sticky top-0 z-10 flex items-center justify-between p-4 ${styles.header}`}>
                <button onClick={onClose} disabled={loading} className={styles.cancelBtn}>
                    Cancel
                </button>
                <h2 className={styles.title}>New Memory</h2>
                <button 
                  onClick={handleSave} 
                  disabled={loading || (!content.trim() && !imageFile)} 
                  className={styles.saveBtn}
                >
                    {loading ? "Saving..." : "Save"}
                </button>
            </div>

            <div className="p-4 flex flex-col gap-6 max-w-2xl mx-auto w-full pb-20">
                
                {/* Image Upload Area */}
                <div>
                    <label className={`block mb-2 ${styles.label}`}>Picture</label>
                    <input 
                        type="file" 
                        accept="image/png, image/jpeg, image/jpg"
                        className="hidden" 
                        ref={fileInputRef}
                        onChange={handleImageChange}
                    />
                    
                    {imagePreview ? (
                        <div className="relative w-full rounded-xl overflow-hidden bg-black aspect-video flex items-center justify-center group">
                            <img src={imagePreview} alt="Preview" className="max-w-full max-h-full object-contain" />
                            <button 
                                onClick={() => {
                                    setImageFile(null);
                                    if (imagePreview) URL.revokeObjectURL(imagePreview);
                                    setImagePreview(null);
                                    if (fileInputRef.current) fileInputRef.current.value = "";
                                }}
                                className="absolute top-2 right-2 p-2 bg-black/60 text-white rounded-full hover:bg-black/80 transition"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                    ) : (
                        <button 
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            className="w-full py-12 border-2 border-dashed border-[var(--border)] rounded-xl text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition flex flex-col items-center gap-3"
                        >
                            <ImageIcon className="w-8 h-8" />
                            <span>Upload a picture</span>
                        </button>
                    )}
                </div>

                {/* Text Note Area */}
                <div>
                    <label className={`block mb-2 ${styles.label}`}>Note Content</label>
                    <textarea
                        value={content}
                        onChange={(e) => setContent(e.target.value)}
                        rows={5}
                        className={`w-full p-3 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${styles.input}`}
                        placeholder="What's on your mind? e.g. Met John at the coffee shop today..."
                    />
                </div>

                {/* People Tagging Area */}
                <div>
                    <label className={`block mb-2 ${styles.label}`}>Tag People</label>
                    <div className="flex flex-col gap-3">
                        {taggedPeopleIds.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {taggedPeopleIds.map(id => {
                                    const person = allPeople.find(p => p.id === id);
                                    if (!person) return null;
                                    return (
                                        <button
                                            key={person.id}
                                            type="button"
                                            onClick={() => toggleTag(person.id)}
                                            className={`px-3 py-1.5 flex items-center gap-1 ${styles.tagActive}`}
                                        >
                                            @{person.label} <X className="w-3 h-3" />
                                        </button>
                                    );
                                })}
                            </div>
                        )}

                        <input
                            value={personSearch}
                            onChange={(e) => setPersonSearch(e.target.value)}
                            className={`w-full p-2 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${styles.input}`}
                            placeholder="Search people..."
                        />

                        {personSearch && (
                            <div className="flex flex-wrap gap-2 mt-1">
                                {allPeople
                                    .filter(p => p.label.toLowerCase().includes(personSearch.toLowerCase()) && !taggedPeopleIds.includes(p.id))
                                    .map(person => (
                                        <button
                                            key={person.id}
                                            type="button"
                                            onClick={() => {
                                                toggleTag(person.id);
                                                setPersonSearch("");
                                            }}
                                            className={`px-3 py-1.5 ${styles.tagInactive}`}
                                        >
                                            @{person.label}
                                        </button>
                                    ))}
                                {allPeople.filter(p => p.label.toLowerCase().includes(personSearch.toLowerCase()) && !taggedPeopleIds.includes(p.id)).length === 0 && (
                                    <p className="text-xs opacity-70">No matching people found.</p>
                                )}
                            </div>
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}
