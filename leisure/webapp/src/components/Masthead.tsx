import type { ReactNode } from "react";

type Tab = "digest" | "plan" | "profile";

export function Masthead({ eyebrow, title, accent, tab, digestCount, name }: {
  eyebrow: string;
  title: string;
  accent?: string;
  tab: Tab;
  digestCount?: number;
  name?: string;
}) {
  const tabs: { id: Tab; href: string; label: string; count?: ReactNode }[] = [
    { id: "digest", href: "/digest", label: "Подборка", count: digestCount },
    { id: "plan", href: "/plan", label: "План" },
    { id: "profile", href: "/profile", label: "Профиль" },
  ];
  return (
    <header className="mast-bar">
      <div className="mast">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h1>{title} {accent ? <i>{accent}</i> : null}</h1>
        </div>
        {name ? <span className="sync"><span className="dot" aria-hidden="true" />{name}</span> : null}
      </div>
      <nav className="tabs" aria-label="Разделы">
        {tabs.map((t) => (
          <a key={t.id} className="tab" href={t.href} aria-current={t.id === tab ? "page" : undefined}>
            {t.label}{t.count != null ? <> <b>{t.count}</b></> : null}
          </a>
        ))}
      </nav>
    </header>
  );
}
