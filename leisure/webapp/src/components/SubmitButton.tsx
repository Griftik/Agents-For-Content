"use client";

import { useFormStatus } from "react-dom";

/** Кнопка формы, которая блокируется на время запроса: двойное нажатие не шлёт второй POST. */
export function SubmitButton({ children, className = "btn primary" }: { children: React.ReactNode; className?: string }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={className} disabled={pending} aria-busy={pending || undefined}>
      {children}
    </button>
  );
}
