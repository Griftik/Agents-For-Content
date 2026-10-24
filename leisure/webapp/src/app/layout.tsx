import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { TelegramBoot } from "@/components/TelegramBoot";
import { getUserId } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Досуг", template: "%s · Досуг" },
  description: "Подборка выходных по твоим ценностям и интересам.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  colorScheme: "light dark",
};

const FONTS =
  "https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600&family=Oranienbaum&display=swap";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const uid = await getUserId();
  return (
    <html lang="ru">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={FONTS} />
      </head>
      <body>
        <a className="skip-link" href="#main">К содержимому</a>
        <TelegramBoot authed={uid != null} />
        {children}
      </body>
    </html>
  );
}
