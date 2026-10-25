import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { saveProfile } from "@/app/actions";
import { DeleteData } from "@/components/DeleteData";
import { EmailForm } from "@/components/EmailForm";
import { ApiDown, AuthGate, NoProfile } from "@/components/Gate";
import { Learned } from "@/components/Learned";
import { Masthead } from "@/components/Masthead";
import { Onboarding } from "@/components/Onboarding";
import { ProfileChips } from "@/components/ProfileSwitcher";
import { ShowNameSwitch } from "@/components/ShowNameSwitch";
import { ValuePicker } from "@/components/ValuePicker";
import { ApiError, api } from "@/lib/api";
import type { AccountProfiles, Profile } from "@/lib/api-types";
import { first, moscowToday } from "@/lib/format";
import { load } from "@/lib/load";
import { TOP_VALUES, clusters, parseStep } from "@/lib/onboarding";
import { hasUnmarkedDecisions } from "@/lib/plan";
import { getProfileId, getUserId } from "@/lib/session";

export const metadata: Metadata = { title: "Профиль" };
export const dynamic = "force-dynamic";

const LEVELS = ["Не показывать", "Иногда", "Интересно", "Главное"];
const BUDGET_CHIPS = [
  { v: 0, l: "Не важно" },
  { v: 1000, l: "до 1 000 ₽" },
  { v: 2500, l: "до 2 500 ₽" },
  { v: 5000, l: "до 5 000 ₽" },
];
const TIMES = ["утро", "день", "вечер", "ночь"];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export default async function ProfilePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const uid = await getUserId();
  const pid = await getProfileId();
  if (!uid || !pid) return <AuthGate />;

  // Онбординг: /profile?onboarding=welcome|1|2. Профиль может ещё не существовать.
  const step = parseStep(first(sp.onboarding));
  let prof: Profile | null = null;
  try {
    prof = await api.profile(pid);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status !== 404) return <ApiDown message={e.status ? String(e.status) : "нет связи"} />;
  }
  if (step || !prof?.has_consent || !prof.onboarded) {
    if (prof?.onboarded && prof.has_consent) redirect("/profile");
    const eff = prof?.has_consent ? (step === "welcome" || !step ? "1" : step) : "welcome";
    const cat = await load(() => api.catalog());
    if (cat.kind !== "ok") return <ApiDown message={cat.kind === "down" ? cat.message : undefined} />;
    return <Onboarding step={eff} profile={prof} catalog={cat.data} error={first(sp.error)} needConsent={first(sp.need) === "consent"} />;
  }

  const loaded = await load(() => Promise.all([api.catalog(), api.decisions(pid), api.profiles(uid).catch((): AccountProfiles | null => null)]));
  if (loaded.kind === "no-profile") return <NoProfile />;
  if (loaded.kind === "down") return <ApiDown message={loaded.message} />;
  const [catalog, decisions, acc] = loaded.data;
  const p = prof;
  const list = acc?.profiles?.length ? acc.profiles : [{ user_id: uid, name: p.name || "я", kind: "self", onboarded: true, is_main: true }];

  const saved = first(sp.saved) === "1";
  const error = first(sp.error);
  const top = Object.entries(p.values).filter(([, w]) => w >= 5).map(([k]) => k).slice(0, TOP_VALUES);
  const groups = clusters(catalog.values, catalog.value_clusters);
  const cats = [...new Set([...catalog.categories, ...(catalog.business_categories ?? []), ...Object.keys(p.interests)])];
  const prm = p.params;
  const times = prm.times ?? [];
  const budget = BUDGET_CHIPS.some((b) => b.v === (prm.budget ?? 0)) ? (prm.budget ?? 0) : 0;
  const travel = Number(prm.travel_minutes ?? p.travel_minutes ?? 40);
  const aff = p.affinity ?? {};

  return (
    <div className="wrap">
      <Masthead title="Профиль" tab="profile" profiles={list} activeId={pid} planDot={hasUnmarkedDecisions(decisions, moscowToday())} />
      <main id="main" className="page reveal" style={{ paddingTop: 4 }}>
        <ProfileChips profiles={list} activeId={pid} />
        {saved ? <p className="notice ok" role="status">Сохранено</p> : null}
        {error ? <p className="notice warn" role="alert">{error}</p> : null}

        <form action={saveProfile} className="profile">
          <section className="card stack" aria-labelledby="who">
            <h2 id="who" style={{ fontSize: 24 }}>Имя</h2>
            <label className="sr" htmlFor="pname">Имя</label>
            <input id="pname" name="name" type="text" maxLength={80} defaultValue={p.name} autoComplete="given-name" className="field" />
          </section>

          <section className="card stack" aria-labelledby="vals">
            <h2 id="vals" style={{ fontSize: 24 }}>Ценности</h2>
            <ValuePicker groups={groups} short={catalog.value_short ?? {}} initial={top} inline />
          </section>

          <section className="card" aria-labelledby="ints">
            <h2 id="ints" style={{ fontSize: 24, marginBottom: 6 }}>Направления</h2>
            {cats.map((c) => {
              const cur = Math.min(3, Math.max(0, p.interests[c] ?? 1));
              const id = `i-${c.replace(/\W+/g, "-")}`;
              return (
                <div key={c} className="irow2">
                  <label className="nm" htmlFor={id}>{c}</label>
                  <input id={id} type="range" name={`i:${c}`} min={0} max={3} step={1} defaultValue={cur} list="lvl" aria-valuetext={LEVELS[cur]} />
                  <output className="svc" htmlFor={id} aria-hidden="true">{LEVELS[cur]}</output>
                </div>
              );
            })}
          </section>

          <section className="card stack" aria-labelledby="bud">
            <h2 id="bud" style={{ fontSize: 24 }}>Бюджет</h2>
            <div className="pick" role="radiogroup" aria-labelledby="bud">
              {BUDGET_CHIPS.map((b) => (
                <label key={b.v}><input type="radio" name="budget" value={b.v} defaultChecked={budget === b.v} /><span>{b.l}</span></label>
              ))}
            </div>
          </section>

          <section className="card stack" aria-labelledby="tm">
            <h2 id="tm" style={{ fontSize: 24 }}>Время</h2>
            <div className="pick" role="group" aria-labelledby="tm">
              {TIMES.map((t) => (
                <label key={t}><input type="checkbox" name="times" value={t} defaultChecked={times.includes(t)} /><span>{cap(t)}</span></label>
              ))}
            </div>
          </section>

          <section className="card stack" aria-labelledby="tr">
            <h2 id="tr" style={{ fontSize: 24 }}>На дорогу</h2>
            <div className="range-row">
              <input id="travel" type="range" name="travel" min={10} max={90} step={5} defaultValue={travel} aria-labelledby="tr" aria-valuetext={`${travel} минут`} />
              <output className="svc fg" htmlFor="travel">{travel} мин</output>
            </div>
          </section>

          <div className="savebar">
            <button type="submit" className="btn primary">Сохранить</button>
          </div>
        </form>

        <section className="card stack" aria-labelledby="learned">
          <h2 id="learned" style={{ fontSize: 24 }}>Что я о тебе узнал</h2>
          <Learned tags={aff.tag ?? {}} cats={aff.cat ?? {}} />
        </section>

        <section className="card stack" aria-labelledby="friends">
          <h2 id="friends" style={{ fontSize: 24 }}>Друзья</h2>
          <ShowNameSwitch initial={p.show_name !== false} />
        </section>

        <section className="card stack" aria-labelledby="acc">
          <h2 id="acc" style={{ fontSize: 24 }}>Почта</h2>
          <EmailForm />
        </section>

        <section className="card stack" aria-labelledby="del">
          <h2 id="del" className="sr">Данные</h2>
          <DeleteData />
          <p className="foot" style={{ marginTop: 6 }}><a href="/policy">Политика обработки данных</a></p>
        </section>
      </main>
    </div>
  );
}
