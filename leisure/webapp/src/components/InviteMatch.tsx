import type { Why } from "@/lib/api-types";
import { Ring } from "./Ring";

/** «Совпадение N %» и «Почему тебе» для друга с настроенным профилем: те же кольцо и чипы, что на карточке дайджеста. */
export function InviteMatch({ score, why }: { score: number; why: Why[] }) {
  return (
    <section className="card stack" style={{ gap: 8 }} aria-label="Совпадение с твоими интересами">
      <div className="ring-wrap">
        <Ring score={score} />
        <b>Совпадение {Math.round(score)} %</b>
      </div>
      {why.length ? (
        <div className="row">
          <span className="eyebrow">Почему тебе ·</span>
          {why.map((w) => <span key={w.t} className={w.c === "learn" ? "why learn" : w.c === "neg" ? "why neg" : "why"}>{w.t}</span>)}
        </div>
      ) : null}
    </section>
  );
}
