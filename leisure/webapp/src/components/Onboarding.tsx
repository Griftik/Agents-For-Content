import { finishOnboardingAction, startOnboardingAction } from "@/app/actions";
import type { Catalog, Profile } from "@/lib/api-types";
import { BUDGETS, PROPOSED_N, TOP_VALUES, clusters, rankCategories, type OnboardingStep } from "@/lib/onboarding";
import { ValuePicker } from "./ValuePicker";

/**
 * Онбординг в Mini App из двух шагов (FLOW-ONBOARDING): приветствие с согласием (если профиля ещё нет) → «1 из 2» пять ценностей →
 * «2 из 2» восемь направлений и строка бюджета → «Дайджест». Тексты приветствия — T-REF-LANDING.
 */
export function Onboarding({ step, profile, catalog, error, needConsent }: { step: OnboardingStep; profile: Profile | null; catalog: Catalog; error?: string; needConsent?: boolean }) {
  return (
    <div className="wrap">
      <main id="main" className="onb">
        {step === "welcome" ? <Welcome hasConsent={!!profile?.has_consent} error={error} needConsent={needConsent} /> : null}
        {step === "1" ? <StepValues catalog={catalog} profile={profile} error={error} /> : null}
        {step === "2" && profile ? <StepInterests catalog={catalog} profile={profile} error={error} /> : null}
        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}

function Welcome({ hasConsent, error, needConsent }: { hasConsent: boolean; error?: string; needConsent?: boolean }) {
  return (
    <>
      <h1>Выходные под то, что для тебя важно</h1>
      <p style={{ maxWidth: "60ch" }}>
        Каждый четверг присылаю 5–7 событий и объясняю, почему они подходят именно тебе. Нужны два шага: пять главных ценностей и интересы, около минуты.
      </p>
      <form action={startOnboardingAction} className="stack">
        {!hasConsent ? (
          <label className="consent">
            <input type="checkbox" name="consent" aria-describedby={needConsent ? "need" : undefined} />
            <span>
              Даю согласие на обработку моего Telegram id, имени и ответов, чтобы собрать подборку. Подробнее в <a href="/policy" target="_blank" rel="noopener noreferrer">политике</a>.
            </span>
          </label>
        ) : null}
        {!hasConsent ? <input type="hidden" name="needs_consent" value="1" /> : null}
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
        <p className="eyebrow">Шаг 1 из 2</p>
        <h1>Что для тебя важно</h1>
      </div>
      <p>Выбери пять главных ценностей из {catalog.values.length}. Остальные тоже учту, но слабее.</p>
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
        <p className="eyebrow">Шаг 2 из 2</p>
        <h1>Интересы</h1>
      </div>
      <p>Восемь направлений под твои ценности. Нажми, чтобы убрать или вернуть; остальные покажу реже.</p>
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
        <legend className="eyebrow" style={{ marginBottom: 8 }}>Бюджет на событие</legend>
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
        <a className="btn quiet" href="/profile?onboarding=1">← Назад</a>
        <button type="submit" className="btn primary">Показать подборку →</button>
      </div>
      <p className="muted" style={{ fontSize: 13.5 }}>Все направления можно поправить позже в разделе «Профиль».</p>
    </form>
  );
}
