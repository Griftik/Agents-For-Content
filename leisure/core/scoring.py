"""Скоринг события под профиль (п. 6.4 спеки). Перенос score() прототипа с теми же числами.

Отличие от прототипа — одно и осознанное: ценность «Инновации/новизна» = 0 в профиле даёт 0 (по спеке),
а не 3 (в JS `||3` подменял ноль). Остальные веса и пороги — в scoring.yaml.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .affinity import compute_affinity, learning_bonus
from .catalog import NOVELTY_VALUE, VALUE_MAP, value_label
from .config import scoring_config
from .timeutil import clamp, js_round, price_num, slot_of


@dataclass(frozen=True)
class Why:
    text: str
    kind: str = ""  # '' — позитив, 'neg' — негатив, 'learn' — из обучения

    def as_dict(self) -> dict:
        return {"t": self.text, "c": self.kind}


@dataclass
class ScoreResult:
    score: int                      # 0–100, итог с учётом продвижения
    base: int                       # 0–100 без продвижения
    raw: float                      # до округления и обрезки
    why: list[Why] = field(default_factory=list)
    promoted: bool = False

    def why_dicts(self, limit: int | None = None) -> list[dict]:
        return [w.as_dict() for w in (trim_why(self.why, limit) if limit else self.why)]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["why"] = [w.as_dict() for w in self.why]
        return d


def trim_why(why: list[Why], n: int) -> list[Why]:
    """До n причин: негативные не отбрасываем, позитивные — по порядку."""
    if len(why) <= n:
        return list(why)
    neg = [w for w in why if w.kind == "neg"]
    pos = [w for w in why if w.kind != "neg"]
    keep = set(id(w) for w in (neg + pos)[:max(n, len(neg))])
    return [w for w in why if id(w) in keep]


def is_promoted(ev: Mapping, now: datetime | None = None) -> bool:
    pu = ev.get("promoted_until")
    if not pu:
        return False
    if isinstance(pu, str):
        pu = datetime.fromisoformat(pu.replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    if pu.tzinfo is None:
        pu = pu.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return pu > now


def score(ev: Mapping, profile: Mapping, aff: Mapping | None = None, cfg: dict | None = None,
          now: datetime | None = None) -> ScoreResult:
    cfg = cfg or scoring_config()
    values: Mapping = profile.get("values") or {}
    interests: Mapping = profile.get("interests") or {}
    params: Mapping = profile.get("params") or {}
    W = cfg
    why: list[Why] = []
    s = 0.0

    # интерес к категории
    category = ev.get("category") or ""
    iw = interests.get(category, W["interest"]["default_level"])
    iw = int(iw) if iw is not None else int(W["interest"]["default_level"])
    s += iw * float(W["interest"]["per_level"])

    # ценности по тегам
    vsum = vn = 0.0
    hit: dict[str, float] = {}
    for t in ev.get("tags") or []:
        for v, k in VALUE_MAP.get(t, ()):
            pv = float(values.get(v, 0) or 0)
            vsum += pv * k
            vn += k
            hit[v] = max(hit.get(v, 0.0), pv)
    vavg = vsum / vn if vn else float(W["values"]["empty_average"])
    s += vavg * float(W["values"]["multiplier"])
    strong = [(v, w) for v, w in hit.items() if w >= float(W["why"]["value_min_weight"])]
    strong.sort(key=lambda vw: -vw[1])  # устойчивая сортировка, как Array.sort в JS
    for v, _ in strong[: int(W["why"]["max_values"])]:
        why.append(Why(value_label(v)))

    # эстетика
    aw = float(W["aesthetics"]["required"] if params.get("aesthetics") else W["aesthetics"]["optional"])
    aest = ev.get("aesthetics") or W["aesthetics"]["default_level"]
    s += float(aest) * aw
    if float(ev.get("aesthetics") or 0) >= float(W["why"]["aesthetics_min"]):
        why.append(Why("эстетика 5/5"))

    # новизна × ценность новизны
    nv = values.get(NOVELTY_VALUE)
    nv = float(W["novelty"]["value_default"]) if nv is None else float(nv)
    nov = ev.get("novelty") or W["novelty"]["default_level"]
    s += float(nov) * (nv / 5) * float(W["novelty"]["multiplier"])
    if float(ev.get("novelty") or 0) >= float(W["why"]["novelty_min"]):
        why.append(Why("нетривиально"))

    # аудитория
    if ev.get("audience_30plus"):
        s += float(W["audience"]["plus30_bonus"])
    elif params.get("adults30"):
        s += float(W["audience"]["adults30_penalty"])

    # с детьми (params.kids или company «с детьми»): +детские события, −ночные и шумные. Выключено в профиле по умолчанию
    if params.get("kids") or params.get("company") == "с детьми":
        K = W["kids"]
        if ev.get("audience_kids"):
            s += float(K["audience_bonus"])
            why.append(Why("подходит с детьми"))
        if set(ev.get("tags") or []) & set(K["night_noisy_tags"]):
            s += float(K["night_noisy_penalty"])
            why.append(Why("поздно или шумно для детей", "neg"))

    # бюджет (бесплатное никогда не «выше бюджета»)
    budget = float(params.get("budget") or 0)
    pr = price_num(ev)
    if budget > 0 and pr and pr > budget:
        s += float(W["budget"]["over_penalty"])
        why.append(Why("выше бюджета", "neg"))

    # обучение
    lb = learning_bonus(ev, aff, cfg)
    s += lb
    thr = float(W["why"]["learn_threshold"])
    if lb >= thr:
        why.append(Why("похоже на то, что ты выбирал", "learn"))
    elif lb <= -thr:
        why.append(Why("похоже на отклонённое", "neg"))

    # уверенность и время
    if ev.get("confidence") == "нужно проверить":
        s += float(W["confidence"]["check_penalty"])
    if slot_of(ev) in (params.get("times") or []):
        s += float(W["time"]["match_bonus"])

    # интерес выключен / максимальный
    if iw == 0:
        s *= float(W["interest"]["off_multiplier"])
        why.insert(0, Why("интерес выключен", "neg"))
    elif iw == 3:
        why.insert(0, Why(f"{category} · 3/3"))

    base = int(clamp(js_round(s), 0, 100))
    final = base
    promoted = False
    if is_promoted(ev, now) and base >= int(cfg["promotion"]["min_base_score"]):
        promoted = True
        final = int(clamp(base + int(cfg["promotion"]["bonus"]), 0, 100))
        why.append(Why("партнёр"))
    return ScoreResult(score=final, base=base, raw=s, why=why, promoted=promoted)


def score_events(events: Iterable[Mapping], profile: Mapping, decisions: Iterable[Mapping] = (),
                 cfg: dict | None = None, aff: Mapping | None = None, now: datetime | None = None,
                 key: str = "id") -> dict[str, ScoreResult]:
    """Скоринг пачки событий под один профиль; affinity считается один раз (или берётся готовая)."""
    cfg = cfg or scoring_config()
    if aff is None:
        aff = profile.get("affinity") or compute_affinity(list(decisions), cfg)
    return {str(ev.get(key) or ev.get("slug")): score(ev, profile, aff, cfg, now) for ev in events}
