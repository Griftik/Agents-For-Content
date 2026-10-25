"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Гостевая сессия с первого экрана (docs/PIVOT-PWA.md §2): если cookie нет, просим у веба аккаунт (POST /api/session →
 * POST API /api/session) и обновляем страницу. Согласие на обработку данных — отдельная галочка на приветствии, до неё
 * профиль не создаётся.
 */
export function SessionBoot({ authed }: { authed: boolean }) {
  const router = useRouter();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (authed) return;
    let live = true;
    fetch("/api/session", { method: "POST", credentials: "same-origin" })
      .then((r) => {
        if (!live) return;
        if (r.ok) router.refresh();
        else setFailed(true);
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [authed, router, attempt]);

  if (!failed || authed) return null;
  return (
    <p role="alert" className="notice warn" style={{ margin: "12px auto", maxWidth: 720 }}>
      Не получилось подготовить приложение. Проверь соединение.{" "}
      <button type="button" className="btn small" onClick={() => { setFailed(false); setAttempt((n) => n + 1); }}>Повторить</button>
    </p>
  );
}
