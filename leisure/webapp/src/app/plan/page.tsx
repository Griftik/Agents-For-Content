import type { Metadata } from "next";
import { decide, removeFromPlan } from "@/app/actions";
import { ApiDown, AuthGate, NoProfile } from "@/components/Gate";
import { InviteButton } from "@/components/InviteButton";
import { Masthead } from "@/components/Masthead";
import { PastMark } from "@/components/PastMark";
import { api } from "@/lib/api";
import type { AccountProfiles, PlanItem } from "@/lib/api-types";
import { dayLabel, timeLine } from "@/lib/feed";
import { moscowToday, placeLine, timeRange } from "@/lib/format";
import { load } from "@/lib/load";
import { hasUnmarkedPast, pastItems } from "@/lib/plan";
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
  const loaded = await load(() => Promise.all([api.plan(pid), api.profile(pid), api.profiles(uid).catch((): AccountProfiles | null => null)]));
  if (loaded.kind === "no-profile") return <NoProfile />;
  if (loaded.kind === "down") return <ApiDown message={loaded.message} />;
  const [plan, profile, acc] = loaded.data;
  if (!profile.has_consent) return <NoProfile />;
  const list = acc?.profiles?.length ? acc.profiles : [{ user_id: uid, name: profile.name || "я", kind: "self", onboarded: profile.onboarded, is_main: true }];
  const past = pastItems(plan.past);
  const days = plan.weekend.filter((d) => (plan.days[d] ?? []).length);
  const empty = days.length === 0 && plan.horizon.length === 0;

  return (
    <div className="wrap">
      <Masthead title="План" tab="plan" profiles={list} activeId={pid} planDot={hasUnmarkedPast(plan.past)} />
      <main id="main" className="page reveal" style={{ paddingTop: 4, gap: 24 }}>
        {past.length ? (
          <section className="pday" aria-labelledby="past-h">
            <h2 id="past-h">Прошли <span className="svc">{past.length}</span></h2>
            <div className="items">
              {past.map((it) => (
                <div key={`${it.event.slug}-${it.day}`} className="pitem">
                  <span className="svc">{dayLabel(it.day as `${number}-${number}-${number}`)}{timeRange(it.event) ? ` · ${timeRange(it.event)}` : ""}</span>
                  <div className="n"><a href={`/e/${it.event.slug}`}>{it.event.title}</a></div>
                  <div className="v">{it.event.venue}</div>
                  <PastMark slug={it.event.slug} initialStatus={it.status} initialRating={it.rating ?? null} />
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
