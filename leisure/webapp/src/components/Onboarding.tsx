import { finishOnboardingAction, startOnboardingAction } from "@/app/actions";
import type { Catalog, Profile } from "@/lib/api-types";
import { BUDGETS, PROPOSED_N, TOP_VALUES, clusters, rankCategories, type OnboardingStep } from "@/lib/onboarding";
import { ValuePicker } from "./ValuePicker";

/**
 * Первый вход (FLOW-APP, А1 → Э1 → Э2): приветствие с согласием (T-APP-WELCOME, T-APP-CONSENT) → «Шаг 1 / 2» пять ценностей
 * (пятая сразу открывает шаг 2) → «Шаг 2 / 2» восемь направлений и бюджет → лента на сегодня.
 */
export function Onboarding({ step, profile, catalog, error, needConsent }: { step: OnboardingStep; profile: Profile | null; catalog: Catalog; error?: string; needConsent?: boolean }) {
  return (
    <div className="wrap">
      <main id="main" className="onb reveal">
        {step === "welcome" ? <Welcome hasConsent={!!profile?.has_consent} error={error} needConsent={needConsent} /> : null}
        {step === "1" ? <StepValues catalog={catalog} profile={profile} error={error} /> : null}
        {step === "2" && profile ? <StepInterests catalog={catalog} profile={profile} error={error} /> : null}
        {step === "welcome" ? <p className="foot"><a href="/policy">Политика обработки данных</a></p> : null}
      </main>
    </div>
  );
}

function Welcome({ hasConsent, error, needConsent }: { hasConsent: boolean; error?: string; needConsent?: boolean }) {
  return (
    <>
      <p className="svc fg">Catch</p>
      <h1>Ничего интересного мимо тебя не пройдёт</h1>
      <p style={{ maxWidth: "60ch" }}>Два шага, около минуты: что для тебя важно и что интересно. Регистрации нет.</p>
      <form action={startOnboardingAction} className="stack">
        {!hasConsent ? (
          <label className="consent">
            <input type="checkbox" name="consent" aria-describedby={needConsent ? "need" : undefined} />
            <span>
              Даю согласие на обработку моих ответов и решений, чтобы подбирать события. Данные хранятся в России. Подробнее в{" "}
              <a href="/policy" target="_blank" rel="noopener noreferrer">политике обработки данных</a>.
            </span>
            <small>Согласие можно отозвать в любой момент: «Удалить мои данные» в профиле.</small>
          </label>
        ) : null}
        {!hasConsent ? <input type="hidden" name="needs_consent" value="1" /> : null}
        {!hasConsent ? (
          <div className="stack" style={{ gap: 4 }}>
            <label htmlFor="who" className="svc">Имя, необязательно</label>
            <input id="who" name="name" type="text" maxLength={80} autoComplete="given-name" className="field" />
          </div>
        ) : null}
        {needConsent ? <p id="need" role="alert" className="field-error">Отметь согласие, чтобы продолжить.</p> : null}
        {error ? <p role="alert" className="field-error">Не получилось сохранить, попробуй ещё раз.</p> : null}
        <div className="row"><button type="submit" className="btn primary">Начать</button></div>
      </form>
    </>
  );
}

function StepValues({ catalog, profile, error }: { catalog: Catalog; profile: Profile | null; error?: string }) {
  const groups = clusters(catalog.values, catalog.value_clusters);
  const fives = profile ? Object.entries(profile.values).filter(([, w]) => w >= 5).map(([k]) => k) : [];
  return (
    <>
      <div>
        <p className="svc">Шаг 1 / 2</p>
        <h1>{profile && profile.kind && profile.kind !== "self" && profile.name ? `Что важно для ${profile.name}` : "Что для тебя важно"}</h1>
      </div>
      {error ? <p role="alert" className="field-error">{error === "save" ? "Не получилось сохранить, попробуй ещё раз." : `Нужно выбрать ровно ${TOP_VALUES}.`}</p> : null}
      <ValuePicker groups={groups} short={catalog.value_short ?? {}} initial={fives.length === TOP_VALUES ? fives : []} />
    </>
  );
}

function StepInterests({ catalog, profile, error }: { catalog: Catalog; profile: Profile; error?: string }) {
  const cats = [...catalog.categories, ...(catalog.business_categories ?? [])];
  const ranked = rankCategories(cats, profile.values, catalog.category_values, profile.interests);
  const shown = ranked.slice(0, PROPOSED_N);
  const budget = profile.params.budget ?? 0;
  const cur = BUDGETS.some((b) => b.value === budget) ? budget : 0;
  return (
    <form action={finishOnboardingAction} className="stack" style={{ gap: 18 }}>
      <div>
        <p className="svc">Шаг 2 / 2</p>
        <h1>Интересы</h1>
      </div>
      {error ? <p role="alert" className="field-error">Не получилось сохранить, попробуй ещё раз.</p> : null}
      <div className="pick" role="group" aria-label="Направления">
        {shown.map((c) => (
          <label key={c}>
            <input type="checkbox" name="cat" value={c} defaultChecked />
            <span>{c}</span>
          </label>
        ))}
      </div>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="svc" style={{ marginBottom: 8 }}>Бюджет</legend>
        <span className="seg wrapseg">
          {BUDGETS.map((b) => (
            <label key={b.value}>
              <input type="radio" name="budget" value={b.value} defaultChecked={b.value === cur} />
              <span>{b.label}</span>
            </label>
          ))}
        </span>
      </fieldset>
      <div className="row">
        <a className="btn quiet" href="/profile?onboarding=1" style={{ minHeight: 48 }}>Назад</a>
        <button type="submit" className="btn primary">Показать рекомендации</button>
      </div>
    </form>
  );
}
