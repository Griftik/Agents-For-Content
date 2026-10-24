import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";
import { ApiDown } from "@/components/Gate";
import { InviteButton } from "@/components/InviteButton";
import { InviteFlow } from "@/components/InviteFlow";
import { InviteStatus } from "@/components/InviteStatus";
import { PublicEvent } from "@/components/PublicEvent";
import { ApiError, api } from "@/lib/api";
import type { Decision, InviteView, Profile } from "@/lib/api-types";
import { botLink, miniLink } from "@/lib/config";
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
    // Код неизвестен: показываем событие по слагу, если оно есть, иначе «Эта ссылка не работает».
    const { ev } = await getEvent(slug);
    if (!ev) return <InviteStatus kind="bad" hasProfile={!!view.profile} />;
  }
  if (invite) {
    if (invite.event && invite.event.slug !== slug) redirect(inviteHref(invite.event.slug, code!));
    if (invite.status === "past") return <InviteStatus kind="past" hasProfile={!!view.profile} title={invite.event?.title} />;
    if (invite.status === "unpublished") return <InviteStatus kind="unpublished" hasProfile={!!view.profile} title={invite.event?.title} />;
    if (!invite.event) return <InviteStatus kind="bad" hasProfile={!!view.profile} />;
    if (invite.inviter_is_me) {
      return (
        <div className="wrap">
          <main id="main" className="public">
            <p className="notice" role="status">Это твоё приглашение. Чтобы позвать друга, нажми «Позвать друга» на карточке события.</p>
            <PublicEvent ev={invite.event} />
          </main>
        </div>
      );
    }
    const ev = invite.event;
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
        hasProfile={!!view.profile}
        prior={prior && PRIOR[prior.status] ? `${PRIOR[prior.status]}${prior.day ? `, ${wdFull(prior.day).toLowerCase()}` : ""}` : null}
        openUrl={miniLink("inv", code!)}
        card={<PublicEvent ev={ev} heading="h2" />}
      />
    );
  }

  const { ev, error } = await getEvent(slug);
  if (error) return <ApiDown message={error} />;
  if (!ev) notFound();

  const dates = [...ev.dates].sort();
  const past = dates.length > 0 && dates[dates.length - 1] < moscowToday();
  const cta = botLink(`e_${slug}`);
  const going = view.decisions.find((d) => d.event_slug === slug && d.status === "иду");

  return (
    <div className="wrap">
      <main id="main" className="public">
        {past ? <p className="notice warn" role="status">Это событие уже прошло. Подборку на ближайшие выходные можно собрать ниже.</p> : null}
        <PublicEvent ev={ev} />
        {going ? <div className="row"><InviteButton slug={slug} day={going.day} small={false} /></div> : null}

        <section className="cta" aria-labelledby="cta">
          <h2 id="cta">Собери свою подборку на выходные</h2>
          <p>Ответь боту на пару вопросов о том, что для тебя важно, и каждый четверг получай события с пояснением, почему они подходят именно тебе.</p>
          {cta ? <a className="btn primary" href={cta} rel="noopener noreferrer">Собрать мне такую подборку</a> : <p>Бот пока не подключён к этой странице.</p>}
        </section>

        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}
