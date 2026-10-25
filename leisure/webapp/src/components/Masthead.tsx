import type { AccountProfile } from "@/lib/api-types";
import { BottomNav, type Tab } from "./BottomNav";
import { ProfileSwitcher } from "./ProfileSwitcher";

export type { Tab };

/** Каркас экрана: заголовок вкладки слева, переключатель профилей справа, нижняя навигация. */
export function Masthead({ title, tab, profiles, activeId, planDot }: { title: string; tab: Tab; profiles: AccountProfile[]; activeId: number; planDot?: boolean }) {
  return (
    <>
      <header className="app-head">
        <h1>{title}</h1>
        <ProfileSwitcher profiles={profiles} activeId={activeId} />
      </header>
      <BottomNav tab={tab} planDot={planDot} />
    </>
  );
}
