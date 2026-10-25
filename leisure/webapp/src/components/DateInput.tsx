"use client";

import { useEffect } from "react";

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

/** Выбранный чип дня прокручивается в видимую зону ряда (ряд прокручивается, календарь закреплён справа). */
export function ScrollToCurrent() {
  useEffect(() => {
    const el = document.querySelector<HTMLElement>('.daystrip [aria-current="true"]');
    el?.scrollIntoView({ block: "nearest", inline: "center" });
  }, []);
  return null;
}
