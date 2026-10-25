"use client";

import { useEffect, useState } from "react";
import { dropOfferAction } from "@/app/actions";

/** Повтор предложения своей подборки приглашённому: один раз при первом открытии после дня события («Давай» / «Не нужно»). */
export function LaterOffer() {
  const [shown, setShown] = useState(true);
  // показан один раз: отмечаем сразу (offer_seen = 2), баннер остаётся до «Давай» / «Не нужно»
  useEffect(() => {
    void dropOfferAction();
  }, []);
  if (!shown) return null;
  return (
    <section className="offer later-bar" aria-labelledby="later-h">
      <h2 id="later-h">Свои рекомендации?</h2>
      <p>Два шага, около минуты.</p>
      <div className="row">
        <a className="btn primary" href="/profile?onboarding=1">Давай</a>
        <button type="button" className="btn" onClick={() => setShown(false)}>Не нужно</button>
      </div>
    </section>
  );
}
