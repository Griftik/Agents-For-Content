"use client";

import { useEffect, useRef, useState } from "react";
import { copyToClipboard } from "@/lib/clipboard";

/** «Скопировать план» — единственное действие на странице плана, которому нужен JS. Без JS остаётся текст в <details>. */
export function CopyButton({ text, label = "Скопировать план", done = "План скопирован" }: { text: string; label?: string; done?: string }) {
  const [mounted, setMounted] = useState(false);
  const [state, setState] = useState<"" | "ok" | "fail">("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    setMounted(true);
    return () => clearTimeout(timer.current);
  }, []);

  async function copy() {
    const ok = await copyToClipboard(text);
    setState(ok ? "ok" : "fail");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState(""), 1800);
  }

  if (!mounted) return null;
  return (
    <>
      <button type="button" className="btn" onClick={copy}>{label}</button>
      <span className="copy-status" role="status" aria-live="polite">
        {state === "ok" ? done : state === "fail" ? "Не вышло, выдели текст ниже и скопируй" : ""}
      </span>
    </>
  );
}
