"""Воронка /stats (п. 10): в целом, по источникам, и точка отвала по вопросам."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from bot.content import Content
from bot.db import repo
from bot.db.models import Event, Lead, utcnow


@dataclass
class Funnel:
    starts: set[int] = field(default_factory=set)
    began: set[int] = field(default_factory=set)
    completed: set[int] = field(default_factory=set)
    phone: set[int] = field(default_factory=set)
    report: set[int] = field(default_factory=set)
    hot: set[int] = field(default_factory=set)
    booking: set[int] = field(default_factory=set)
    contacted: set[int] = field(default_factory=set)
    specialists: set[int] = field(default_factory=set)

    def line(self) -> str:
        n = len(self.starts)

        def pct(x: set[int], base: int) -> str:
            return f"{len(x)} ({round(100 * len(x) / base)}%)" if base else str(len(x))

        return (
            f"старты {n} | начали {pct(self.began, n)} | завершили {pct(self.completed, n)}"
            f" | телефон {pct(self.phone, n)}\n"
            f"разбор отправлен {len(self.report)} | горячие {pct(self.hot, len(self.phone))} от контактов"
            f" | перешли к записи {len(self.booking)} | связался {len(self.contacted)}"
            f" | специалисты {len(self.specialists)}"
        )


EVENT_BUCKET = {
    "start": "starts", "app_started": "began", "app_completed": "completed",
    "contact_shared": "phone", "report_sent": "report", "booking_link_clicked": "booking",
    "specialist_docs_sent": "specialists",
}


def build(events: list[Event], contacted: list[Lead], c: Content) -> tuple[Funnel, dict[str, Funnel], Counter]:
    total = Funnel()
    by_src: dict[str, Funnel] = defaultdict(Funnel)
    user_src: dict[int, str] = {}
    last_q: dict[int, int] = {}
    order = c.order

    for e in events:
        if e.user_id is None:
            continue
        src = (e.payload or {}).get("source") or "direct"
        user_src.setdefault(e.user_id, src)
        bucket = EVENT_BUCKET.get(e.name)
        if e.name == "segment_assigned" and (e.payload or {}).get("segment") == "hot":
            bucket = "hot"
        if bucket:
            getattr(total, bucket).add(e.user_id)
            getattr(by_src[src], bucket).add(e.user_id)
        if e.name == "q_answered":
            q = (e.payload or {}).get("q_code")
            if q in order:
                last_q[e.user_id] = max(last_q.get(e.user_id, -1), order.index(q))

    for lead in contacted:
        total.contacted.add(lead.user_id)
        by_src[user_src.get(lead.user_id, "direct")].contacted.add(lead.user_id)

    # Отвал: начали, не завершили и не ушли в ветку специалиста → бросили на следующем вопросе
    drop: Counter = Counter()
    for uid in total.began - total.completed - total.specialists:
        i = last_q.get(uid, -1) + 1
        drop[order[i] if i < len(order) else "contact"] += 1
    return total, dict(by_src), drop


async def stats_text(c: Content, days: int) -> str:
    since = utcnow() - timedelta(days=days)
    total, by_src, drop = build(await repo.events_since(since), await repo.contacted_since(since), c)
    lines = [f"Воронка за {days} дн.", total.line(), ""]
    for src, f in sorted(by_src.items(), key=lambda kv: -len(kv[1].starts)):
        lines += [f"— {src}", f.line()]
    lines.append("")
    if drop:
        lines.append("Где бросают заявку:")
        for q, n in drop.most_common():
            num = f"{c.order.index(q) + 1}. " if q in c.order else ""
            text = c.question(q).text if c.question(q) else "запрос телефона"  # type: ignore[union-attr]
            lines.append(f"{n} — {num}{text}")
    else:
        lines.append("Брошенных заявок нет.")
    return "\n".join(lines)
