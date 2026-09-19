"use client";

import { useState } from "react";
import styles from "./page.module.css";
import { Header } from "../../components/Header/Header";
import { PeopleSidebar } from "../../components/PeopleSidebar/PeopleSidebar";
import { TimelineBoard } from "../../components/Timeline/TimelineBoard";
import { AddPerson } from "../../components/AddScreens/AddPerson";
import { AddNote } from "../../components/AddScreens/AddNote";
import { Plus, User, FileText } from "lucide-react";

export default function Home() {
  const [isAddPersonOpen, setIsAddPersonOpen] = useState(false);
  const [isAddNoteOpen, setIsAddNoteOpen] = useState(false);

  // Picker state
  const [isPickerOpen, setIsPickerOpen] = useState(false);

  const [refreshKey, setRefreshKey] = useState(0);

  const handleSuccess = () => {
    setRefreshKey(prev => prev + 1);
  };

  const handleFabClick = () => {
    // Toggle picker menu
    setIsPickerOpen(!isPickerOpen);
  };

  const openAddPerson = () => {
    setIsPickerOpen(false);
    setIsAddPersonOpen(true);
  };

  const openAddNote = () => {
    setIsPickerOpen(false);
    setIsAddNoteOpen(true);
  };

  return (
    <div className="h-screen w-full flex flex-col md:flex-row overflow-hidden bg-[var(--background)]">

      {/* 1/3 Left Panel */}
      <aside className="w-full md:w-1/3 flex flex-col border-r border-[var(--border)] h-auto md:h-full bg-[var(--background)] z-20 shrink-0 shadow-sm relative">
        <Header />

        <div className="flex-1 overflow-hidden flex flex-col pt-4">
          <div className="px-6 mb-6 flex flex-col items-center md:items-start text-center md:text-left gap-4 shrink-0">
            <div className="flex flex-col">
              <h2 className={styles.title}>My Memories</h2>
              <p className={`mt-1 max-w-sm ${styles.subtitle}`}>
                Helping me remember people, events, and the stories.
              </p>
            </div>
          </div>

          <div className="flex-1 overflow-hidden flex flex-col">
            <h3 className={`mb-3 px-6 shrink-0 ${styles.sectionTitle}`}>People</h3>
            <div className="flex-1 overflow-y-auto px-4 pb-20 md:pb-4">
              <PeopleSidebar />
            </div>
          </div>
        </div>
      </aside>

      {/* 2/3 Right Panel */}
      <main className="flex-1 h-full relative flex flex-col bg-[var(--background)] z-10 overflow-hidden">
        <TimelineBoard />
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
          onClick={openAddNote}
          className={`flex items-center gap-3 px-4 py-3 ${styles.menuBtn}`}
        >
          <span className={styles.btnText}>Add Note</span>
          <div className={`w-10 h-10 flex items-center justify-center ${styles.iconContainer}`}>
            <FileText className={`w-5 h-5 ${styles.icon}`} />
          </div>
        </button>

        <button
          onClick={openAddPerson}
          className={`flex items-center gap-3 px-4 py-3 ${styles.menuBtn}`}
        >
          <span className={styles.btnText}>Add Person</span>
          <div className={`w-10 h-10 flex items-center justify-center ${styles.iconContainer}`}>
            <User className={`w-5 h-5 ${styles.icon}`} />
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

      <AddPerson
        isOpen={isAddPersonOpen}
        onClose={() => setIsAddPersonOpen(false)}
        onSuccess={handleSuccess}
      />
      <AddNote
        isOpen={isAddNoteOpen}
        onClose={() => setIsAddNoteOpen(false)}
        onSuccess={handleSuccess}
      />
    </div>
  );
}
