"use client";

import { useRef, useState } from "react";
import { tweakLearnedAction } from "@/app/actions";

type Entry = { kind: "tag" | "cat"; key: string; w: number };

/** «Что я о тебе узнал»: чипы `+ Джаз` / `− Вечеринки`; нажатие открывает лист Больше · Меньше · Сбросить. */
export function Learned({ tags, cats }: { tags: Record<string, number>; cats: Record<string, number> }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [sel, setSel] = useState<Entry | null>(null);
  const [busy, setBusy] = useState(false);
  const entries: Entry[] = [
    ...Object.entries(cats).map(([key, w]) => ({ kind: "cat" as const, key, w: Number(w) })),
    ...Object.entries(tags).map(([key, w]) => ({ kind: "tag" as const, key, w: Number(w) })),
  ]
    .filter((e) => Math.abs(e.w) >= 0.5)
    .sort((a, b) => Math.abs(b.w) - Math.abs(a.w))
    .slice(0, 24);
  if (!entries.length) return <p className="muted">Пока ничего: отмечай «Иду» и «Не моё».</p>;
  const open = (e: Entry) => {
    setSel(e);
    dlg.current?.showModal();
  };
  const apply = async (op: "more" | "less" | "reset") => {
    if (!sel || busy) return;
    setBusy(true);
    await tweakLearnedAction(sel.kind, sel.key, op);
    setBusy(false);
    dlg.current?.close();
  };
  return (
    <>
      <div className="learned">
        {entries.map((e) => (
          <button key={`${e.kind}:${e.key}`} type="button" className={e.w > 0 ? "plus" : "minus"} onClick={() => open(e)} aria-label={`${e.w > 0 ? "плюс" : "минус"} ${e.key}`}>
            {e.w > 0 ? "+ " : "− "}{e.key}
          </button>
        ))}
      </div>
      <dialog ref={dlg} className="sheet" aria-labelledby="lrn-h">
        <h2 id="lrn-h">{sel?.key}</h2>
        <div className="row">
          <button type="button" className="btn primary" disabled={busy} onClick={() => apply("more")}>Больше</button>
          <button type="button" className="btn" disabled={busy} onClick={() => apply("less")}>Меньше</button>
          <button type="button" className="btn quiet" disabled={busy} onClick={() => apply("reset")}>Сбросить</button>
        </div>
      </dialog>
    </>
  );
}
