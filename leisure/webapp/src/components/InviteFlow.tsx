"use client";

import { startTransition, useActionState, useEffect, useRef, useState, type ReactNode } from "react";
import { acceptInviteAction, declineInviteAction, openInviteAction, postponeOfferAction, type AcceptState } from "@/app/actions";
import type { InviteAcceptStatus } from "@/lib/api-types";

export type InviteFlowProps = {
  code: string;
  slug: string;
  day: string;
  title: string;
  /** «суббота, 24 окт» и «13:00–15:00» — уже отформатированы на сервере. */
  dayText: string;
  timeText: string;
  inviterName: string | null;
  /** Пригласивший удалил профиль (status gone): шапка «Тебя зовут на событие», кнопки без слова «вместе». */
  gone: boolean;
  authed: boolean;
  /** Согласие на обработку данных уже дано (profile.has_consent): галочка не нужна. */
  hasConsent: boolean;
  /** Прежний ответ друга: «иду, суббота». */
  prior: string | null;
  /** Карточка события, отрисованная на сервере. */
  card: ReactNode;
};

const IDLE: AcceptState = { phase: "idle" };

/**
 * Блок действий приглашённого (T-INVITE-CARD, FLOW-INVITE В1–В3). Галочка согласия стоит на странице заранее; «Иду вместе»
 * и «Может быть» запоминают выбор, а запись происходит, как только готовы оба условия — сессия и согласие, в любом порядке.
 * Поэтому до записанного «иду»: ссылка 1, галочка 1, кнопка 1 (см. lib/invite.ts: inviteeTaps).
 */
export function InviteFlow(p: InviteFlowProps) {
  const [state, formAction, pending] = useActionState(acceptInviteAction, IDLE);
  const [consent, setConsent] = useState(false);
  const [wanted, setWanted] = useState<InviteAcceptStatus | null>(null);
  const [forceConsent, setForceConsent] = useState(false);
  const [name, setName] = useState("");
  const last = useRef<InviteAcceptStatus | null>(null);
  const box = useRef<HTMLInputElement>(null);

  const consentNeeded = forceConsent || !p.hasConsent;
  const ready = p.authed && (!consentNeeded || consent);

  // Страница приглашения показана: учёт открытия, один раз на код за вкладку. Профиль без согласия API не создаёт.
  useEffect(() => {
    if (!p.authed) return;
    const key = `leisure:open:${p.code}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch {}
    void openInviteAction(p.code);
  }, [p.authed, p.code]);

  // Запись: выбор запомнен, и все условия выполнены.
  useEffect(() => {
    if (!wanted || !ready || pending) return;
    const fd = new FormData();
    fd.set("code", p.code);
    fd.set("slug", p.slug);
    fd.set("day", p.day);
    fd.set("status", wanted);
    if (consentNeeded) fd.set("needs_consent", "1");
    if (consent) fd.set("consent", "on");
    if (name.trim()) fd.set("name", name.trim());
    last.current = wanted;
    setWanted(null);
    startTransition(() => formAction(fd));
  }, [wanted, ready, pending, consent, consentNeeded, name, p.code, p.slug, p.day, formAction]);

  // Сервер сказал, что согласия нет (например, профиль-заготовка): показываем галочку и ждём её.
  useEffect(() => {
    if (state.phase === "error" && state.error === "consent") {
      setForceConsent(true);
      setWanted(last.current);
    }
  }, [state]);

  const needMsg = wanted != null && consentNeeded && !consent;
  useEffect(() => {
    if (needMsg) box.current?.focus();
  }, [needMsg]);

  if (state.phase === "done") return <Done {...p} state={state} />;

  const busy = pending || wanted != null;
  const choose = (s: InviteAcceptStatus) => {
    if (busy && (consentNeeded ? consent : true)) return; // запрос уже идёт: второго POST не будет
    setWanted(s);
  };
  const names = p.gone ? { going: "Иду", title: "Тебя зовут на событие" } : { going: "Иду вместе", title: `${p.inviterName ?? "Друг"} зовёт тебя` };

  return (
    <div className="wrap">
      <main id="main" className="public reveal" style={{ gap: 12, paddingTop: 8 }}>
        <header className="invite-head">
          <span className="svc">Приглашение</span>
          <h1>{names.title}</h1>
          <span className="svc fg">{[p.dayText, p.timeText].filter(Boolean).join(" · ")}</span>
        </header>
        {p.prior ? <span className="svc">Прежний ответ: {p.prior}</span> : null}
        {p.card}

        <section className="invite-actions" aria-labelledby="act-h">
          <h2 id="act-h" className="sr">Ответить на приглашение</h2>
          {consentNeeded ? (
            <div>
              <label className="consent">
                <input ref={box} type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} aria-describedby={needMsg ? "consent-need" : undefined} />
                <span>
                  Даю согласие на обработку моих ответов и решений, чтобы записать меня в план и подбирать события. Данные хранятся в России. Подробнее
                  в <a href="/policy" target="_blank" rel="noopener noreferrer">политике обработки данных</a>.
                </span>
                <small>Согласие можно отозвать в любой момент: «Удалить мои данные» в профиле.</small>
              </label>
              {needMsg ? <p id="consent-need" role="alert" className="field-error" style={{ marginTop: 8 }}>Отметь согласие, и я запишу твой выбор.</p> : null}
            </div>
          ) : null}
          {consentNeeded ? (
            <label className="stack" style={{ gap: 4 }}>
              <span className="svc">Имя, необязательно</span>
              <input name="name" type="text" maxLength={80} autoComplete="given-name" value={name} onChange={(e) => setName(e.target.value)} className="field" />
            </label>
          ) : null}
          <div className="stickybar" style={{ padding: "4px 0 0" }}>
            <button type="button" className="btn" onClick={() => choose("maybe")} aria-disabled={pending || undefined}>Может быть</button>
            <button type="button" className="btn primary" onClick={() => choose("going")} aria-busy={pending || undefined} aria-disabled={pending || undefined}>{names.going}</button>
          </div>
          <form action={declineInviteAction} className="row" style={{ justifyContent: "center" }}>
            <input type="hidden" name="code" value={p.code} />
            <button type="submit" className="btn link" style={{ minHeight: 48, marginLeft: 0 }}>Другие события под меня</button>
          </form>
          <p role="status" aria-live="polite" className="muted" style={{ fontSize: 13.5 }}>
            {wanted && !p.authed ? "Готовим приложение…" : pending ? "Записываю…" : ""}
          </p>
          {state.phase === "error" && state.error === "no-session" ? <p role="alert" className="field-error">Приложение ещё готовится. Нажми ещё раз через секунду.</p> : null}
          {state.phase === "error" && state.error === "gone" ? (
            <p role="alert" className="field-error">Это событие уже недоступно. Другие ждут в <a href="/digest">рекомендациях</a>.</p>
          ) : null}
          {state.phase === "error" && state.error === "down" ? <p role="alert" className="field-error">Не получилось записать. Попробуй ещё раз.</p> : null}
        </section>
        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}

function Done(p: InviteFlowProps & { state: Extract<AcceptState, { phase: "done" }> }) {
  const { state } = p;
  const going = state.status === "going";
  const [later, setLater] = useState(false);

  const day = p.dayText;
  return (
    <div className="wrap">
      <main id="main" className="public done reveal">
        <section className="stack" aria-labelledby="done-h">
          <h1 id="done-h">{going ? (p.gone ? "Ты идёшь" : "Вы идёте вместе") : "Записано в «может быть»"}</h1>
          <p>«{p.title}», {day}{going && p.timeText ? `, ${p.timeText}` : ""}.</p>
        </section>

        <div className="row">
          {going && state.links ? (
            <>
              {state.links.gcal ? <a className="btn cal" href={state.links.gcal} target="_blank" rel="noopener noreferrer">Google Календарь</a> : null}
              {state.links.outlook ? <a className="btn cal" href={state.links.outlook} target="_blank" rel="noopener noreferrer">Outlook</a> : null}
              <a className="btn cal" href={state.links.ics} download>.ics</a>
            </>
          ) : null}
          <a className="btn quiet" href="/plan">План</a>
        </div>

        {state.profileState === "new" ? (
          later ? (
            <p className="notice" role="status">Хорошо. Начать можно в любой момент в разделе «Профиль».</p>
          ) : (
            <section className="offer" aria-labelledby="offer-h">
              <h2 id="offer-h">Свои рекомендации?</h2>
              <div className="row">
                <a className="btn primary" href="/profile?onboarding=1">Давай</a>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setLater(true);
                    void postponeOfferAction();
                  }}
                >
                  Потом
                </button>
              </div>
            </section>
          )
        ) : null}
      </main>
    </div>
  );
}
