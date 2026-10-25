import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { decide } from "@/app/actions";
import { ApiDown } from "@/components/Gate";
import { InviteButton } from "@/components/InviteButton";
import { InviteFlow } from "@/components/InviteFlow";
import { InviteStatus } from "@/components/InviteStatus";
import { PublicEvent } from "@/components/PublicEvent";
import { ApiError, api } from "@/lib/api";
import type { Decision, InviteView, Profile } from "@/lib/api-types";
import { dateShort, first, moscowToday, timeRange, wdFull } from "@/lib/format";
import { getUserId } from "@/lib/session";
import { CODE_RE, inviteHref } from "@/lib/start-param";

export const dynamic = "force-dynamic";

const getEvent = cache(async (slug: string) => {
  try {
    return { ev: await api.event(slug), error: null as string | null };
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { ev: null, error: null };
    if (e instanceof ApiError) return { ev: null, error: e.status ? String(e.status) : "нет связи" };
    throw e;
  }
});

type Props = { params: Promise<{ slug: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const { ev } = await getEvent(slug);
  if (!ev) return { title: "Событие" };
  const desc = (ev.why_fit_hint || ev.description || "").slice(0, 200);
  return {
    title: ev.title,
    description: desc,
    robots: { index: true, follow: true },
    openGraph: { title: ev.title, description: desc, type: "article", locale: "ru_RU" },
  };
}

/** Профиль и решения зрителя; без сессии или профиля — пусто. Сбой API не ломает публичную страницу. */
async function viewer(uid: number | null): Promise<{ profile: Profile | null; decisions: Decision[]; down: boolean }> {
  if (!uid) return { profile: null, decisions: [], down: false };
  try {
    const profile = await api.profile(uid);
    return { profile, decisions: await api.decisions(uid), down: false };
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    return { profile: null, decisions: [], down: e.status !== 404 };
  }
}

const PRIOR: Record<string, string> = { иду: "иду", может: "может быть", интересно: "интересно", мимо: "мимо" };

export default async function EventPage({ params, searchParams }: Props) {
  const { slug } = await params;
  if (!/^[A-Za-z0-9_-]{1,120}$/.test(slug)) notFound();
  const sp = await searchParams;
  const inv = first(sp.inv);
  const code = inv && CODE_RE.test(inv) ? inv : null;
  const uid = await getUserId();

  // Приглашение: статус определяется по коду, а не по слагу (снятое с публикации событие по слагу вернуло бы 404).
  let invite: InviteView | null = null;
  if (code) {
    try {
      invite = await api.invite(code, uid ?? undefined);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.status !== 404) return <ApiDown message={e.status ? String(e.status) : "нет связи"} />;
    }
  }
  const view = await viewer(uid);

  if (code && !invite) {
    // Код неизвестен: явный экран «ссылка не работает»; если событие по слагу есть — с кнопкой «К событию»
    const { ev } = await getEvent(slug);
    return <InviteStatus kind="bad" hasProfile={!!view.profile?.has_consent} title={ev?.title} eventHref={ev ? `/e/${ev.slug}` : undefined} />;
  }
  if (invite) {
    const ev = invite.event?.event ?? null;
    const evSlug = invite.event_slug ?? ev?.slug ?? null;
    if (evSlug && evSlug !== slug) redirect(inviteHref(evSlug, code!));
    if (invite.status === "past") return <InviteStatus kind="past" hasProfile={!!view.profile?.has_consent} title={ev?.title} />;
    if (invite.status === "unpublished") return <InviteStatus kind="unpublished" hasProfile={!!view.profile?.has_consent} title={ev?.title} />;
    if (!ev) return <InviteStatus kind="bad" hasProfile={!!view.profile?.has_consent} />;
    if (invite.is_own) {
      return (
        <div className="wrap">
          <main id="main" className="public">
            <p className="notice" role="status">Это твоё приглашение. Чтобы позвать друга, нажми «Позвать друга» на карточке события.</p>
            <PublicEvent ev={ev} />
          </main>
        </div>
      );
    }
    const day = invite.day ?? ev.dates[0] ?? "";
    const prior = view.decisions.find((d) => d.event_slug === ev.slug);
    return (
      <InviteFlow
        code={code!}
        slug={ev.slug}
        day={day}
        title={ev.title}
        dayText={day ? `${wdFull(day).toLowerCase()}, ${dateShort(day)}` : ""}
        timeText={timeRange(ev)}
        inviterName={invite.inviter_name}
        gone={invite.status === "gone"}
        authed={uid != null}
        hasConsent={!!view.profile?.has_consent}
        prior={prior && PRIOR[prior.status] ? `${PRIOR[prior.status]}${prior.day ? `, ${wdFull(prior.day).toLowerCase()}` : ""}` : null}
        card={<PublicEvent ev={ev} day={day} heading="h2" />}
      />
    );
  }

  const { ev, error } = await getEvent(slug);
  if (error) return <ApiDown message={error} />;
  if (!ev) notFound();

  const dates = [...ev.dates].sort();
  const past = dates.length > 0 && dates[dates.length - 1] < moscowToday();
  const mine = view.decisions.find((d) => d.event_slug === slug);
  const going = mine && (mine.status === "иду" || mine.status === "сходил") ? mine : null;
  const nextDay = dates.find((d) => d >= moscowToday()) ?? dates[0] ?? "";
  const sourceOk = /^https?:\/\//.test(ev.url);
  return (
    <div className="wrap">
      <main id="main" className="public reveal" style={{ gap: 12, paddingTop: 8 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <a className="back" href={uid ? "/digest" : "/"} aria-label="Назад">←</a>
          {uid && going ? <InviteButton slug={slug} day={going.day ?? nextDay} small={false} /> : null}
        </div>
        <PublicEvent ev={ev} day={going?.day ?? nextDay} />
        {uid && !past ? (
          <form action={decide} className="stickybar">
            <input type="hidden" name="slug" value={slug} />
            <input type="hidden" name="current" value={mine?.status ?? ""} />
            <input type="hidden" name="op" value="toggle" />
            {nextDay && !going ? <input type="hidden" name="day" value={nextDay} /> : null}
            {sourceOk ? <a className="btn" href={ev.url} target="_blank" rel="noopener noreferrer">К билетам</a> : null}
            <button type="submit" name="status" value="иду" className="btn primary" aria-pressed={!!going}>{going ? "В плане" : "Иду"}</button>
          </form>
        ) : null}
        {!uid ? (
          <div className="stickybar">
            {sourceOk ? <a className="btn" href={ev.url} target="_blank" rel="noopener noreferrer">К билетам</a> : null}
            <a className="btn primary" href="/profile?onboarding=welcome">Начать</a>
          </div>
        ) : null}
        {uid && past && sourceOk ? <div className="row"><a className="btn" href={ev.url} target="_blank" rel="noopener noreferrer">К билетам</a></div> : null}
        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}
