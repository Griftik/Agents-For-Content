import { redirect } from "next/navigation";

/** Сессии ещё нет: гостевой аккаунт создаётся сам (SessionBoot в layout), страница обновится. */
export function AuthGate() {
  return (
    <main id="main" className="wrap page" style={{ paddingTop: 26 }}>
      <div className="notice" role="status">
        <h2>Готовим приложение</h2>
        <p>Секунду: создаём твой аккаунт. Входа и паролей нет.</p>
      </div>
    </main>
  );
}

/** Профиля или согласия ещё нет: начинаем с приветствия онбординга. */
export function NoProfile(): never {
  redirect("/profile?onboarding=welcome");
}

export function ApiDown({ message }: { message?: string }) {
  return (
    <main id="main" className="wrap page" style={{ paddingTop: 26 }}>
      <div className="notice warn" role="alert">
        <h2>Не получилось загрузить данные</h2>
        <p>Сервис подборок сейчас не отвечает. Обнови страницу через минуту.{message ? <span className="muted"> ({message})</span> : null}</p>
      </div>
    </main>
  );
}
