// Рисует иконки PWA без внешних зависимостей (PNG собирается вручную: zlib + CRC). Запуск: node scripts/make-icons.mjs
// Знак: буква C (Catch) акцентом на фоне светлой темы. Цвета — DESIGN.md; окончательный знак опишет дизайн.
import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const out = resolve(dirname(fileURLToPath(import.meta.url)), "..", "public", "icons");
mkdirSync(out, { recursive: true });

const BG = [0xec, 0xee, 0xf1];   // --bg светлой темы
const INK = [0x7a, 0x1f, 0x3d];  // --accent

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
const chunk = (type, data) => {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const c = Buffer.alloc(4);
  c.writeUInt32BE(crc(body));
  return Buffer.concat([len, body, c]);
};

/** scale — доля стороны, занятая знаком (для maskable меньше: безопасная зона 80 %). */
function png(size, scale, rounded) {
  const SS = 3; // сглаживание
  const raw = Buffer.alloc((size * 4 + 1) * size);
  const cx = size / 2;
  const R = (size * scale) / 2;
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    for (let x = 0; x < size; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SS; sy++) for (let sx = 0; sx < SS; sx++) {
        const px = x + (sx + 0.5) / SS, py = y + (sy + 0.5) / SS;
        const d = Math.hypot(px - cx, py - cx);
        // скруглённый квадрат для обычных иконок; maskable и так обрезается системой
        const inside = !rounded || (() => {
          const rad = size * 0.22, qx = Math.abs(px - cx) - (cx - rad), qy = Math.abs(py - cx) - (cx - rad);
          return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) <= rad;
        })();
        let col = null;
        if (inside) {
          col = BG;
          // буква C: кольцо толщиной 0.26R с вырезом справа (сектор ±38°)
          const ang = Math.atan2(py - cx, px - cx);
          const inRing = Math.abs(d - R * 0.62) <= R * 0.13;
          const gap = Math.abs(ang) < (38 * Math.PI) / 180;
          if (inRing && !gap) col = INK;
        }
        if (col) { r += col[0]; g += col[1]; b += col[2]; a += 255; }
      }
      const n = SS * SS, i = y * (size * 4 + 1) + 1 + x * 4;
      const cov = a / 255;
      raw[i] = cov ? Math.round(r / cov) : 0;
      raw[i + 1] = cov ? Math.round(g / cov) : 0;
      raw[i + 2] = cov ? Math.round(b / cov) : 0;
      raw[i + 3] = Math.round(a / n);
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw, { level: 9 })), chunk("IEND", Buffer.alloc(0))]);
}

const files = { "icon-192.png": [192, 0.8, true], "icon-512.png": [512, 0.8, true], "maskable-512.png": [512, 0.6, false], "apple-touch-icon.png": [180, 0.8, false] };
for (const [name, [size, scale, rounded]] of Object.entries(files)) writeFileSync(resolve(out, name), png(size, scale, rounded));
console.log("иконки:", Object.keys(files).join(", "));
