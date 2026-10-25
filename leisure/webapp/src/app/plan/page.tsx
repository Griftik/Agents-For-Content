import type { Metadata } from "next";
import { decide, removeFromPlan } from "@/app/actions";
import { ApiDown, AuthGate, NoProfile } from "@/components/Gate";
import { InviteButton } from "@/components/InviteButton";
import { Masthead } from "@/components/Masthead";
import { PastMark } from "@/components/PastMark";
import { ApiError, api } from "@/lib/api";
import type { AccountProfile, EventT, PlanItem } from "@/lib/api-types";
import { dayLabel, timeLine } from "@/lib/feed";
import { moscowToday, placeLine, timeRange } from "@/lib/format";
import { load } from "@/lib/load";
import { hasUnmarkedPast, pastDecisions } from "@/lib/plan";
import { getProfileId, getUserId } from "@/lib/session";

export const metadata: Metadata = { title: "План" };
export const dynamic = "force-dynamic";

function Item({ it }: { it: PlanItem }) {
  const ev = it.event;
  const maybe = it.status === "может";
  const { venue, rest } = placeLine(ev);
  return (
    <div className="pitem">
      <span className="svc fg">{timeRange(ev) || "время уточняется"}{maybe ? " · может быть" : ""}</span>
      <div className="n"><a href={`/e/${ev.slug}`}>{ev.title}</a></div>
      <div className="v">{venue}{rest ? ` · ${rest}` : ""}</div>
      {it.companions?.length ? <span className="svc">{it.companions.length > 1 ? `С друзьями (${it.companions.length})` : `Вдвоём с ${it.companions[0]}`}</span> : null}
      {it.conflict ? <div className="warn">Пересекается по времени</div> : null}
      <div className="row">
        {maybe ? (
          <form action={decide} style={{ display: "contents" }}>
            <input type="hidden" name="slug" value={ev.slug} />
            <input type="hidden" name="day" value={it.day} />
            <button type="submit" name="status" value="иду" className="btn small go">Иду</button>
          </form>
        ) : (
          <a className="btn small cal" href={`/api/events/${ev.slug}/ics?day=${it.day}`} download>Календарь</a>
        )}
        {/^https?:\/\//.test(ev.url) ? <a className="btn small" href={ev.url} target="_blank" rel="noopener noreferrer">К билетам</a> : null}
        <InviteButton slug={ev.slug} day={it.day} />
        <form action={removeFromPlan} style={{ display: "contents" }}>
          <input type="hidden" name="slug" value={ev.slug} />
          <button type="submit" className="btn small quiet">Убрать</button>
        </form>
      </div>
    </div>
  );
}

export default async function PlanPage() {
  const uid = await getUserId();
  const pid = await getProfileId();
  if (!uid || !pid) return <AuthGate />;
  const today = moscowToday();
  const loaded = await load(() => Promise.all([api.plan(pid), api.profile(pid), api.decisions(pid), api.profiles(uid).catch((): AccountProfile[] => [])]));
  if (loaded.kind === "no-profile") return <NoProfile />;
  if (loaded.kind === "down") return <ApiDown message={loaded.message} />;
  const [plan, profile, decisions, profiles] = loaded.data;
  if (!profile.has_consent) return <NoProfile />;
  const list = profiles.length ? profiles : [{ id: uid, name: profile.name || "я", kind: "self", onboarded: profile.onboarded }];

  // Прошедшие: решения с датой до сегодня; карточки событий подгружаем по слагу (API плана отдаёт только будущее)
  const past = pastDecisions(decisions, today);
  const pastEvents = await Promise.all(
    past.map(async (d) => {
      try {
        return { d, ev: await api.event(d.event_slug) };
      } catch (e) {
        if (e instanceof ApiError) return { d, ev: null as EventT | null };
        throw e;
      }
    }),
  );
  const days = plan.weekend.filter((d) => (plan.days[d] ?? []).length);
  const empty = days.length === 0 && plan.horizon.length === 0;

  return (
    <div className="wrap">
      <Masthead title="План" tab="plan" profiles={list} activeId={pid} planDot={hasUnmarkedPast(decisions, today)} />
      <main id="main" className="page reveal" style={{ paddingTop: 4, gap: 24 }}>
        {pastEvents.length ? (
          <section className="pday" aria-labelledby="past-h">
            <h2 id="past-h">Прошли <span className="svc">{pastEvents.length}</span></h2>
            <div className="items">
              {pastEvents.map(({ d, ev }) => (
                <div key={d.event_slug} className="pitem">
                  <span className="svc">{d.day ? dayLabel(d.day as `${number}-${number}-${number}`) : ""}{ev && timeRange(ev) ? ` · ${timeRange(ev)}` : ""}</span>
                  <div className="n"><a href={`/e/${d.event_slug}`}>{ev?.title ?? d.event_slug}</a></div>
                  {ev ? <div className="v">{ev.venue}</div> : null}
                  <PastMark slug={d.event_slug} initialStatus={d.status} initialRating={d.rating} />
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {empty ? (
          <div className="fempty" role="status">
            <h2>Пока пусто</h2>
            <a className="btn primary" href="/digest?day=today">Рекомендации</a>
          </div>
        ) : null}

        {days.map((d) => (
          <section key={d} className="pday" aria-labelledby={`d-${d}`}>
            <h2 id={`d-${d}`}>{dayLabel(d as `${number}-${number}-${number}`)}</h2>
            <div className="items">{(plan.days[d] ?? []).map((it) => <Item key={it.event.slug} it={it} />)}</div>
          </section>
        ))}

        {plan.horizon.length ? (
          <section className="pday" aria-labelledby="hor">
            <h2 id="hor">Дальше</h2>
            <div className="items">
              {plan.horizon.map((it) => (
                <div key={it.event.slug}>
                  <span className="svc" style={{ display: "block", paddingTop: 10 }}>{timeLine(it.day, today, null, null)}</span>
                  <Item it={it} />
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}
