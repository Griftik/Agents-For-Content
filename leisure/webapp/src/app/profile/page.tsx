import type { Metadata } from "next";
import { saveProfile } from "@/app/actions";
import { redirect } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Profile } from "@/lib/api-types";
import { first } from "@/lib/format";
import { parseStep } from "@/lib/onboarding";
import { load } from "@/lib/load";
import { getUserId } from "@/lib/session";
import { ApiDown, AuthGate, NoProfile } from "@/components/Gate";
import { Masthead } from "@/components/Masthead";
import { Onboarding } from "@/components/Onboarding";
import { ShowNameSwitch } from "@/components/ShowNameSwitch";
import { Slider } from "@/components/Slider";

export const metadata: Metadata = { title: "Профиль" };
export const dynamic = "force-dynamic";

const LEVELS: [number, string, string][] = [
  [0, "—", "не показывать"],
  [1, "иногда", "иногда"],
  [2, "да", "интересно"],
  [3, "главное", "в первую очередь"],
];

export default async function ProfilePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const uid = await getUserId();
  if (!uid) return <AuthGate />;

  // Онбординг в Mini App: /profile?onboarding=welcome|1|2. Профиль здесь может ещё не существовать.
  const step = parseStep(first(sp.onboarding));
  if (step) {
    let prof: Profile | null = null;
    try {
      prof = await api.profile(uid);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.status !== 404) return <ApiDown message={e.status ? String(e.status) : "нет связи"} />;
    }
    if (prof?.onboarded) redirect("/digest");
    // согласие есть — приветствие пропускаем; нет (профиля нет или заготовка без согласия) — начинаем с него
    const eff = prof?.has_consent ? (step === "welcome" ? "1" : step) : "welcome";
    const cat = await load(() => api.catalog());
    if (cat.kind !== "ok") return <ApiDown message={cat.kind === "down" ? cat.message : undefined} />;
    return <Onboarding step={eff} profile={prof} catalog={cat.data} error={first(sp.error)} needConsent={first(sp.need) === "consent"} />;
  }

  const loaded = await load(() => Promise.all([api.profile(uid), api.catalog(), api.digestAll(uid).then((a) => a.length)]));
  if (loaded.kind === "no-profile") return <NoProfile />;
  if (loaded.kind === "down") return <ApiDown message={loaded.message} />;
  const [p, catalog, total] = loaded.data;

  const saved = first(sp.saved) === "1";
  const error = first(sp.error);
  const values = catalog.values.map((v) => ({ name: v, w: p.values[v] ?? 0 })).sort((a, b) => b.w - a.w);
  const topFive = new Set(values.slice(0, 5).map((v) => v.name));
  const cats = [...new Set([...catalog.categories, ...Object.keys(p.interests)])];
  const prm = p.params;
  const times = prm.times ?? [];
  const areas = prm.areas ?? [];
  const extraAreas = areas.filter((a) => !catalog.areas.includes(a));
  const learned = p.learned;
  const likes = (learned.likes ?? []) as string[];
  const dislikes = (learned.dislikes ?? []) as string[];
  const reasons = Object.entries(learned.reasons ?? {});

  return (
    <div className="wrap">
      <Masthead eyebrow="Профиль" title="Что для тебя" accent="главное" tab="profile" digestCount={total} name={p.name || undefined} />
      <main id="main" className="page" style={{ paddingTop: 18 }}>
        {saved ? <p className="notice ok" role="status">Сохранил. Подборка пересчитается с новыми настройками.</p> : null}
        {error ? <p className="notice warn" role="alert">{error}</p> : null}

        <section className="card learn" aria-labelledby="learned">
          <h2 id="learned" style={{ fontSize: 24 }}>Что я узнал о тебе</h2>
          {learned.n ? (
            <dl>
              {likes.length ? <><dt>чаще выбираешь</dt><dd>{likes.join(", ").toLowerCase()}</dd></> : null}
              {dislikes.length ? <><dt>чаще отклоняешь</dt><dd>{dislikes.join(", ").toLowerCase()}</dd></> : null}
              {reasons.length ? <><dt>причины «мимо»</dt><dd>{reasons.map(([k, v]) => `${k} (${v})`).join(", ")}</dd></> : null}
            </dl>
          ) : (
            <p className="muted">Пока мало ответов. Отметь несколько событий в подборке, и здесь появится, что тебе нравится.</p>
          )}
        </section>

        <form action={saveProfile} className="profile">
          <section className="card" aria-labelledby="vals">
            <h2 id="vals" style={{ fontSize: 24 }}>Ценности</h2>
            <p className="muted" style={{ fontSize: 13.5, margin: "4px 0 8px" }}>От 0 до 5. Пять самых важных выделены.</p>
            {values.map((v) => <Slider key={v.name} name={`v:${v.name}`} label={v.name} value={v.w} top={topFive.has(v.name)} />)}
          </section>

          <section className="card" aria-labelledby="ints">
            <h2 id="ints" style={{ fontSize: 24 }}>Направления</h2>
            <p className="muted" style={{ fontSize: 13.5, margin: "4px 0 8px" }}>«—» — не показывать, «главное» — в первую очередь.</p>
            {cats.map((c) => {
              const cur = p.interests[c] ?? 2;
              return (
                <fieldset key={c} className="irow" style={{ border: 0, borderTop: "1px solid var(--line)", margin: 0, padding: "9px 0" }}>
                  <legend className="sr">{c}</legend>
                  <span className="nm" aria-hidden="true">{c}</span>
                  <span className="seg">
                    {LEVELS.map(([n, label, title]) => (
                      <label key={n} title={title}>
                        <input type="radio" name={`i:${c}`} value={n} defaultChecked={cur === n} aria-label={`${c}: ${title}`} />
                        <span>{label}</span>
                      </label>
                    ))}
                  </span>
                </fieldset>
              );
            })}
          </section>

          <section className="card" aria-labelledby="prm">
            <h2 id="prm" style={{ fontSize: 24 }}>Параметры</h2>
            <ShowNameSwitch initial={p.show_name !== false} />
            <div className="prow">
              <label className="nm" htmlFor="aesthetics">Красота места и формата обязательна</label>
              <span className="sw"><input id="aesthetics" type="checkbox" name="aesthetics" defaultChecked={!!prm.aesthetics} /><i /></span>
            </div>
            <div className="prow">
              <label className="nm" htmlFor="adults30">Подбирать для взрослых 30+</label>
              <span className="sw"><input id="adults30" type="checkbox" name="adults30" defaultChecked={!!prm.adults30} /><i /></span>
            </div>
            <div className="prow">
              <label className="nm" htmlFor="kids">Идёшь с детьми</label>
              <span className="sw"><input id="kids" type="checkbox" name="kids" defaultChecked={!!prm.kids} /><i /></span>
            </div>
            <div className="prow">
              <label className="nm" htmlFor="budget">Бюджет на событие, ₽ <span className="muted">(0 — без ограничения)</span></label>
              <input id="budget" type="number" name="budget" min={0} max={1000000} step={100} inputMode="numeric" defaultValue={prm.budget ?? 0} />
            </div>
            <fieldset className="prow" style={{ border: 0, borderTop: "1px solid var(--line)", margin: 0, flexWrap: "wrap" }}>
              <legend className="sr">С кем</legend>
              <span className="nm">С кем</span>
              <span className="seg wrapseg">
                {catalog.company.map((c) => (
                  <label key={c}><input type="radio" name="company" value={c} defaultChecked={prm.company === c} /><span>{c}</span></label>
                ))}
              </span>
            </fieldset>
            <fieldset className="prow" style={{ border: 0, borderTop: "1px solid var(--line)", margin: 0, flexWrap: "wrap" }}>
              <legend className="sr">Когда удобно</legend>
              <span className="nm">Когда удобно</span>
              <span className="seg wrapseg">
                {catalog.times.map((t) => (
                  <label key={t}><input type="checkbox" name="times" value={t} defaultChecked={times.includes(t)} /><span>{t}</span></label>
                ))}
              </span>
            </fieldset>
            <fieldset className="prow" style={{ border: 0, borderTop: "1px solid var(--line)", margin: 0, flexWrap: "wrap" }}>
              <legend className="sr">Район</legend>
              <span className="nm">Район</span>
              <span className="seg wrapseg">
                {catalog.areas.map((a) => (
                  <label key={a}><input type="checkbox" name="areas" value={a} defaultChecked={areas.includes(a)} /><span>{a}</span></label>
                ))}
              </span>
              {extraAreas.map((a) => <input key={a} type="hidden" name="areas" value={a} />)}
            </fieldset>
          </section>

          <section className="card" aria-labelledby="note">
            <h2 id="note" style={{ fontSize: 24 }}>Заметка о себе</h2>
            <p className="muted" style={{ fontSize: 13.5, margin: "4px 0 8px" }}>Свободный текст: что любишь, чего избегаешь. До 2000 символов.</p>
            <label className="sr" htmlFor="notes">Заметка</label>
            <textarea id="notes" name="notes" maxLength={2000} defaultValue={p.notes} />
          </section>

          <div className="savebar">
            <button type="submit" className="btn primary">Сохранить</button>
            <a href="/policy">Политика обработки данных</a>
          </div>
        </form>
      </main>
    </div>
  );
}
