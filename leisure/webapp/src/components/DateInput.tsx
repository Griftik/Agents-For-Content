"use client";

/** Календарь в DayStrip: при выборе даты сразу переходим (без JS форма отправляется кнопкой Enter). */
export function DateInput({ today, segment }: { today: string; segment: string }) {
  return (
    <input
      type="date"
      name="day"
      min={today}
      aria-label="Дата"
      onChange={(e) => {
        if (e.target.value) window.location.assign(`/digest?day=${e.target.value}&seg=${segment}`);
      }}
    />
  );
}
