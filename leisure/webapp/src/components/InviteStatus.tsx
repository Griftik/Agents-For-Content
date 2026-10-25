type Kind = "past" | "unpublished" | "bad";

const TEXT: Record<Kind, { guest: string; member: string }> = {
  past: { guest: "Это событие уже прошло.", member: "Это событие уже прошло." },
  unpublished: { guest: "Это событие убрали из афиши.", member: "Это событие убрали из афиши." },
  bad: { guest: "Эта ссылка не работает.", member: "Эта ссылка не работает." },
};

/** Приглашение не действует (T-INVITE-PAST / -UNPUBLISHED / -BAD): понятный экран вместо шапки и кнопок решения, выход в «Дайджест». */
export function InviteStatus({ kind, hasProfile, title }: { kind: Kind; hasProfile: boolean; title?: string }) {
  return (
    <div className="wrap">
      <main id="main" className="public">
        {title ? <p className="svc">{title}</p> : null}
        <div className="notice" role="status">
          <p>{hasProfile ? TEXT[kind].member : TEXT[kind].guest}</p>
        </div>
        <div className="row">
          {hasProfile ? (
            <a className="btn primary" href="/digest">Рекомендации</a>
          ) : (
            <a className="btn primary" href="/profile?onboarding=welcome">Другие события под меня</a>
          )}
        </div>
        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}
