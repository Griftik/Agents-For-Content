import type { Metadata } from "next";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { Markdown } from "@/lib/markdown";

export const metadata: Metadata = { title: "Политика обработки данных", robots: { index: true, follow: true } };

export default async function PolicyPage() {
  const source = await readFile(path.join(process.cwd(), "content", "policy.md"), "utf8");
  return (
    <div className="wrap">
      <main id="main" className="public prose">
        <Markdown source={source} />
        <p className="foot"><a href="/digest">К подборке</a></p>
      </main>
    </div>
  );
}
