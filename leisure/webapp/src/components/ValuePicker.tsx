"use client";

import { useState } from "react";
import { saveOnboardingValuesAction } from "@/app/actions";
import { TOP_VALUES } from "@/lib/onboarding";

/** Шаг 1 из 2: пять главных ценностей из 19 в четырёх группах. Счётчик «Выбрано N из 5»; шестую выбрать нельзя; «Дальше» появляется на пятой. */
export function ValuePicker({ groups, short, initial }: { groups: [string, string[]][]; short: Record<string, string>; initial: string[] }) {
  const [sel, setSel] = useState<string[]>(initial.slice(0, TOP_VALUES));
  const full = sel.length >= TOP_VALUES;
  const toggle = (v: string) => setSel((cur) => (cur.includes(v) ? cur.filter((x) => x !== v) : cur.length >= TOP_VALUES ? cur : [...cur, v]));
  return (
    <form action={saveOnboardingValuesAction} className="stack" style={{ gap: 18 }}>
      <p role="status" aria-live="polite">
        Выбрано {sel.length} из {TOP_VALUES}{sel.length ? `: ${sel.map((v) => short[v] ?? v).join(", ")}` : ""}
      </p>
      {groups.map(([name, values]) => (
        <fieldset key={name} className="group" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="eyebrow" style={{ marginBottom: 8 }}>{name}</legend>
          <div className="pick">
            {values.map((v) => {
              const on = sel.includes(v);
              return (
                <label key={v}>
                  <input type="checkbox" name="top" value={v} checked={on} disabled={!on && full} onChange={() => toggle(v)} />
                  <span>{short[v] ?? v}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
      ))}
      <div className="row">
        <button type="button" className="btn quiet" onClick={() => (window.history.length > 1 ? window.history.back() : window.location.assign("/digest"))}>
          ← Назад
        </button>
        {full ? <button type="submit" className="btn primary">Дальше →</button> : <span className="muted" style={{ fontSize: 13.5 }}>Дальше появится, когда выберешь пять.</span>}
      </div>
    </form>
  );
}
