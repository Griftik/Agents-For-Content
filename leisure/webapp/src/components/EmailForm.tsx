"use client";

import { useActionState } from "react";
import { linkEmailAction, type EmailState } from "@/app/actions";

/** «Чтобы не потерять подборку на другом телефоне»: почта для ссылки-входа (magic link). Пока у API нет SMTP — «почта подключится позже». */
export function EmailForm() {
  const [state, action, pending] = useActionState<EmailState, FormData>(linkEmailAction, { phase: "idle" });
  return (
    <form action={action} className="stack" style={{ gap: 8 }}>

      <div className="row">
        <label className="sr" htmlFor="email">Почта</label>
        <input id="email" name="email" type="email" inputMode="email" autoComplete="email" placeholder="name@example.com" required style={{ flex: "1 1 220px", minHeight: 44, width: "auto" }} />
        <button type="submit" className="btn" style={{ minHeight: 48 }} disabled={pending}>Прислать ссылку</button>
      </div>
      <p role="status" aria-live="polite" className={state.phase === "error" ? "field-error" : "muted"} style={{ fontSize: 13.5 }}>
        {state.phase === "sent" ? "Отправил ссылку. Она действует 15 минут и срабатывает один раз." : null}
        {state.phase === "later" ? "Почта пока не подключена. Попробуй позже." : null}
        {state.phase === "error" ? state.message : null}
      </p>
    </form>
  );
}
