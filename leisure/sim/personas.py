"""50 детерминированных персон: ответы онбординга, скрытый вкус и модель поведения.

Всё случайное берётся из random.Random, посеянного строкой «seed:индекс», поэтому один seed даёт одних и тех же людей.
Модуль не трогает БД и настройки продукта (только справочники leisure.core.catalog и чистые функции времени).
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass, field

from leisure.core.catalog import ALL_CATS, VALUE_MAP, VALUES
from leisure.core.timeutil import slot_of

DEFAULT_SEED = 20261024
FIRST_USER_ID = 900_000_001

NAMES = [
    "Анна", "Борис", "Вера", "Глеб", "Дарья", "Егор", "Жанна", "Иван", "Кира", "Лев", "Мария", "Никита", "Ольга",
    "Павел", "Регина", "Сергей", "Татьяна", "Ульяна", "Фёдор", "Хельга", "Цветана", "Чеслав", "Элла", "Юлия", "Яна",
    "Алексей", "Богдан", "Виктория", "Григорий", "Диана", "Евгений", "Злата", "Игорь", "Ксения", "Леонид", "Милана",
    "Назар", "Оксана", "Платон", "Раиса", "Святослав", "Тамара", "Устин", "Филипп", "Эмма", "Ярослав", "Алла",
    "Василий", "Галина", "Денис",
]

# Порядок шагов онбординга — по нему считаются отвалы. «areas» (район) из продукта убран, но остаётся в розыгрыше
# случайных чисел, чтобы набор персон не менялся между прогонами; персона, «бросившая» на нём, теперь проходит дальше.
STEPS = ["consent", "values", "weights", "interests", "company", "times", "budget", "aesthetics", "areas", "notes"]
# Базовая вероятность бросить именно на этом экране (до множителя архетипа). Допущение модели, не измерение.
STEP_HAZARD = {"consent": 0.03, "values": 0.03, "weights": 0.06, "interests": 0.07, "company": 0.01, "times": 0.01,
               "budget": 0.02, "aesthetics": 0.01, "areas": 0.01, "notes": 0.03}

NOTES = [
    "Надоели одинаковые концерты, хочется попробовать что-то руками.",
    "Хочу больше камерных мест и меньше толпы.",
    "Интересны лекции про город и технологии.",
    "Ищу компанию по интересам и неформальные встречи.",
    "Устал от шумных клубов, хочется тишины и природы.",
    "Хочу выставки и театр без очередей.",
    "Нужны события с детьми на день.",
    "Не люблю дорогие билеты, ищу бесплатное.",
]

# Архетипы. values — пять главных ценностей; cats_high/mid/off — истинные интересы (3 / 2 / 0, остальное 1).
ARCHETYPES: dict[str, dict] = {
    "эстет": dict(
        count=7, values=["Красота/эстетика", "Творчество", "Сохранение традиций", "Исследования", "Инновации/новизна"],
        extra=["Свобода", "Развитие"], high=["Театр", "Современное искусство", "Джаз", "Кино", "Концерты"],
        mid=["Винные бары", "Нетривиальное", "Природа и усадьбы"], off=["Вечеринки", "Волейбол", "Волейбол: матчи"],
        company=["с партнёром", "один"], times=[["вечер"], ["день", "вечер"]], budget=[0, 5000, 2500], aesthetics=0.95,
        area=["центр", "любой"], patience=0.75, engagement=0.80, decisive=0.70, hazard_mult=0.7, w=(0.55, 0.25, 0.20),
        p_rate=0.60, rating_bias=0.1, churn_thr=0.20, blocks=0.2),
    "нетворкер": dict(
        count=6, values=["Единство/Дружба", "Развитие", "Наставничество", "Инновации/новизна", "Свобода"],
        extra=["Творчество", "Исследования"], high=["Предприниматели и клубы", "Управление и стратегия", "ИИ и технологии",
                                                    "Конференции и форумы", "Бизнес-завтраки"],
        mid=["Винные бары", "Нетривиальное", "Закрытые клубы"], off=["Природа и усадьбы", "Волейбол"],
        company=["с друзьями", "любая"], times=[["вечер"], ["день", "вечер"]], budget=[0, 5000], aesthetics=0.4,
        area=["центр", "любой"], patience=0.7, engagement=0.80, decisive=0.8, hazard_mult=0.8, w=(0.6, 0.25, 0.15),
        p_rate=0.45, rating_bias=0.0, churn_thr=0.22, blocks=0.2),
    "интеллектуал": dict(
        count=7, values=["Исследования", "Развитие", "Творчество", "Инновации/новизна", "Сохранение традиций"],
        extra=["Красота/эстетика", "Свобода"], high=["ИИ и технологии", "Нетривиальное", "Кино", "Театр", "Современное искусство"],
        mid=["Образование для управленцев", "Джаз", "Природа и усадьбы"], off=["Вечеринки", "Волейбол: матчи"],
        company=["один", "с партнёром"], times=[["день", "вечер"], ["вечер"]], budget=[2500, 0], aesthetics=0.6,
        area=["любой", "центр"], patience=0.9, engagement=0.82, decisive=0.6, hazard_mult=0.5, w=(0.5, 0.3, 0.2),
        p_rate=0.55, rating_bias=-0.1, churn_thr=0.20, blocks=0.1),
    "родитель": dict(
        count=5, values=["Семья", "Забота", "Здоровье", "Природа", "Сохранение традиций"],
        extra=["Развитие", "Единство/Дружба"], high=["Своими руками", "Природа и усадьбы", "Кино"],
        mid=["Театр", "Нетривиальное"], off=["Вечеринки", "Винные бары", "Концерты"],
        company=["с детьми"], times=[["утро", "день"], ["день"]], budget=[1000, 2500], aesthetics=0.5,
        area=["свой округ", "любой"], patience=0.45, engagement=0.60, decisive=0.7, hazard_mult=1.4, w=(0.5, 0.35, 0.15),
        p_rate=0.35, rating_bias=0.0, churn_thr=0.25, blocks=0.3),
    "спортсмен": dict(
        count=5, values=["Здоровье", "Природа", "Единство/Дружба", "Свобода", "Развитие"],
        extra=["Семья", "Наставничество"], high=["Волейбол", "Волейбол: матчи", "Природа и усадьбы"],
        mid=["Нетривиальное", "Концерты"], off=["Театр", "Современное искусство", "Винные бары"],
        company=["с друзьями", "любая"], times=[["утро", "день"], ["день"]], budget=[1000, 0], aesthetics=0.2,
        area=["любой", "свой округ"], patience=0.55, engagement=0.65, decisive=0.8, hazard_mult=1.1, w=(0.6, 0.2, 0.2),
        p_rate=0.4, rating_bias=0.2, churn_thr=0.25, blocks=0.3),
    "тусовщик": dict(
        count=6, values=["Единство/Дружба", "Свобода", "Творчество", "Инновации/новизна", "Красота/эстетика"],
        extra=["Здоровье"], high=["Вечеринки", "Концерты", "Джаз", "Винные бары"],
        mid=["Кино", "Нетривиальное", "Современное искусство"], off=["Управление и стратегия", "Образование для управленцев",
                                                                       "Природа и усадьбы"],
        company=["с друзьями"], times=[["вечер", "ночь"], ["ночь"]], budget=[2500, 0], aesthetics=0.7,
        area=["центр"], patience=0.5, engagement=0.75, decisive=0.85, hazard_mult=1.2, w=(0.55, 0.25, 0.2),
        p_rate=0.4, rating_bias=0.1, churn_thr=0.22, blocks=0.25),
    "экономный": dict(
        count=5, values=["Развитие", "Забота", "Природа", "Свобода", "Исследования"],
        extra=["Семья", "Здоровье"], high=["Природа и усадьбы", "Своими руками", "Кино", "Нетривиальное"],
        mid=["ИИ и технологии", "Театр"], off=["Винные бары", "Вечеринки", "Закрытые клубы"],
        company=["любая", "один"], times=[["день"], ["день", "вечер"]], budget=[1000], aesthetics=0.3,
        area=["любой", "свой округ"], patience=0.6, engagement=0.65, decisive=0.7, hazard_mult=0.9, w=(0.5, 0.3, 0.2),
        p_rate=0.4, rating_bias=-0.2, churn_thr=0.25, blocks=0.2),
    "занятой": dict(
        count=6, values=["Развитие", "Наставничество", "Семья", "Здоровье", "Инновации/новизна"],
        extra=["Единство/Дружба", "Свобода"], high=["Управление и стратегия", "Конференции и форумы", "ИИ и технологии"],
        mid=["Предприниматели и клубы", "Кино", "Концерты"], off=["Вечеринки", "Своими руками"],
        company=["любая", "с партнёром"], times=[["вечер"], ["день", "вечер"]], budget=[0, 5000], aesthetics=0.4,
        area=["центр", "любой"], patience=0.2, engagement=0.45, decisive=0.55, hazard_mult=2.4, w=(0.5, 0.35, 0.15),
        p_rate=0.2, rating_bias=0.0, churn_thr=0.28, blocks=0.4),
    "мастер": dict(
        count=3, values=["Творчество", "Природа", "Свобода", "Исследования", "Красота/эстетика"],
        extra=["Сохранение традиций", "Забота"], high=["Своими руками", "Природа и усадьбы", "Современное искусство"],
        mid=["Кино", "Джаз", "Нетривиальное"], off=["Управление и стратегия", "Вечеринки"],
        company=["один", "с партнёром"], times=[["день"], ["день", "вечер"]], budget=[1000, 2500], aesthetics=0.85,
        area=["любой"], patience=0.7, engagement=0.70, decisive=0.6, hazard_mult=1.0, w=(0.45, 0.3, 0.25),
        p_rate=0.5, rating_bias=0.1, churn_thr=0.22, blocks=0.15),
}

# Допущения модели поведения (не измерения): общий сдвиг вовлечённости и порога ухода.
ENGAGEMENT_SCALE = 0.72
CHURN_SHIFT = 0.12

TZ_OVERRIDES = ["Europe/Kaliningrad", "Asia/Yekaterinburg", "Asia/Novosibirsk"]  # «переехавшие»: у остальных Москва


@dataclass
class Persona:
    idx: int
    user_id: int
    name: str
    username: str
    archetype: str
    tz: str
    # ответы онбординга
    top_values: list[str]
    important: list[str]
    interest_targets: dict[str, int]
    max_interest_taps: int
    overselect: bool
    company: str
    times: list[str]
    budget: int
    aesthetics: bool
    area: str                         # скрытое предпочтение (влияет на причину «далеко»); бот про район больше не спрашивает
    note: str
    # онбординг: сбои поведения
    abandon_step: str | None
    abandon_sub: int
    misclick_step: str | None
    misclick_recovery: str
    noise_step: str | None
    help_at_notes: bool
    onboard_offset_h: float          # часов от вторника 2026-10-20 00:00 UTC
    # поведение после онбординга
    engagement: float
    p_open_scale: float
    view_range: tuple[int, int]
    decisive: float
    w_go_maybe_interest: tuple[float, float, float]
    p_rate: float
    p_attend: float
    rating_bias: float
    double_tap: float
    delay_profile: str
    churn_thr: float
    blocks_on_churn: bool
    p_cmd: dict[str, float]
    delete_week: int | None
    reset_week: int | None
    reason_none_p: float
    seed_key: str = ""
    taste_cats: dict[str, float] = field(default_factory=dict)
    value_w: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    # ── скрытый вкус: насколько событие ему подходит на самом деле (0..1) ──
    def whim(self, slug: str) -> float:
        h = hashlib.sha256(f"{self.seed_key}|{slug}".encode()).digest()
        return int.from_bytes(h[:4], "big") / 2**32 - 0.5  # детерминированный шум −0.5…+0.5

    def values_fit(self, tags: list[str]) -> float:
        s = n = 0.0
        for t in tags:
            for v, k in VALUE_MAP.get(t, ()):
                s += self.value_w.get(v, 1) * k
                n += k
        return (s / n / 5.0) if n else 0.5

    def fit(self, ev: dict) -> float:
        cat = self.taste_cats.get(ev.get("category") or "", 0.33)
        vf = self.values_fit(list(ev.get("tags") or []))
        price = ev.get("price_from")
        over = bool(price and self.budget and price > self.budget)
        slot_ok = slot_of(ev) in self.times
        aes = (int(ev.get("aesthetics") or 3) / 5.0) if self.aesthetics else 0.6
        kids_pen = 0.15 if (self.company == "с детьми" and not ev.get("audience_kids")) else 0.0
        f = 0.42 * cat + 0.28 * vf + 0.10 * aes + 0.10 * (1.0 if slot_ok else 0.4) + 0.10 * (0.2 if over else 1.0)
        f += 0.22 * self.whim(ev.get("slug") or "") - kids_pen
        return max(0.0, min(1.0, f))

    def skip_reason(self, ev: dict, rng: random.Random, available: list[str]) -> str | None:
        """Причина «мимо» по правде: что в событии действительно не устроило. None → «Без причины»."""
        price = ev.get("price_from")
        cands: list[tuple[str, float]] = []
        if price and self.budget and price > self.budget:
            cands.append(("дорого", 3.0))
        if self.taste_cats.get(ev.get("category") or "", 0.33) <= 0.34:
            cands.append(("не моё", 2.5))
        if slot_of(ev) not in self.times:
            cands.append(("не в это время", 1.5))
        if self.area == "центр" and ev.get("metro") and rng.random() < 0.25:
            cands.append(("далеко", 1.2))
        if self.company == "с детьми" and not ev.get("audience_kids"):
            cands.append(("не та компания", 2.0))
        cands.append(("уже был", 0.3))
        cands = [(r, w) for r, w in cands if r in available]
        if not cands or rng.random() < self.reason_none_p:
            return None
        total = sum(w for _, w in cands)
        x = rng.random() * total
        for r, w in cands:
            x -= w
            if x <= 0:
                return r
        return cands[-1][0]


def _pick(rng: random.Random, seq):
    return seq[rng.randrange(len(seq))]


def make_persona(seed: int, idx: int, archetype: str, n_users: int) -> Persona:
    a = ARCHETYPES[archetype]
    rng = random.Random(f"{seed}:{idx}")
    # пять главных ценностей: типичные для архетипа, иногда одна заменена
    top = list(a["values"])
    if rng.random() < 0.4:
        top[rng.randrange(5)] = _pick(rng, [v for v in VALUES if v not in top])
    rest = [v for v in VALUES if v not in top]
    important = [v for v in rest if (v in a["extra"] and rng.random() < 0.75) or rng.random() < 0.2]
    value_w = {v: 5 if v in top else 3 if v in important else 1 for v in VALUES}
    # интересы: истинные цели 0–3 по 19 категориям
    targets = {c: 1 for c in ALL_CATS}
    for c in a["mid"]:
        targets[c] = 2
    for c in a["high"]:
        targets[c] = 3
    for c in a["off"]:
        targets[c] = 0
    taste = {c: {0: 0.05, 1: 0.33, 2: 0.66, 3: 1.0}[t] for c, t in targets.items()}
    patience = a["patience"] * (0.8 + 0.4 * rng.random())
    max_taps = max(1, int(round(2 + patience * 11)))
    # онбординг: где бросит (по зоне риска каждого экрана)
    mult = a["hazard_mult"] * (0.6 + 0.8 * rng.random())
    abandon = None
    for st in STEPS:
        if rng.random() < min(0.6, STEP_HAZARD[st] * mult):
            abandon = st if st != "areas" else None
            break
    if abandon == "weights":
        sub = rng.randrange(0, 8)
    elif abandon == "values":
        sub = rng.randrange(0, 5)
    else:
        sub = 0
    misclick = _pick(rng, ["company", "budget", "aesthetics", "areas"]) if rng.random() < 0.12 else None
    if misclick == "areas":
        misclick = None                                     # шага «район» в продукте больше нет
    noise = _pick(rng, ["values", "interests", "company", "budget"]) if rng.random() < 0.08 else None
    # время онбординга: 85 % во вторник–четверг днём, остальные в пятницу–воскресенье
    if rng.random() < 0.88:
        offset = rng.uniform(8.0, 24.0 + 24.0 + 17.0)       # вт 08:00 … чт 17:00 UTC
    else:
        offset = rng.uniform(24.0 * 3 + 8.0, 24.0 * 5 + 21.0)  # пт 08:00 … вс 21:00 UTC
    eng = max(0.2, min(0.98, a["engagement"] * ENGAGEMENT_SCALE + rng.uniform(-0.12, 0.12)))
    lo = 1 if a["patience"] < 0.5 else 2
    view = (lo, lo + 2 + int(a["patience"] * 4))
    p_cmd = {"plan": 0.25 + 0.3 * eng, "profile": 0.10, "digest": 0.08, "help": 0.05, "start": 0.03}
    budget = _pick(rng, a["budget"])
    persona = Persona(
        idx=idx, user_id=FIRST_USER_ID + idx, name=NAMES[idx % len(NAMES)] + ("" if idx < len(NAMES) else str(idx // len(NAMES) + 1)),
        username=f"sim_user_{idx + 1:03d}", archetype=archetype, tz="Europe/Moscow",
        top_values=top, important=important, interest_targets=targets, max_interest_taps=max_taps,
        overselect=rng.random() < 0.10, company=_pick(rng, a["company"]), times=list(_pick(rng, a["times"])),
        budget=budget, aesthetics=rng.random() < a["aesthetics"], area=_pick(rng, a["area"]),
        note=_pick(rng, NOTES) if rng.random() < 0.3 else "", abandon_step=abandon, abandon_sub=sub,
        misclick_step=misclick, misclick_recovery="reset" if rng.random() < 0.4 else "continue", noise_step=noise,
        help_at_notes=False, onboard_offset_h=round(offset, 2), engagement=round(eng, 3),
        p_open_scale=round(0.85 + 0.3 * rng.random(), 3), view_range=view, decisive=a["decisive"],
        w_go_maybe_interest=tuple(a["w"]), p_rate=a["p_rate"], p_attend=0.85, rating_bias=a["rating_bias"],
        double_tap=0.04 if a["patience"] < 0.6 else 0.02,
        delay_profile=_pick(rng, ["evening", "evening", "next_day", "weekend"]), churn_thr=a["churn_thr"] + CHURN_SHIFT,
        blocks_on_churn=rng.random() < a["blocks"], p_cmd=p_cmd, delete_week=None, reset_week=None,
        reason_none_p=0.25, seed_key=f"{seed}:{idx}", taste_cats=taste, value_w=value_w)
    return persona


def generate(n_users: int = 50, seed: int = DEFAULT_SEED) -> list[Persona]:
    """n_users персон; для 50 — ровно набор из ARCHETYPES[*]['count']."""
    rng = random.Random(f"{seed}:archetypes")
    pool: list[str] = []
    for name, a in ARCHETYPES.items():
        pool += [name] * a["count"]
    rng.shuffle(pool)
    while len(pool) < n_users:               # больше 50 — добираем архетипы по кругу
        pool.append(pool[len(pool) % 50])
    personas = [make_persona(seed, i, pool[i], n_users) for i in range(n_users)]
    # особые случаи, детерминированно: смена часового пояса, /reset, /delete, «/help» в шаге заметки
    srng = random.Random(f"{seed}:special")
    order = list(range(n_users))
    srng.shuffle(order)
    ok = [i for i in order if personas[i].abandon_step is None]
    for k, i in enumerate(ok[:len(TZ_OVERRIDES)]):
        personas[i].tz = TZ_OVERRIDES[k]
    tail = ok[len(TZ_OVERRIDES):]
    for i in tail[:2]:
        personas[i].reset_week = 2
    for i in tail[2:4]:
        personas[i].delete_week = 3
    for i in tail[4:5]:
        personas[i].help_at_notes = True
    # поздний онбординг: суббота днём/вечером и воскресенье — первая подборка приходит, когда часть событий уже началась
    for i, off in zip(tail[5:9], (107.0, 113.0, 132.0, 137.0), strict=False):     # сб 11:00, сб 17:00, вс 12:00, вс 17:00 UTC
        personas[i].onboard_offset_h = off
    return personas


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


if __name__ == "__main__":
    from collections import Counter
    ps = generate()
    print(len(ps), Counter(p.archetype for p in ps))
    print(Counter(p.abandon_step for p in ps))
