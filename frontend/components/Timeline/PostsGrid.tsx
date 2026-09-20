"use client";

import Link from "next/link";
import { FileText, Image as ImageIcon, Users } from "lucide-react";
import type { Post } from "../../lib/api";
import { SERVER_URL } from "../../lib/config";

export function PostsGrid({ posts, onSaved }: { posts: Post[]; onSaved: () => void }) {
  return <>
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 pb-8">
      {posts.map(post => (
        <Link 
          href={`/post/${post.id}`}
          key={post.id}
          className="text-left rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 hover:shadow-md flex flex-col gap-3 transition-shadow block"
        >
          {post.picture_url && (
            <div className="w-full h-40 relative rounded-lg overflow-hidden bg-black">
              <img src={`${SERVER_URL}${post.picture_url}`} alt="Post picture" className="w-full h-full object-cover" />
            </div>
          )}
          
          {post.note_content && (
            <div>
              <FileText className="mb-2 h-5 w-5 text-[var(--muted-foreground)]" aria-hidden="true" />
              <span className="block font-medium line-clamp-3 text-sm">
                {post.note_content.trim() || "Empty memory"}
              </span>
            </div>
          )}

          {post.tagged_people.length > 0 && (
            <div className="flex items-center gap-2 mt-auto pt-2 border-t border-[var(--border)]">
              <Users className="h-4 w-4 text-[var(--muted-foreground)]" />
              <div className="flex -space-x-2">
                {post.tagged_people.map(p => (
                  <img 
                    key={p.id} 
                    src={p.image_url ? `${SERVER_URL}${p.image_url}` : "/placeholder.png"} 
                    alt={p.label}
                    title={p.label}
                    className="w-6 h-6 rounded-full border border-[var(--border)] bg-gray-200 object-cover"
                  />
                ))}
              </div>
              <span className="text-xs text-[var(--muted-foreground)] ml-1">
                {post.tagged_people.map(p => p.label).join(", ")}
              </span>
            </div>
          )}
        </Link>
      ))}
    </div>
    {posts.length === 0 && <p>No memories on this date.</p>}
  </>;
}
