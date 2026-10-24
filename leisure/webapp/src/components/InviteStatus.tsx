type Kind = "past" | "unpublished" | "bad";

const TEXT: Record<Kind, { guest: string; member: string }> = {
  past: {
    guest: "Это событие уже прошло, но выходные впереди. Подборку под себя можно собрать за два шага.",
    member: "Это событие уже прошло. Подборка на ближайшие выходные ждёт в «Дайджесте».",
  },
  unpublished: {
    guest: "Это событие убрали из афиши. На ближайшие выходные есть другие: подборку под себя можно собрать за два шага.",
    member: "Это событие убрали из афиши. Другие на ближайшие выходные ждут в «Дайджесте».",
  },
  bad: {
    guest: "Эта ссылка не работает. Подборку на выходные можно собрать за два шага.",
    member: "Эта ссылка не работает. Подборка на ближайшие выходные ждёт в «Дайджесте».",
  },
};

/** Приглашение не действует (T-INVITE-PAST / -UNPUBLISHED / -BAD): понятный экран вместо шапки и кнопок решения, выход в «Дайджест». */
export function InviteStatus({ kind, hasProfile, title }: { kind: Kind; hasProfile: boolean; title?: string }) {
  return (
    <div className="wrap">
      <main id="main" className="public">
        {title ? <p className="eyebrow">{title}</p> : null}
        <div className="notice" role="status">
          <p>{hasProfile ? TEXT[kind].member : TEXT[kind].guest}</p>
        </div>
        <div className="row">
          {hasProfile ? (
            <a className="btn primary" href="/digest">Дайджест</a>
          ) : (
            <>
              <a className="btn primary" href="/profile?onboarding=welcome">Другие выходные под меня</a>
              <a className="btn" href="/digest">Дайджест</a>
            </>
          )}
        </div>
        <p className="foot"><a href="/policy">Политика обработки данных</a></p>
      </main>
    </div>
  );
}
