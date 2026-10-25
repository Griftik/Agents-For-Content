"use client";

import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { feedDecideAction, undoDecisionAction, type FeedDecision } from "@/app/actions";
import type { FeedItem } from "@/lib/api-types";
import { timeLine } from "@/lib/feed";
import { dateShort, placeLine, priceLabel, wdShort } from "@/lib/format";
import { InviteButton } from "./InviteButton";

const THRESHOLD = 0.35; // доля ширины
const VELOCITY = 0.6; // пикс/мс
const UNDO_MS = 5000;

type Toast = { text: string; slug: string } | null;

function Card({ it, today, counter, style, className, behind, onPointerDown, onPointerMove, onPointerUp, dx }: {
  it: FeedItem; today: string; counter: string; style?: React.CSSProperties; className?: string; behind?: boolean;
  onPointerDown?: (e: RPointerEvent) => void; onPointerMove?: (e: RPointerEvent) => void; onPointerUp?: (e: RPointerEvent) => void; dx?: number;
}) {
  const ev = it.event;
  const { venue, rest } = placeLine(ev);
  const price = priceLabel(ev);
  const w = typeof window === "undefined" ? 390 : window.innerWidth;
  const k = Math.min(1, Math.abs(dx ?? 0) / (w * THRESHOLD));
  const isToday = it.day === today;
  const end = ev.end_time && ev.end_time !== ev.start_time ? `до ${ev.end_time}` : "";
  const near = timeLine(it.day, today, null, null); // «Сегодня», «Завтра», «Сб, 31 окт»
  const wd = `${wdShort(it.day)} ${dateShort(it.day)}`;
  const dayText = near === wd || /\d/.test(near) ? wd : `${near} · ${wd}`;
  return (
    <article
      className={`fcard ${className ?? ""}${behind ? " behind" : ""}`}
      style={style}
      aria-hidden={behind || undefined}
      role={behind ? undefined : "region"}
      aria-label={behind ? undefined : ev.title}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {it.cover ? (
        <div className="cover">
          {/* обложка приходит с чужого домена источника: next/image требует список доменов, здесь обычный img */}
          <img src={it.cover} alt="" loading="lazy" draggable={false} /> {/* eslint-disable-line @next/next/no-img-element */}
        </div>
      ) : null}
      <div className="top">
        {it.can_make_it ? <span className="svc ok">Успеваешь</span> : <span />}
        <span className="svc">{counter}</span>
      </div>
      <div className="when">
        {ev.start_time ? <b className={isToday ? "" : "sm"}>{ev.start_time}</b> : null}
        <span className="svc fg">{[dayText, end].filter(Boolean).join(" · ")}</span>
      </div>
      <h2>{ev.title}</h2>
      <p className="place">{venue}{rest ? ` · ${rest}` : ""}</p>
      <div className="tear" aria-hidden="true" />
      {ev.description ? <p className="desc">{ev.description}</p> : ev.tags?.length ? <p className="desc svc">{ev.tags.slice(0, 4).join(" · ")}</p> : null}
      <div className="bot">
        <span className="svc">{[ev.free ? "Бесплатно" : price, ev.category].filter(Boolean).join(" · ")}</span>
        <a href={`/e/${ev.slug}`} draggable={false}>Подробнее</a>
      </div>
      <span className="stamp go" style={{ opacity: (dx ?? 0) > 0 ? k : 0 }} aria-hidden="true">Иду</span>
      <span className="stamp no" style={{ opacity: (dx ?? 0) < 0 ? k : 0 }} aria-hidden="true">Не моё</span>
    </article>
  );
}

/**
 * Лента: одна карточка на экран, «Иду» и «Не моё» кнопками и свайпом (жест повторяет кнопки, не заменяет их). После действия 5 секунд
 * доступно «Отменить». Стрелки ←/→ делают то же, Enter — «Подробнее». Без JS страница показывает первую карточку и ссылку «Подробнее».
 */
export function FeedDeck({ items, today, emptyLabel, nextLabel, nextHref, allHref }: {
  items: FeedItem[]; today: string;
  /** T-FEED-END / T-FEED-LATE: когда все карточки просмотрены. */
  emptyLabel: string; nextLabel: string; nextHref: string | null;
  /** T-FEED-EMPTY: лента с самого начала пуста — «Пока ничего», кнопки «Всё» (если выбрано направление) и следующий день. */
  allHref: string | null;
}) {
  const [idx, setIdx] = useState(0);
  const [dx, setDx] = useState(0);
  const [phase, setPhase] = useState<"idle" | "drag" | "settle" | "fly">("idle");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [inPlan, setInPlan] = useState<FeedItem | null>(null);
  const drag = useRef<{ x: number; t: number; id: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const sheet = useRef<HTMLDialogElement>(null);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    return () => clearTimeout(timer.current);
  }, []);

  const cur = items[idx];
  const next = items[idx + 1];

  async function act(status: FeedDecision) {
    if (!cur || busy) return;
    setBusy(true);
    const dir = status === "иду" ? 1 : -1;
    if (!reduced.current) {
      setPhase("fly");
      setDx(dir * (window.innerWidth + 80));
      await new Promise((r) => setTimeout(r, 180));
    }
    const r = await feedDecideAction(cur.event.slug, cur.day, status);
    setPhase("idle");
    setDx(0);
    if (!r.ok) {
      setBusy(false);
      setToast({ text: "Не получилось записать. Попробуй ещё раз.", slug: "" });
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setToast(null), 3000);
      return;
    }
    try {
      navigator.vibrate?.(10);
    } catch {}
    const done = cur;
    setIdx((i) => i + 1);
    setBusy(false);
    if (status === "иду") {
      setInPlan(done);
      sheet.current?.showModal();
    }
    setToast({ text: status === "иду" ? "В плане" : "Убрал.", slug: done.event.slug });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), UNDO_MS);
  }

  async function undo() {
    if (!toast?.slug) return;
    const slug = toast.slug;
    setToast(null);
    clearTimeout(timer.current);
    sheet.current?.close();
    const r = await undoDecisionAction(slug);
    if (r.ok) setIdx((i) => Math.max(0, i - 1));
  }

  // жест: начинается после 10 px по горизонтали, иначе это прокрутка
  const onDown = (e: RPointerEvent) => {
    if (busy || e.button !== 0) return;
    drag.current = { x: e.clientX, t: e.timeStamp, id: e.pointerId };
  };
  const onMove = (e: RPointerEvent) => {
    if (!drag.current || drag.current.id !== e.pointerId) return;
    const d = e.clientX - drag.current.x;
    if (phase !== "drag" && Math.abs(d) < 10) return;
    if (phase !== "drag") {
      setPhase("drag");
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    }
    setDx(d);
  };
  const onUp = (e: RPointerEvent) => {
    if (!drag.current || drag.current.id !== e.pointerId) return;
    const d = e.clientX - drag.current.x;
    const v = Math.abs(d) / Math.max(1, e.timeStamp - drag.current.t);
    drag.current = null;
    if (phase !== "drag") return;
    if (Math.abs(d) >= window.innerWidth * THRESHOLD || v > VELOCITY) {
      void act(d > 0 ? "иду" : "не моё");
    } else {
      setPhase("settle");
      setDx(0);
      setTimeout(() => setPhase("idle"), 220);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!cur || (e.target as HTMLElement)?.closest?.("input, textarea, dialog")) return;
      if (e.key === "ArrowRight") void act("иду");
      else if (e.key === "ArrowLeft") void act("не моё");
      else if (e.key === "Enter") window.location.assign(`/e/${cur.event.slug}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur, busy]);

  if (!cur) {
    const none = items.length === 0;
    return (
      <div className="fempty" role="status">
        <h2>{none ? "Пока ничего" : emptyLabel}</h2>
        <div className="row" style={{ justifyContent: "center" }}>
          {none && allHref ? <a className="btn primary" href={allHref}>Всё</a> : null}
          {nextHref ? <a className={`btn${none && allHref ? "" : " primary"}`} href={nextHref}>{nextLabel}</a> : null}
        </div>
        {toast ? <Toasty toast={toast} onUndo={undo} /> : null}
      </div>
    );
  }
  const rot = phase === "drag" || phase === "fly" ? Math.max(-8, Math.min(8, dx / 40)) : 0;
  return (
    <div className="deck">
      <div className="deck-stage" aria-live="polite">
        {next ? <Card it={next} today={today} counter="" behind /> : null}
        <Card
          key={cur.event.slug + cur.day}
          it={cur}
          today={today}
          counter={`${idx + 1} / ${items.length}`}
          className={phase === "drag" ? "drag" : phase === "settle" ? "settle" : phase === "fly" ? "fly" : ""}
          style={{ transform: `translateX(${dx}px) rotate(${rot}deg)` }}
          dx={dx}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
        />
      </div>
      {next ? <div className="fc-next" aria-hidden="true" style={{ marginTop: -12 }} /> : null}
      <div className="actionbar" role="group" aria-label="Решение">
        <button type="button" className="btn" aria-disabled={busy || undefined} onClick={() => act("не моё")}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          Не моё
        </button>
        <button type="button" className="btn primary" aria-disabled={busy || undefined} onClick={() => act("иду")}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12l5 5L19 7" /></svg>
          Иду
        </button>
      </div>
      {toast ? <Toasty toast={toast} onUndo={undo} /> : null}
      <dialog ref={sheet} className="sheet" aria-labelledby="inplan-h" onClose={() => setInPlan(null)}>
        <h2 id="inplan-h">В плане</h2>
        {inPlan ? (
          <>
            <p>«{inPlan.event.title}», {timeLine(inPlan.day, today, inPlan.event.start_time, inPlan.event.end_time).toLowerCase()}{inPlan.event.venue ? `, ${inPlan.event.venue}` : ""}.</p>
            <div className="row">
              {/^https?:\/\//.test(inPlan.event.url) ? <a className="btn primary" href={inPlan.event.url} target="_blank" rel="noopener noreferrer">К билетам</a> : null}
              <a className="btn cal" href={`/api/events/${inPlan.event.slug}/ics?day=${inPlan.day}`} download>Календарь</a>
              <InviteButton slug={inPlan.event.slug} day={inPlan.day} small={false} />
              <button type="button" className="btn quiet" onClick={() => sheet.current?.close()}>Дальше</button>
            </div>
          </>
        ) : null}
      </dialog>
    </div>
  );
}

function Toasty({ toast, onUndo }: { toast: NonNullable<Toast>; onUndo: () => void }) {
  return (
    <div className="toast" role="status">
      {toast.text}
      {toast.slug ? <button type="button" onClick={onUndo}>Отменить</button> : null}
    </div>
  );
}
