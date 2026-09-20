"use client";

import { useState } from "react";
import styles from "./page.module.css";
import { AddPost } from "../../components/AddScreens/AddPost";
import { AddPerson } from "../../components/AddScreens/AddPerson";
import { Plus, FileText, UserPlus } from "lucide-react";
import { Header } from "../../components/Header/Header";
import { PeopleSidebar } from "../../components/PeopleSidebar/PeopleSidebar";
import { TimelineBoard } from "../../components/Timeline/TimelineBoard";

export default function Home() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [isAddPostOpen, setIsAddPostOpen] = useState(false);
  const [isAddPersonOpen, setIsAddPersonOpen] = useState(false);

  const handleSuccess = () => {
    setRefreshKey(prev => prev + 1);
  };

  const handleFabClick = () => {
    setIsPickerOpen(!isPickerOpen);
  };

  const openAddPost = () => {
    setIsPickerOpen(false);
    setIsAddPostOpen(true);
  };

  const openAddPerson = () => {
    setIsPickerOpen(false);
    setIsAddPersonOpen(true);
  };

  return (
    <div className="h-screen w-full flex flex-col md:flex-row overflow-hidden bg-[var(--background)]">

      {/* 1/3 Left Panel */}
      <aside className="w-full md:w-1/3 flex flex-col border-r border-[var(--border)] h-auto md:h-full bg-[var(--background)] z-20 shrink-0 shadow-sm relative">
        <Header />

        <div className="flex-1 overflow-hidden flex flex-col pt-4">
          <div className="flex-1 overflow-hidden flex flex-col">
            <h2 className={`mb-3 px-6 shrink-0 ${styles.title}`}>People</h2>
            <div className="flex-1 overflow-y-auto px-4 pb-20 md:pb-4">
              <PeopleSidebar refreshKey={refreshKey} />
            </div>
          </div>
        </div>
      </aside>

      {/* 2/3 Right Panel */}
      <main className="flex-1 h-full relative flex flex-col bg-[var(--background)] z-10 overflow-hidden">
        <TimelineBoard refreshKey={refreshKey} />
      </main>

      {/* Picker Menu Background Overlay */}
      {isPickerOpen && (
        <div
          className={`fixed inset-0 z-[45] ${styles.backdrop}`}
          onClick={() => setIsPickerOpen(false)}
        />
      )}

      {/* Picker Menu Options */}
      <div className={`fixed bottom-24 right-6 flex flex-col gap-3 z-50 ${styles.pickerMenu} ${isPickerOpen ? 'scale-100 opacity-100 translate-y-0' : 'scale-75 opacity-0 translate-y-10 pointer-events-none'}`}>
        <button
          onClick={openAddPerson}
          className={`flex items-center gap-3 px-4 py-3 ${styles.menuBtn}`}
        >
          <span className={styles.btnText}>Add Person</span>
          <div className={`w-10 h-10 flex items-center justify-center ${styles.iconContainer}`}>
            <UserPlus className={`w-5 h-5 ${styles.icon}`} />
          </div>
        </button>

        <button
          onClick={openAddPost}
          className={`flex items-center gap-3 px-4 py-3 ${styles.menuBtn}`}
        >
          <span className={styles.btnText}>Add Memory</span>
          <div className={`w-10 h-10 flex items-center justify-center ${styles.iconContainer}`}>
            <FileText className={`w-5 h-5 ${styles.icon}`} />
          </div>
        </button>
      </div>

      <button
        onClick={handleFabClick}
        className={`fixed bottom-6 right-6 w-14 h-14 flex justify-center items-center z-50 ${styles.fabBase} ${isPickerOpen ? styles.fabActive : styles.fabInactive}`}
        aria-label="Add new entry"
      >
        <Plus className="w-6 h-6" />
      </button>

      <AddPost
        isOpen={isAddPostOpen}
        onClose={() => setIsAddPostOpen(false)}
        onSuccess={handleSuccess}
      />

      <AddPerson
        isOpen={isAddPersonOpen}
        onClose={() => setIsAddPersonOpen(false)}
        onSuccess={handleSuccess}
      />
    </div>
  );
}
