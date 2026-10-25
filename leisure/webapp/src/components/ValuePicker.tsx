"use client";

import { useRef, useState } from "react";
import { saveOnboardingValuesAction } from "@/app/actions";
import { TOP_VALUES } from "@/lib/onboarding";

/** Шаг 1 из 2: пять главных ценностей из 19 в четырёх группах. Счётчик «Выбрано N из 5»; шестую выбрать нельзя; «Дальше» появляется на пятой. */
/**
 * Пять ценностей из 19 по группам. В онбординге (inline=false) пятая сразу отправляет форму (авто-переход на Шаг 2, FLOW-APP);
 * внутри формы профиля (inline=true) только чипы и счётчик.
 */
export function ValuePicker({ groups, short, initial, inline = false }: { groups: [string, string[]][]; short: Record<string, string>; initial: string[]; inline?: boolean }) {
  const [sel, setSel] = useState<string[]>(initial.slice(0, TOP_VALUES));
  const form = useRef<HTMLFormElement>(null);
  const full = sel.length >= TOP_VALUES;
  const toggle = (v: string) => {
    setSel((cur) => {
      const next = cur.includes(v) ? cur.filter((x) => x !== v) : cur.length >= TOP_VALUES ? cur : [...cur, v];
      if (!inline && next.length === TOP_VALUES && !cur.includes(v)) setTimeout(() => form.current?.requestSubmit(), 150);
      return next;
    });
  };
  const body = (
    <>
      <p className="svc fg" role="status" aria-live="polite">{sel.length} / {TOP_VALUES}</p>
      {groups.map(([name, values]) => (
        <fieldset key={name} className="group" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="svc" style={{ marginBottom: 8 }}>{name}</legend>
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
    </>
  );
  if (inline) return <div className="stack" style={{ gap: 14 }}>{body}</div>;
  return (
    <form ref={form} action={saveOnboardingValuesAction} className="stack" style={{ gap: 18 }}>
      {body}
      <div className="row">
        {full ? <button type="submit" className="btn primary">Дальше</button> : null}
      </div>
    </form>
  );
}
