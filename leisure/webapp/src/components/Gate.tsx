import { botLink } from "@/lib/config";

/** Нет сессии: страница открыта не из Telegram или initData ещё не обменялся на сессию. */
export function AuthGate() {
  const bot = botLink();
  return (
    <main id="main" className="wrap page" style={{ paddingTop: 26 }}>
      <div className="notice">
        <h2>Открой приложение из Telegram</h2>
        <p>Логинов и паролей здесь нет: тебя узнаём по Telegram. Открой «Досуг» из бота, и подборка появится сама.</p>
        {bot ? <p style={{ marginTop: 10 }}><a className="btn go" href={bot}>Открыть бота</a></p> : null}
      </div>
    </main>
  );
}

/** Профиль ещё не создан: онбординг проходит в боте. */
export function NoProfile() {
  const bot = botLink("start");
  return (
    <main id="main" className="wrap page" style={{ paddingTop: 26 }}>
      <div className="notice">
        <h2>Сначала познакомимся</h2>
        <p>Профиля пока нет. Ответь на несколько вопросов в боте: это три минуты, и подборка станет твоей.</p>
        {bot ? <p style={{ marginTop: 10 }}><a className="btn go" href={bot}>Начать в боте</a></p> : null}
      </div>
    </main>
  );
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
