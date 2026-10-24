"use client";

import { startTransition, useActionState, useEffect, useRef, useState, type ReactNode } from "react";
import { acceptInviteAction, postponeOfferAction, type AcceptState } from "@/app/actions";
import type { InviteAcceptStatus } from "@/lib/api-types";
import { inTelegram, requestWriteAccess } from "@/lib/tg-client";

export type InviteFlowProps = {
  code: string;
  slug: string;
  day: string;
  title: string;
  /** «суббота, 24 окт» и «13:00–15:00» — уже отформатированы на сервере. */
  dayText: string;
  timeText: string;
  inviterName: string | null;
  /** Пригласивший удалил профиль (gone): шапка «Тебя зовут на событие», кнопки без слова «вместе». */
  gone: boolean;
  authed: boolean;
  hasProfile: boolean;
  /** Прежний ответ друга: «иду, суббота». */
  prior: string | null;
  /** t.me/<бот>/<app>?startapp=inv_<код> для браузера без Telegram. */
  openUrl: string | null;
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
  const [mode, setMode] = useState<"unknown" | "telegram" | "browser">(p.authed ? "telegram" : "unknown");
  const [consent, setConsent] = useState(false);
  const [wanted, setWanted] = useState<InviteAcceptStatus | null>(null);
  const [forceConsent, setForceConsent] = useState(false);
  const last = useRef<InviteAcceptStatus | null>(null);
  const box = useRef<HTMLInputElement>(null);

  const consentNeeded = forceConsent || !p.hasProfile;
  const ready = p.authed && (!consentNeeded || consent);

  useEffect(() => {
    if (!p.authed) setMode(inTelegram() ? "telegram" : "browser");
  }, [p.authed]);

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
    last.current = wanted;
    setWanted(null);
    startTransition(() => formAction(fd));
  }, [wanted, ready, pending, consent, consentNeeded, p.code, p.slug, p.day, formAction]);

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

  const choose = (s: InviteAcceptStatus) => setWanted(s);
  const names = p.gone ? { going: "Иду", title: "Тебя зовут на событие" } : { going: "Иду вместе", title: `${p.inviterName ?? "Друг"} зовёт тебя` };
  const authFail = state.phase === "error" && state.error === "no-session" && !p.authed;

  return (
    <div className="wrap">
      <main id="main" className="public">
        <header className="invite-head">
          <span className="eyebrow">Приглашение</span>
          <h1>{names.title}</h1>
          <p className="when">{[p.dayText.charAt(0).toUpperCase() + p.dayText.slice(1), p.timeText].filter(Boolean).join(" · ")}</p>
        </header>
        {p.prior ? <p className="prior">Прежний ответ: {p.prior}</p> : null}
        {p.card}

        {mode === "browser" ? (
          <section className="invite-actions" aria-labelledby="browser-h">
            <h2 id="browser-h" className="sr">Открыть в Telegram</h2>
            <p>Чтобы записаться, открой приглашение в Telegram. Логинов и паролей нет: тебя узнаём по Telegram.</p>
            {p.openUrl ? <a className="btn primary" href={p.openUrl} rel="noopener noreferrer">Открыть в Telegram</a> : null}
          </section>
        ) : mode === "telegram" ? (
          <section className="invite-actions" aria-labelledby="act-h">
            <h2 id="act-h" className="sr">Ответить на приглашение</h2>
            {consentNeeded ? (
              <div>
                <label className="consent">
                  <input ref={box} type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} aria-describedby={needMsg ? "consent-need" : undefined} />
                  <span>
                    Даю согласие на обработку моего Telegram id, имени и ответов, чтобы записать меня в план и подбирать события. Данные хранятся в России. Подробнее
                    в <a href="/policy" target="_blank" rel="noopener noreferrer">политике обработки данных</a>.
                  </span>
                  <small>Согласие можно отозвать в любой момент: /delete в боте.</small>
                </label>
                {needMsg ? <p id="consent-need" role="alert" className="field-error" style={{ marginTop: 8 }}>Отметь согласие, и я запишу твой выбор.</p> : null}
              </div>
            ) : null}
            <div className="row actions">
              <button type="button" className="btn primary" onClick={() => choose("going")} aria-busy={pending || undefined}>{names.going}</button>
              <button type="button" className="btn" style={{ minHeight: 48 }} onClick={() => choose("maybe")}>Может быть</button>
              <a className="btn link" style={{ minHeight: 48 }} href={p.hasProfile ? "/digest" : "/profile?onboarding=welcome"}>Другие выходные под меня</a>
            </div>
            <p role="status" aria-live="polite" className="muted" style={{ fontSize: 13.5 }}>
              {wanted && !p.authed ? "Входим через Telegram…" : pending ? "Записываю…" : ""}
            </p>
            {authFail ? <p role="alert" className="field-error">Не получилось войти. Закрой приглашение и открой его из Telegram ещё раз.</p> : null}
            {state.phase === "error" && state.error === "gone" ? (
              <p role="alert" className="field-error">Это событие уже недоступно. Другие выходные ждут в <a href="/digest">«Дайджесте»</a>.</p>
            ) : null}
            {state.phase === "error" && state.error === "down" ? <p role="alert" className="field-error">Не получилось записать. Попробуй ещё раз.</p> : null}
          </section>
        ) : (
          <noscript>
            <p>Чтобы записаться, открой приглашение в Telegram.</p>
            {p.openUrl ? <a className="btn primary" href={p.openUrl}>Открыть в Telegram</a> : null}
          </noscript>
        )}
        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}

function Done(p: InviteFlowProps & { state: Extract<AcceptState, { phase: "done" }> }) {
  const { state } = p;
  const going = state.status === "going";
  const who = state.togetherWith ?? p.inviterName;
  const [write, setWrite] = useState<"idle" | "granted" | "refused">("idle");
  const [later, setLater] = useState(false);
  const [tg, setTg] = useState(false);
  useEffect(() => setTg(inTelegram()), []);

  const day = p.dayText;
  const lead = going
    ? p.gone || !who ? (p.gone ? "План на этот день придёт в Telegram." : "Друг увидит, что ты идёшь. План на этот день придёт в Telegram.") : `${who} увидит, что ты идёшь. План на этот день придёт в Telegram.`
    : p.gone || !who ? "Передумать можно в плане." : `${who} об этом не узнает. Передумать можно в плане.`;

  async function ask() {
    setWrite((await requestWriteAccess()) ? "granted" : "refused");
  }

  return (
    <div className="wrap">
      <main id="main" className="public done">
        <section className="stack" aria-labelledby="done-h">
          <h1 id="done-h">{going ? (p.gone ? "Ты идёшь" : "Вы идёте вместе") : "Записано в «может быть»"}</h1>
          <p>«{p.title}», {day}{going && p.timeText ? `, ${p.timeText}` : ""}.</p>
          <p className="muted">{lead}</p>
        </section>

        <div className="row">
          {going && state.links ? (
            <>
              {state.links.gcal ? <a className="btn cal" href={state.links.gcal} target="_blank" rel="noopener noreferrer">Google Календарь</a> : null}
              {state.links.outlook ? <a className="btn cal" href={state.links.outlook} target="_blank" rel="noopener noreferrer">Outlook</a> : null}
              <a className="btn cal" href={state.links.ics} download>.ics</a>
            </>
          ) : null}
          {tg && write === "idle" ? <button type="button" className="btn" onClick={ask}>Получать план в Telegram</button> : null}
          <a className="btn quiet" href="/plan">Мой план</a>
        </div>
        <p role="status" aria-live="polite" className="muted" style={{ fontSize: 13.5 }}>
          {write === "granted" ? "Готово: план будет приходить в Telegram." : write === "refused" ? "Хорошо. План смотри здесь, в приложении." : ""}
        </p>

        {state.profileState === "new" ? (
          later ? (
            <p className="notice" role="status">Хорошо. Начать можно в любой момент в разделе «Профиль».</p>
          ) : (
            <section className="offer" aria-labelledby="offer-h">
              <h2 id="offer-h">Хочешь свою подборку на выходные?</h2>
              <p>Два шага: пять главных ценностей и интересы, около минуты. Дальше подборка будет приходить по четвергам.</p>
              <div className="row">
                <a className="btn primary" href="/profile?onboarding=1">Давай</a>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setLater(true);
                    void postponeOfferAction(p.day);
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
