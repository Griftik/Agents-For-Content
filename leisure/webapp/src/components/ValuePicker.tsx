"use client";

import { useEffect, useRef, useState } from "react";
import { saveOnboardingValuesAction } from "@/app/actions";
import { TOP_VALUES } from "@/lib/onboarding";

const DRAFT = "leisure:draft:top";

/**
 * Пять ценностей из 19 по группам. Все чипы активны; шестая не выбирается (счётчик остаётся 5 / 5). В онбординге (inline=false)
 * старт с пустого выбора, пятая сразу отправляет форму (авто-переход на Шаг 2), черновик переживает перезагрузку (sessionStorage).
 * Внутри формы профиля (inline=true) только чипы и счётчик.
 */
export function ValuePicker({ groups, short, initial, inline = false }: { groups: [string, string[]][]; short: Record<string, string>; initial: string[]; inline?: boolean }) {
  const [sel, setSel] = useState<string[]>(initial.slice(0, TOP_VALUES));
  const [busy, setBusy] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const known = groups.flatMap(([, v]) => v);
  const full = sel.length >= TOP_VALUES;

  useEffect(() => {
    if (inline) return;
    try {
      const raw = sessionStorage.getItem(DRAFT);
      const draft = raw ? (JSON.parse(raw) as string[]).filter((v) => known.includes(v)).slice(0, TOP_VALUES) : null;
      if (draft?.length) setSel(draft);
    } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inline]);

  const toggle = (v: string) => {
    if (busy) return;
    setSel((cur) => {
      const next = cur.includes(v) ? cur.filter((x) => x !== v) : cur.length >= TOP_VALUES ? cur : [...cur, v];
      if (!inline) {
        try {
          sessionStorage.setItem(DRAFT, JSON.stringify(next));
        } catch {}
        if (next.length === TOP_VALUES && !cur.includes(v)) {
          setBusy(true);
          setTimeout(() => form.current?.requestSubmit(), 150);
        }
      }
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
                  <input type="checkbox" name="top" value={v} checked={on} onChange={() => toggle(v)} aria-disabled={!on && full ? true : undefined} />
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
    <form
      ref={form}
      action={saveOnboardingValuesAction}
      className="stack"
      style={{ gap: 18 }}
      onSubmit={() => {
        setBusy(true);
        try {
          sessionStorage.removeItem(DRAFT);
        } catch {}
      }}
    >
      {body}
      <div className="row">
        {full ? <button type="submit" className="btn primary" aria-disabled={busy || undefined} disabled={busy}>Дальше</button> : null}
      </div>
    </form>
  );
}
