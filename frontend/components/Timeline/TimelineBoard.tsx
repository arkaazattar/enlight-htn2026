"use client";

import { useMemo, useState, useCallback } from "react";
import styles from "./TimelineBoard.module.css";
import { NotesGrid } from "./NotesGrid";

const MOCK_DAYS = [
  { date: "2023-10-01", id: "d1" },
  { date: "2023-10-05", id: "d2" },
  { date: "2023-10-12", id: "d3" },
  { date: "2023-10-18", id: "d4" },
  { date: "2023-11-02", id: "d5" },
  { date: "2023-11-15", id: "d6" },
];

const MOCK_NOTES = {
  d1: [
    {
      id: "n1",
      title: "Coffee with Alice",
      image:
        "https://images.unsplash.com/photo-1541167760496-1628856ab772?auto=format&fit=crop&q=80&w=400",
      type: "picture",
    },
    { id: "n2", title: "Read a book", image: null, type: "silhouette" },
  ],
  d2: [
    {
      id: "n3",
      title: "Hiking Trip",
      image:
        "https://images.unsplash.com/photo-1551632811-561732d1e306?auto=format&fit=crop&q=80&w=400",
      type: "picture",
    },
    { id: "n4", title: "Dinner party", image: null, type: "silhouette" },
    {
      id: "n5",
      title: "Sunset view",
      image:
        "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?auto=format&fit=crop&q=80&w=400",
      type: "picture",
    },
  ],
  d3: [{ id: "n6", title: "Work meeting", image: null, type: "silhouette" }],
};

const TIMELINE_WIDTH = 3600;

function getDayOfYear(dateString: string) {
  const [year, month, day] = dateString.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  const start = new Date(year, 0, 1);
  const diff = date.getTime() - start.getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function formatMonthYearFromScroll(scrollLeft: number, maxScroll: number) {
  const safeRatio = maxScroll <= 0 ? 0 : scrollLeft / maxScroll;
  const approxDayIndex = Math.min(364, Math.max(0, Math.floor(safeRatio * 364)));
  const date = new Date(2023, 0, 1 + approxDayIndex);

  return date.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

export function TimelineBoard() {
  const [selectedDayId, setSelectedDayId] = useState("d2");
  const [currentMonthYear, setCurrentMonthYear] = useState("October 2023");

  const notesForDay = MOCK_NOTES[selectedDayId as keyof typeof MOCK_NOTES] || [];

  const mappedDays = useMemo(() => {
    return MOCK_DAYS.map((day) => {
      const dayOfYear = getDayOfYear(day.date);
      const left = (dayOfYear / 364) * TIMELINE_WIDTH;
      const notesCount = (MOCK_NOTES[day.id as keyof typeof MOCK_NOTES] || []).length;

      return {
        ...day,
        dayOfYear,
        left,
        notesCount,
      };
    });
  }, []);

  const monthLabels = useMemo(() => {
    return Array.from({ length: 12 }, (_, monthIndex) => {
      const date = new Date(2023, monthIndex, 1);
      const dayOfYear = Math.floor(
        (date.getTime() - new Date(2023, 0, 1).getTime()) / (1000 * 60 * 60 * 24)
      );
      const left = (dayOfYear / 364) * TIMELINE_WIDTH;

      return {
        label: date.toLocaleDateString(undefined, { month: "short" }),
        left,
      };
    });
  }, []);

  const selectedDay = MOCK_DAYS.find((d) => d.id === selectedDayId);

  const handleTimelineScroll = useCallback((scrollLeft: number, maxScroll: number) => {
    setCurrentMonthYear(formatMonthYearFromScroll(scrollLeft, maxScroll));
  }, []);

  return (
    <div className={`w-full h-full flex flex-col ${styles.board}`}>

      {/* Date Selector */}
      <div className="w-full border-b border-[var(--border)] bg-[var(--background)] px-6 py-4 shrink-0">
        <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-3">Select Date</h3>
        <div className="flex gap-2 overflow-x-auto pb-2 hideScrollbar">
          {MOCK_DAYS.map((day) => {
            const dateObj = new Date(day.date);
            // Quick fix to avoid timezone offset issues for mock data
            const displayDate = new Date(dateObj.getTime() + Math.abs(dateObj.getTimezoneOffset() * 60000));
            return (
              <button
                key={day.id}
                onClick={() => setSelectedDayId(day.id)}
                className={`flex-shrink-0 px-4 py-2 rounded-full text-sm font-medium transition-all ${selectedDayId === day.id
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)] shadow-md"
                    : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]"
                  }`}
              >
                {displayDate.toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric"
                })}
              </button>
            );
          })}
        </div>
      </div>
      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <h2 className={`mb-8 ${styles.dayHeader}`}>
          Stories from {selectedDay?.date}
        </h2>
        <NotesGrid notesForDay={notesForDay} />
      </div>
    </div>
  );
}