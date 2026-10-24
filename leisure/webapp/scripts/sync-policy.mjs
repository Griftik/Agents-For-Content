// Копирует текст политики из leisure/web/POLICY.md (источник правды у дизайна) в webapp/content/policy.md.
// Если источника рядом нет (например, сборка из одной папки webapp), остаётся ранее скопированный файл.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = resolve(root, "..", "web", "POLICY.md");
const dst = resolve(root, "content", "policy.md");

mkdirSync(dirname(dst), { recursive: true });
if (existsSync(src)) {
  copyFileSync(src, dst);
  console.log("policy: скопировано из", src);
} else if (existsSync(dst)) {
  console.log("policy: источник не найден, остаётся", dst);
} else {
  console.error("policy: нет ни", src, "ни", dst);
  process.exit(1);
}
