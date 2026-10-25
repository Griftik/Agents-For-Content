"use client";

import { useState } from "react";
import { deleteDataAction } from "@/app/actions";

/** «Удалить мои данные»: двухшаговое подтверждение, затем профиль, решения и подписки стираются, сессия сбрасывается. */
export function DeleteData() {
  const [ask, setAsk] = useState(false);
  return (
    <div className="stack" style={{ gap: 8 }}>
      {!ask ? (
        <div className="row"><button type="button" className="btn danger" style={{ minHeight: 48 }} onClick={() => setAsk(true)}>Удалить мои данные</button></div>
      ) : (
        <form action={deleteDataAction} className="stack" style={{ gap: 8 }} role="alertdialog" aria-labelledby="del-q">
          <p id="del-q">Удалить профиль и решения? Это отзыв согласия на обработку данных. Восстановить будет нельзя.</p>
          <div className="row">
            <button type="submit" className="btn primary" style={{ minHeight: 48 }}>Удалить всё</button>
            <button type="button" className="btn" style={{ minHeight: 48 }} onClick={() => setAsk(false)}>Оставить</button>
          </div>
        </form>
      )}
    </div>
  );
}
