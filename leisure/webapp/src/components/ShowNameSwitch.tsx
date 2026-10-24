"use client";

import { useState, useTransition } from "react";
import { setShowNameAction } from "@/app/actions";

/** «Показывать имя друзьям» (T-SETUP-NAME): одно нажатие переключает на месте, PUT /api/profile show_name. */
export function ShowNameSwitch({ initial }: { initial: boolean }) {
  const [on, setOn] = useState(initial);
  const [error, setError] = useState(false);
  const [pending, start] = useTransition();
  const toggle = () => {
    const next = !on;
    setOn(next);
    setError(false);
    start(async () => {
      const r = await setShowNameAction(next);
      if (!r.ok) {
        setOn(!next);
        setError(true);
      }
    });
  };
  return (
    <div className="prow" style={{ flexWrap: "wrap" }}>
      <div className="nm">
        <span id="shn-l">Показывать имя друзьям</span>
        <p id="shn-d" className="muted" style={{ fontSize: 13.5 }}>
          Друг, которого ты позвал, увидит на странице события «{`{Имя}`} зовёт тебя». Если выключить, будет «Друг зовёт тебя».
        </p>
      </div>
      <span className="sw-row">
        <span className="muted" style={{ fontSize: 13.5 }}>{on ? "Показывается" : "Скрыто"}</span>
        <span className="sw">
          <input type="checkbox" role="switch" checked={on} onChange={toggle} disabled={pending} aria-labelledby="shn-l" aria-describedby="shn-d" />
          <i />
        </span>
      </span>
      {error ? <p role="alert" className="field-error" style={{ flexBasis: "100%" }}>Не получилось сохранить, попробуй ещё раз.</p> : null}
    </div>
  );
}
