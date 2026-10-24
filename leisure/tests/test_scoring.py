"""10 эталонных пар (событие, профиль) с ожидаемым диапазоном (п. 6.4 спеки)."""
from leisure.core.scoring import score, trim_why, Why
from leisure.core.catalog import default_profile

from .conftest import make_event

WINZAVOD = "winzavod-new-season-oct2026"      # выставка, эстетика 5, новизна 5, бесплатно, 30+
PROBKA = "probka-wines-malaya-nikitskaya"     # место, от 1 800 ₽
ONGON = "ges2-pocket-ongon-oct24"             # своими руками, 13:00–15:00, бесплатно


def why_texts(r):
    return [w.text for w in r.why]


# 1. Выставка с эстетикой 5/5 и новизной 5 для профиля-эстета: высокий балл и обе причины.
def test_pair_1_aesthetic_exhibition_default_profile(by_slug, profile):
    r = score(by_slug[WINZAVOD], profile)
    assert 75 <= r.score <= 85
    assert "эстетика 5/5" in why_texts(r) and "нетривиально" in why_texts(r)
    assert r.why[0].text in ("Творчество", "Эстетика", "Новизна")


# 2. Та же выставка при интересе 3/3 — на 9 выше и первая причина «категория · 3/3».
def test_pair_2_interest_three(by_slug, profile):
    base = score(by_slug[WINZAVOD], profile).score
    profile["interests"]["Современное искусство"] = 3
    r = score(by_slug[WINZAVOD], profile)
    assert r.score == base + 9
    assert r.why[0].text == "Современное искусство · 3/3"


# 3. Интерес выключен: итог ×0.35 и причина «интерес выключен» первой.
def test_pair_3_interest_off(by_slug, profile):
    profile["interests"]["Современное искусство"] = 0
    r = score(by_slug[WINZAVOD], profile)
    assert 15 <= r.score <= 30
    assert r.why[0] == Why("интерес выключен", "neg")


# 4. Бюджет: событие дороже бюджета теряет 12 и получает негативную причину.
def test_pair_4_over_budget(by_slug, profile):
    free_budget = score(by_slug[PROBKA], profile).score
    profile["params"]["budget"] = 1000
    r = score(by_slug[PROBKA], profile)
    assert r.score == free_budget - 12
    assert Why("выше бюджета", "neg") in r.why


# 5. Аудитория: событие «не для 30+» штрафуется на 12 только если в профиле adults30.
def test_pair_5_audience_30plus(profile):
    ev = make_event(audience_30plus=False)
    strict = score(ev, profile).score
    profile["params"]["adults30"] = False
    assert score(ev, profile).score == strict + 12
    assert score(make_event(audience_30plus=True), profile).score == score(ev, profile).score + 4


# 6. «Нужно проверить» — минус 4.
def test_pair_6_confidence(profile):
    ok = score(make_event(confidence="подтверждено"), profile).score
    assert score(make_event(confidence="нужно проверить"), profile).score == ok - 4


# 7. Эстетика обязательна: вес 4 вместо 2.5 — для события с aesthetics 5 разница 7.5.
def test_pair_7_aesthetics_required(profile):
    ev = make_event(aesthetics=5)
    req = score(ev, profile).raw
    profile["params"]["aesthetics"] = False
    assert req - score(ev, profile).raw == 7.5


# 8. Любимое время: совпадение слота даёт +3.
def test_pair_8_time_match(profile):
    ev = make_event(time_text="19:30")  # вечер
    profile["params"]["times"] = ["вечер"]
    with_time = score(ev, profile).score
    profile["params"]["times"] = []
    assert with_time == score(ev, profile).score + 3


# 9. Обучение: три «иду» на похожие события дают бонус и причину; три «мимо» — штраф.
def test_pair_9_learning(profile):
    liked = [{"event_id": f"j{i}", "status": "иду", "event_category": "Джаз", "event_tags": ["музыка", "камерно"]} for i in range(3)]
    from leisure.core.affinity import compute_affinity
    aff = compute_affinity(liked)
    ev = make_event(category="Джаз", tags=["музыка", "камерно", "вечер"])
    r = score(ev, profile, aff)
    assert r.score >= score(ev, profile).score + 3
    assert Why("похоже на то, что ты выбирал", "learn") in r.why
    disliked = [{"event_id": f"p{i}", "status": "мимо", "reason": "не моё", "event_category": "Вечеринки", "event_tags": ["шумно", "музыка"]} for i in range(3)]
    aff2 = compute_affinity(disliked)
    party = make_event(category="Вечеринки", tags=["шумно", "музыка", "ночь"])
    r2 = score(party, profile, aff2)
    assert Why("похоже на отклонённое", "neg") in r2.why
    assert r2.score < score(party, profile).score


# 10. Событие без ценностных тегов: формула даёт ровно 57 для профиля по умолчанию (интерес к «Кино» = 2).
#     18 (интерес 2) + 15 (пустое среднее 2.5×6) + 12 (эстетика 3×4) + 4.8 (новелти 3×4/5×2) + 4 (30+) + 3 (время) = 56.8
def test_pair_10_formula_pinned(profile):
    ev = make_event(category="Кино", tags=[], time_text="14:00", aesthetics=3, novelty=3)
    r = score(ev, profile)
    assert r.raw == 56.8 and r.score == 57
    assert r.why == []


def test_score_clamped_0_100(profile):
    for v in profile["values"]:
        profile["values"][v] = 5
    for c in profile["interests"]:
        profile["interests"][c] = 3
    ev = make_event(aesthetics=5, novelty=5, tags=["творчество", "эстетика", "новизна", "дружба", "развитие", "вечер"])
    assert score(ev, profile).score == 94  # 27 + 30 + 20 + 10 + 4 + 3 — максимум без обучения
    aff = {"tag": {"творчество": 10.0}, "cat": {"Концерты": 10.0}, "n": 5}
    assert score(ev, profile, aff).score == 100  # +12 обучения → обрезка до 100
    for v in profile["values"]:
        profile["values"][v] = 0
    profile["params"]["adults30"] = True
    assert score(make_event(audience_30plus=False, aesthetics=1, novelty=1, tags=[], confidence="нужно проверить"), profile).score >= 0


def test_promotion_rules(profile):
    ev = make_event(aesthetics=5, promoted_until="2999-01-01T00:00:00+00:00")
    r = score(ev, profile)
    assert r.promoted and r.score == min(100, r.base + 8) and Why("партнёр") in r.why
    profile["interests"]["Концерты"] = 0  # базовый балл падает ниже 55 — продвижение не действует
    r2 = score(ev, profile)
    assert r2.base < 55 and not r2.promoted and r2.score == r2.base


def test_trim_why_keeps_negatives():
    why = [Why("a"), Why("b"), Why("c"), Why("d"), Why("выше бюджета", "neg"), Why("e")]
    t = trim_why(why, 4)
    assert len(t) == 4 and Why("выше бюджета", "neg") in t and t[0] == Why("a")


def test_default_profile_is_copy():
    p = default_profile()
    p["values"]["Творчество"] = 0
    assert default_profile()["values"]["Творчество"] == 5
