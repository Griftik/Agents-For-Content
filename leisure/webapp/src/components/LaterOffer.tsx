"use client";

import { useState } from "react";
import { dropOfferAction } from "@/app/actions";

/** Повтор предложения подборки (T-INVITE-OFFER, «повтор»): один раз при первом открытии Mini App после дня события. */
export function LaterOffer() {
  const [shown, setShown] = useState(true);
  if (!shown) return null;
  const close = () => {
    setShown(false);
    void dropOfferAction();
  };
  return (
    <section className="offer later-bar" aria-labelledby="later-h">
      <h2 id="later-h" className="sr">Своя подборка</h2>
      <p>Если понравилось, могу подбирать такие выходные каждую неделю. Два шага, около минуты.</p>
      <div className="row">
        <a className="btn primary" href="/profile?onboarding=1" onClick={() => void dropOfferAction()}>Давай</a>
        <button type="button" className="btn" onClick={close}>Не нужно</button>
      </div>
    </section>
  );
}
