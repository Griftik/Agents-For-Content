import type { ReactNode } from "react";

export type Tab = "digest" | "plan" | "profile";

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
const TABS: { id: Tab; href: string; label: string; svg: ReactNode }[] = [
  { id: "digest", href: "/digest", label: "Лента", svg: icon(<><rect x="4" y="4" width="16" height="16" rx="4" /><path d="M4 14h16M9 14v6M15 14v6" /></>) },
  { id: "plan", href: "/plan", label: "План", svg: icon(<><rect x="4" y="5" width="16" height="15" rx="3" /><path d="M4 10h16M9 3v4M15 3v4" /></>) },
  { id: "profile", href: "/profile", label: "Профиль", svg: icon(<><circle cx="12" cy="9" r="4" /><path d="M5 20c1.2-3.5 4-5 7-5s5.8 1.5 7 5" /></>) },
];

/** Нижняя навигация из трёх вкладок; точка на «Плане», пока есть прошедшие события без отметки. */
export function BottomNav({ tab, planDot }: { tab: Tab; planDot?: boolean }) {
  return (
    <nav className="bottom-nav" aria-label="Основное">
      {TABS.map((t) => (
        <a key={t.id} href={t.href} className="bn-item" aria-current={t.id === tab ? "page" : undefined}
          aria-label={t.id === "plan" && planDot ? "План, есть неотмеченные" : undefined}>
          {t.svg}
          <span>{t.label}</span>
          {t.id === "plan" && planDot ? <i className="bn-dot" aria-hidden="true" /> : null}
        </a>
      ))}
    </nav>
  );
}
