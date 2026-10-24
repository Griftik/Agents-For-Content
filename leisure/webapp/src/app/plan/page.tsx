import type { Metadata } from "next";
import { removeFromPlan, decide } from "@/app/actions";
import { api } from "@/lib/api";
import type { PlanItem } from "@/lib/api-types";
import { dateShort, first, parseToday, timeRange, wdFull } from "@/lib/format";
import { load } from "@/lib/load";
import { getUserId, isDev } from "@/lib/session";
import { ApiDown, AuthGate, NoProfile } from "@/components/Gate";
import { CopyButton } from "@/components/CopyButton";
import { Masthead } from "@/components/Masthead";

export const metadata: Metadata = { title: "План" };
export const dynamic = "force-dynamic";

function Item({ it, conflictWith }: { it: PlanItem; conflictWith?: string }) {
  const ev = it.event;
  const maybe = it.status === "может";
  const where = [ev.venue, ev.address, ev.metro ? `м. ${ev.metro}` : ""].filter(Boolean).join(", ");
  const time = timeRange(ev) || "время уточняется";
  return (
    <div className={`pi${maybe ? " maybe" : ""}`}>
      <div className="t">{time}{maybe ? " · может быть" : ""}</div>
      <div className="n"><a href={`/e/${ev.slug}`}>{ev.title}</a></div>
      <div className="v">{where}</div>
      {it.conflict ? <div className="warn">Пересекается по времени{conflictWith ? ` с ${conflictWith}` : ""}</div> : null}
      <div className="row">
        {maybe ? (
          <form action={decide} style={{ display: "contents" }}>
            <input type="hidden" name="slug" value={ev.slug} />
            <input type="hidden" name="day" value={it.day} />
            <button type="submit" name="status" value="иду" className="btn small go">Точно иду</button>
          </form>
        ) : null}
        <a className="btn small" href={`/e/${ev.slug}`}>Подробнее</a>
        {!maybe ? (
          <>
            <a className="btn small cal" href={it.links.gcal} target="_blank" rel="noopener noreferrer">Google Календарь</a>
            <a className="btn small cal" href={it.links.outlook} target="_blank" rel="noopener noreferrer">Outlook</a>
            <a className="btn small cal" href={`/api/events/${ev.slug}/ics?day=${it.day}`} download>.ics</a>
            <a className="btn small" href={it.links.tg} target="_blank" rel="noopener noreferrer">Отправить</a>
          </>
        ) : null}
        <form action={removeFromPlan} style={{ display: "contents" }}>
          <input type="hidden" name="slug" value={ev.slug} />
          <button type="submit" className="btn small quiet">Убрать</button>
        </form>
      </div>
    </div>
  );
}

const mins = (t: string | null) => (t && /^\d{1,2}:\d{2}$/.test(t) ? Number(t.split(":")[0]) * 60 + Number(t.split(":")[1]) : null);
const clip = (t: string, n = 60) => (t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t);

/** С чем пересекается событие: другое «иду» дня с пересекающимся временем (если время не разобрать, берём любое другое с конфликтом). */
function conflictName(items: PlanItem[], it: PlanItem): string | undefined {
  if (!it.conflict) return undefined;
  const others = items.filter((o) => o !== it && o.status === "иду");
  const s1 = mins(it.event.start_time);
  const e1 = mins(it.event.end_time) ?? (s1 != null ? s1 + 60 : null);
  const hit = others.find((o) => {
    const s2 = mins(o.event.start_time);
    const e2 = mins(o.event.end_time) ?? (s2 != null ? s2 + 60 : null);
    return s1 == null || e1 == null || s2 == null || e2 == null ? o.conflict : s1 < e2 && s2 < e1;
  });
  return hit ? clip(hit.event.title) : undefined;
}

export default async function PlanPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const uid = await getUserId();
  if (!uid) return <AuthGate />;
  const today = isDev ? parseToday(first(sp.today)) : undefined;
  const loaded = await load(() => Promise.all([api.plan(uid, today), api.profile(uid), api.digestAll(uid, today).then((a) => a.length)]));
  if (loaded.kind === "no-profile") return <NoProfile />;
  if (loaded.kind === "down") return <ApiDown message={loaded.message} />;
  const [plan, profile, total] = loaded.data;
  const going = Object.values(plan.days).flat().length + plan.horizon.length;

  return (
    <div className="wrap wide">
      <Masthead eyebrow="План" title="Выходные" accent={plan.title} tab="plan" digestCount={total} name={profile.name || undefined} />
      <main id="main" className="page" style={{ paddingTop: 18 }}>
        {going === 0 ? (
          <p className="empty">В плане пока пусто. Отметь «Иду» или «Может быть» в <a href="/digest">дайджесте</a>, и событие появится здесь.</p>
        ) : null}
        <div className="cols">
          {plan.weekend.map((d) => {
            const items = plan.days[d] ?? [];
            return (
              <section key={d} className="col" aria-labelledby={`d-${d}`}>
                <h2 id={`d-${d}`}>{wdFull(d)}<span>{dateShort(d)}</span></h2>
                {items.length ? items.map((it) => <Item key={it.event.slug} it={it} conflictWith={conflictName(items, it)} />) : <p className="none">Пока ничего.</p>}
              </section>
            );
          })}
        </div>

        {plan.horizon.length ? (
          <section className="col horizon" aria-labelledby="hor">
            <h2 id="hor">На горизонте</h2>
            {plan.horizon.map((it) => (
              <div key={it.event.slug}>
                <p className="eyebrow" style={{ marginTop: 10 }}>{wdFull(it.day)}, {dateShort(it.day)}</p>
                <Item it={it} />
              </div>
            ))}
          </section>
        ) : null}

        <section className="stack" aria-labelledby="share">
          <h2 id="share" className="sr">Скопировать план</h2>
          <div className="copy-row"><CopyButton text={plan.text} /></div>
          <details className="plan-text">
            <summary>Текст плана</summary>
            <pre>{plan.text}</pre>
          </details>
        </section>
      </main>
    </div>
  );
}
