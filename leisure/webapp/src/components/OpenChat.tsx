"use client";

import { inTelegram, openTelegramLink } from "@/lib/tg-client";

/**
 * Запасной путь, если право писать не выдано (отказ в requestWriteAccess, старый клиент): чат с ботом по ссылке `?start=w_<код>`,
 * бэкенд на /start ставит can_write. Нужен, чтобы план и напоминания всё же приходили в чат.
 */
export function OpenChat({ url }: { url: string }) {
  return (
    <div className="stack" style={{ gap: 8 }} role="group" aria-label="Открыть чат с ботом">
      <p className="muted" style={{ fontSize: 14, maxWidth: "52ch" }}>
        Чтобы план на день и напоминание приходили в чат, открой чат с ботом и нажми «Start». Без этого они не дойдут, но план всегда виден здесь.
      </p>
      <div className="row">
        <a
          className="btn primary"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            if (inTelegram()) {
              e.preventDefault();
              openTelegramLink(url);
            }
          }}
        >
          Открыть чат с ботом
        </a>
      </div>
    </div>
  );
}
