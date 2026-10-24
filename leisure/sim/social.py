"""Социальный граф симуляции (ТЗ-B, docs/GROWTH.md): друзья, вероятности приглашений и принятий.

Каркас без обработчиков: граф и вероятности чистые и детерминированные от seed. Путь пригласившего и приглашённого идёт через
API приглашений (GROWTH.md §6: POST /api/invites, GET /api/invites/{code}, POST /api/invites/{code}/accept, PUT /api/profile),
а не через экраны бота; подключается, когда бэкенд сдаст ТЗ-8.

Допущения (меняются здесь, не в коде продукта):
- у каждой персоны 2–5 друзей, половина из них (округление вверх) вне сервиса: это новые персоны с архетипом, близким к
  архетипу пригласившего, но не совпадающим с ним;
- общительность зависит от архетипа и индивидуального сдвига; после «иду» персона зовёт друга с вероятностью от общительности,
  вовлечённости и того, насколько событие подходит именно другу;
- друг принимает приглашение с вероятностью от скоринга события под его скрытый вкус (Persona.fit);
- приглашённый без профиля после «Вы идёте вместе» соглашается на онбординг («Давай») с вероятностью от терпения/вовлечённости;
- момент рекомендации после оценки 4–5: «Поделиться» с вероятностью от оценки и общительности.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .personas import ARCHETYPES, FIRST_USER_ID, Persona, make_persona

# близкие по духу архетипы (друг пригласившего: похож, но не такой же)
NEIGHBORS: dict[str, list[str]] = {
    "эстет": ["интеллектуал", "мастер", "тусовщик"],
    "нетворкер": ["тусовщик", "занятой", "интеллектуал"],
    "интеллектуал": ["эстет", "нетворкер", "мастер"],
    "родитель": ["занятой", "экономный", "мастер"],
    "спортсмен": ["тусовщик", "занятой", "экономный"],
    "тусовщик": ["нетворкер", "эстет", "спортсмен"],
    "экономный": ["родитель", "спортсмен", "занятой"],
    "занятой": ["нетворкер", "родитель", "экономный"],
    "мастер": ["эстет", "интеллектуал", "родитель"],
}
SOCIABILITY: dict[str, float] = {"нетворкер": 0.85, "тусовщик": 0.8, "эстет": 0.5, "интеллектуал": 0.45, "родитель": 0.5,
                                 "спортсмен": 0.65, "экономный": 0.4, "занятой": 0.3, "мастер": 0.4}
EXTERNAL_IDX0 = 1000          # индексы новых персон (вне сервиса): 1000 + 10 * индекс пригласившего + k


@dataclass
class Friend:
    idx: int                   # индекс персоны (для внешних >= EXTERNAL_IDX0)
    inside: bool               # уже в сервисе (одна из 50 персон) или нет
    persona: Persona | None = None


def sociability(p: Persona, seed: int) -> float:
    """0..1: как охотно человек зовёт друзей. Архетип + индивидуальный сдвиг (отдельный поток от остальных розыгрышей)."""
    r = random.Random(f"{seed}:{p.idx}:social")
    return max(0.05, min(0.98, SOCIABILITY[p.archetype] + r.uniform(-0.15, 0.15)))


def build_graph(personas: list[Persona], seed: int, n_users: int | None = None) -> dict[int, list[Friend]]:
    """Граф дружбы: у каждой персоны 2–5 друзей, половина вне сервиса. Дружба внутри — односторонняя запись (список друзей
    персоны), чтобы граф не зависел от порядка обхода. Внешние персоны создаются тем же `make_persona`, со своим индексом."""
    n = n_users or len(personas)
    by_arch: dict[str, list[Persona]] = {}
    for p in personas:
        by_arch.setdefault(p.archetype, []).append(p)
    graph: dict[int, list[Friend]] = {}
    for p in personas:
        r = random.Random(f"{seed}:{p.idx}:graph")
        k = r.randint(2, 5)
        outside = (k + 1) // 2
        inside = k - outside
        friends: list[Friend] = []
        pool = [q for q in personas if q.idx != p.idx]
        r.shuffle(pool)
        pool.sort(key=lambda q: 0 if q.archetype in NEIGHBORS[p.archetype] else 1)      # внутри сервиса тоже тянемся к близким
        friends += [Friend(q.idx, True, q) for q in pool[:inside]]
        for j in range(outside):
            arch = r.choice(NEIGHBORS[p.archetype])
            idx = EXTERNAL_IDX0 + 10 * p.idx + j
            friends.append(Friend(idx, False, make_persona(seed, idx, arch, n)))
        graph[p.idx] = friends
    return graph


def user_id_of(f: Friend) -> int:
    return FIRST_USER_ID + f.idx


def p_invite(p: Persona, soc: float, friend_fit: float) -> float:
    """После «иду» зовёт друга: общительность и вовлечённость, плюс подходит ли событие другу (его скрытый вкус)."""
    return max(0.0, min(0.9, 0.02 + 0.22 * soc + 0.08 * p.engagement + 0.2 * (friend_fit - 0.5)))


def p_accept(friend_fit: float, going: bool = True) -> float:
    """Друг принимает приглашение: вероятность растёт с тем, насколько событие подходит его вкусу (Persona.fit)."""
    base = 0.08 + 0.85 * friend_fit ** 1.5
    return max(0.02, min(0.95, base if going else base * 0.6))


def p_take_onboarding(friend: Persona) -> float:
    """«Давай» на предложение онбординга после «Вы идёте вместе»; «Потом» — повтор один раз, второй раз соглашаются реже."""
    return max(0.1, min(0.9, 0.2 + 0.5 * friend.engagement + 0.2 * (friend.max_interest_taps / 13)))


def p_share(rating: int, soc: float) -> float:
    """Момент рекомендации после оценки 4–5: нажать «Поделиться»."""
    return max(0.0, min(0.6, (0.05 if rating == 4 else 0.12) + 0.2 * soc))


def friend_pick(r: random.Random, friends: list[Friend], fits: dict[int, float]) -> Friend | None:
    """Кого зовёт: друзей, которым событие подходит больше, чаще (взвешенный выбор по fit^2)."""
    if not friends:
        return None
    w = [max(0.01, fits.get(f.idx, 0.3)) ** 2 for f in friends]
    return r.choices(friends, w)[0]


__all__ = ["ARCHETYPES", "Friend", "build_graph", "friend_pick", "p_accept", "p_invite", "p_share", "p_take_onboarding", "sociability", "user_id_of"]
