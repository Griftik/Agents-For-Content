import type { ReactNode } from "react";

/** Минимальный рендер Markdown для /policy: заголовки, абзацы, списки, таблицы, цитаты, **жирный**, `код`, [ссылки](url). */

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**")) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={k}>{part.slice(1, -1)}</code>;
    const m = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (m) {
      const safe = /^(https?:\/\/|\/|mailto:)/.test(m[2]);
      return safe ? <a key={k} href={m[2]} rel="noopener noreferrer">{m[1]}</a> : <span key={k}>{m[1]}</span>;
    }
    return <span key={k}>{part}</span>;
  });
}

const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function Markdown({ source }: { source: string }): ReactNode {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let n = 0;
  while (i < lines.length) {
    const line = lines[i];
    const key = `b${n++}`;
    if (!line.trim()) { i++; continue; }

    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const Tag = (`h${h[1].length}`) as "h1" | "h2" | "h3";
      out.push(<Tag key={key}>{inline(h[2], key)}</Tag>);
      i++;
    } else if (line.startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(<blockquote key={key}>{inline(buf.join(" "), key)}</blockquote>);
    } else if (line.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      const [head, , ...body] = rows;
      out.push(
        <table key={key}>
          <thead><tr>{head.map((c, j) => <th key={j} scope="col">{inline(c, `${key}h${j}`)}</th>)}</tr></thead>
          <tbody>{body.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${key}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
        </table>,
      );
    } else if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      const L = ordered ? "ol" : "ul";
      out.push(<L key={key}>{items.map((t, j) => <li key={j}>{inline(t, `${key}i${j}`)}</li>)}</L>);
    } else {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|>|\||\s*([-*]|\d+\.)\s+)/.test(lines[i])) buf.push(lines[i++].trim());
      out.push(<p key={key}>{inline(buf.join(" "), key)}</p>);
    }
  }
  return <>{out}</>;
}
