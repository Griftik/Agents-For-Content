"use client";

import { useState } from "react";
import { markPastAction, type RateResult } from "@/app/actions";
import { copyToClipboard } from "@/lib/clipboard";
import { copyText, splitShare } from "@/lib/invite-share";

/** Прошедшее событие: «Сходил» / «Не сходил», после «Сходил» — ★1–5. Момент рекомендации приходит от API (ref_ask) после 4–5. */
export function PastMark({ slug, initialStatus, initialRating }: { slug: string; initialStatus: string; initialRating: number | null }) {
  const [status, setStatus] = useState(initialStatus);
  const [rating, setRating] = useState<number | null>(initialRating);
  const [ref, setRef] = useState<RateResult["refAsk"]>(null);
  const [note, setNote] = useState("");
  const went = status === "сходил";

  async function mark(w: boolean, r?: number) {
    setNote("");
    const res = await markPastAction(slug, w, r);
    if (!res.ok) return setNote("Не получилось сохранить, попробуй ещё раз.");
    setStatus(w ? "сходил" : "не сходил");
    if (r != null) {
      setNote(rating != null && rating !== r ? `Оценка изменена: ${r} из 5.` : `Оценка ${r} из 5.`);
      setRating(r);
    } else setNote("Отмечено.");
    if (res.refAsk) setRef(res.refAsk);
  }
  async function share() {
    if (!ref) return;
    const { text, url } = splitShare(ref.shareText, ref.url);
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ text, url });
        return setNote("Спасибо.");
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
      }
    }
    setNote((await copyToClipboard(copyText(ref.shareText, ref.url))) ? "Ссылка скопирована." : "Не вышло скопировать.");
  }
  return (
    <div className="pastmark">
      <div className="row" role="group" aria-label="Был ли ты там">
        <button type="button" className="btn" aria-pressed={went} onClick={() => mark(true)}>Сходил</button>
        <button type="button" className="btn" aria-pressed={status === "не сходил"} onClick={() => mark(false)}>Не сходил</button>
      </div>
      {went ? (
        <div className="stars" role="group" aria-label="Оценка">
          {[1, 2, 3, 4, 5].map((v) => (
            <button key={v} type="button" aria-pressed={rating === v} aria-label={`${v} ${v === 1 ? "звезда" : v < 5 ? "звезды" : "звёзд"}`} onClick={() => mark(true, v)}>
              {rating === v ? "● " : ""}{v} ★
            </button>
          ))}
        </div>
      ) : null}
      {ref ? (
        <div className="row">
          <button type="button" className="btn primary" style={{ minHeight: 44 }} onClick={share}>Поделиться</button>
        </div>
      ) : null}
      <p role="status" aria-live="polite" className="muted" style={{ fontSize: 13.5, minHeight: 0 }}>{note}</p>
    </div>
  );
}
