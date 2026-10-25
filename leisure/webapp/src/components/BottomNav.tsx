import type { ReactNode } from "react";

export type Tab = "digest" | "plan" | "profile";

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
const TABS: { id: Tab; href: string; label: string; svg: ReactNode }[] = [
  { id: "digest", href: "/digest", label: "Рекомендации", svg: icon(<><rect x="5" y="3" width="14" height="18" rx="3" /><path d="M9 8h6M9 12h6" /></>) },
  { id: "plan", href: "/plan", label: "План", svg: icon(<><rect x="4" y="5" width="16" height="15" rx="3" /><path d="M8 3v4M16 3v4M4 10h16" /></>) },
  { id: "profile", href: "/profile", label: "Профиль", svg: icon(<><circle cx="12" cy="8" r="4" /><path d="M4 20c1-4 4-6 8-6s7 2 8 6" /></>) },
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
