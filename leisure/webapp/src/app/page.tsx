import { redirect } from "next/navigation";
import { AuthGate, ApiDown } from "@/components/Gate";
import { ApiError, api } from "@/lib/api";
import { first } from "@/lib/format";
import { getUserId } from "@/lib/session";
import { CODE_RE } from "@/lib/start-param";

export const dynamic = "force-dynamic";

/**
 * Первый экран: решает, куда вести. Нет сессии — ждём гостевой аккаунт (SessionBoot); нет согласия — приветствие; профиль не
 * настроен — онбординг; иначе подборка. Ссылка-рекомендация `/?ref=<код>` ведёт через `/r/<код>`.
 */
export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const ref = first(sp.ref);
  if (ref && CODE_RE.test(ref)) redirect(`/r/${ref}`);
  if (first(sp.deleted) === "1") {
    return (
      <main id="main" className="wrap page" style={{ paddingTop: 26 }}>
        <div className="notice ok" role="status">
          <h2>Данные удалены</h2>
          <p>Если захочешь вернуться, просто открой приложение: начнём с чистого листа.</p>
          <p style={{ marginTop: 10 }}><a className="btn primary" href="/profile?onboarding=welcome">Начать</a></p>
        </div>
      </main>
    );
  }
  const uid = await getUserId();
  if (!uid) return <AuthGate />;
  try {
    const p = await api.profile(uid);
    if (!p.has_consent) redirect("/profile?onboarding=welcome");
    redirect(p.onboarded ? "/digest" : "/profile?onboarding=1");
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 404) redirect("/profile?onboarding=welcome");
    return <ApiDown message={e.status ? String(e.status) : "нет связи"} />;
  }
}
