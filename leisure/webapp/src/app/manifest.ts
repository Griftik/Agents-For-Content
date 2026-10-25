import type { MetadataRoute } from "next";

/** Манифест PWA: приложение ставится на экран телефона и открывается без адресной строки. Цвета — leisure/web/DESIGN.md. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Catch",
    short_name: "Catch",
    description: "Ничего интересного мимо тебя не пройдёт.",
    lang: "ru",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#ECEEF1",
    theme_color: "#ECEEF1",
    categories: ["lifestyle", "entertainment"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
