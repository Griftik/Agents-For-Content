import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { LaterOffer } from "@/components/LaterOffer";
import { PwaBoot } from "@/components/PwaBoot";
import { SessionBoot } from "@/components/SessionBoot";
import { api, ApiError } from "@/lib/api";
import { moscowToday } from "@/lib/format";
import { offerAgain } from "@/lib/offer";
import { getProfileId, getUserId } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Досуг", template: "%s · Досуг" },
  description: "События под то, что для тебя важно: сегодня, завтра, на неделю.",
  robots: { index: false, follow: false },
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, statusBarStyle: "default", title: "Досуг" },
  icons: { apple: "/icons/apple-touch-icon.png", icon: "/icons/icon-192.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ECEEF1" },
    { media: "(prefers-color-scheme: dark)", color: "#141619" },
  ],
};

const FONTS = "https://fonts.googleapis.com/css2?family=Piazzolla:wght@800&family=Golos+Text:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap";
// Одно оркестрованное появление на запуск (DESIGN.md, раздел 4): атрибут ставится до первой отрисовки, один раз за сессию вкладки.
const REVEAL = "try{if(!sessionStorage.getItem('leisure:revealed')){sessionStorage.setItem('leisure:revealed','1');document.documentElement.dataset.reveal='1'}}catch(e){}";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const uid = await getUserId();
  const pid = await getProfileId();
  // Повтор предложения своей подборки приглашённому (profile.offer_due = день события + 1): один раз, если онбординг не пройден.
  let offer = false;
  if (pid) {
    try {
      offer = offerAgain(await api.profile(pid), moscowToday());
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
  }
  return (
    <html lang="ru" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={FONTS} />
        <script dangerouslySetInnerHTML={{ __html: REVEAL }} />
      </head>
      <body>
        <a className="skip-link" href="#main">К содержимому</a>
        <SessionBoot authed={uid != null} />
        <PwaBoot />
        {children}
        {offer ? <LaterOffer /> : null}
      </body>
    </html>
  );
}
