"use client";

import { useState } from "react";

/** Ползунок ценности 0–5 с живым значением. Без JS работает как обычный range, число показывает исходное значение. */
export function Slider({ name, label, value, top }: { name: string; label: string; value: number; top: boolean }) {
  const [v, setV] = useState(value);
  const id = `s-${name}`;
  return (
    <div className="vrow">
      <label className={`nm${top ? " top" : ""}`} htmlFor={id}>{label}</label>
      <input id={id} type="range" name={name} min={0} max={5} step={1} value={v} onChange={(e) => setV(Number(e.target.value))}
        aria-valuetext={`${v} из 5`} />
      <output htmlFor={id} aria-hidden="true">{v}</output>
    </div>
  );
}
