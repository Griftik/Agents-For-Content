import pytest

from leisure.core.affinity import compute_affinity, decision_weight, describe_affinity, describe_affinity_text, learning_bonus


def d(status, reason="", rating=0, cat="Джаз", tags=("музыка", "камерно")):
    return {"event_id": "x", "status": status, "reason": reason, "rating": rating, "event_category": cat, "event_tags": list(tags)}


@pytest.mark.parametrize("status,reason,rating,w", [
    ("иду", "", 0, 1.0), ("интересно", "", 0, 0.9), ("может", "", 0, 0.4), ("мимо", "", 0, -1.0),
    ("мимо", "не моё", 0, -1.0), ("мимо", "не в это время", 0, -0.2), ("мимо", "далеко", 0, -0.2),
    ("мимо", "уже был", 0, 0.5), ("мимо", "дорого", 0, -0.1), ("мимо", "не та компания", 0, -0.3),
    ("иду", "", 5, 2.5), ("иду", "", 1, -0.5), ("иду", "", 3, 1.0), ("пропуск", "не хочется", 0, None),
])
def test_decision_weights(status, reason, rating, w):
    got = decision_weight(d(status, reason, rating))
    assert got == (pytest.approx(w) if w is not None else None)


def test_affinity_accumulates_and_skips_no_signal():
    aff = compute_affinity([d("иду"), d("мимо", "дорого", cat="Кино", tags=("визуальное",)), d("пропуск")])
    assert aff["n"] == 2
    assert aff["tag"] == pytest.approx({"музыка": 1.0, "камерно": 1.0, "визуальное": -0.1})
    assert aff["cat"] == pytest.approx({"Джаз": 1.0, "Кино": -0.1})


def test_snapshot_outlives_event():
    """Событие удалено из базы — решение учится по снимку category/tags."""
    aff = compute_affinity([d("иду")], events_by_id={})
    assert aff["cat"]["Джаз"] == 1.0


def test_live_event_preferred_over_snapshot():
    live = {"x": {"category": "Кино", "tags": ["визуальное"]}}
    aff = compute_affinity([d("иду")], events_by_id=live)
    assert aff["cat"] == {"Кино": 1.0} and aff["tag"] == {"визуальное": 1.0}


def test_learning_bonus_clamped():
    aff = compute_affinity([d("иду", rating=5)] * 10)
    assert learning_bonus({"category": "Джаз", "tags": ["музыка"]}, aff) == 12
    aff2 = compute_affinity([d("мимо")] * 10)
    assert learning_bonus({"category": "Джаз", "tags": ["музыка"]}, aff2) == -12
    assert learning_bonus({"category": "Джаз", "tags": ["музыка"]}, None) == 0
    assert learning_bonus({"category": "Театр", "tags": ["история"]}, aff) == 0


def test_learning_bonus_formula():
    aff = {"tag": {"музыка": 1.0, "камерно": 0.0}, "cat": {"Джаз": 1.0}, "n": 1}
    # avg(1.0, 0.0) × 3 + 1.0 × 2.5 = 4.0
    assert learning_bonus({"category": "Джаз", "tags": ["музыка", "камерно", "вечер"]}, aff) == 4.0


def test_describe_affinity():
    decs = [d("иду"), d("иду"), d("мимо", "далеко", cat="Вечеринки", tags=("шумно",)), d("мимо", "далеко", cat="Вечеринки", tags=("шумно",))]
    aff = compute_affinity(decs)
    info = describe_affinity(aff, decs)
    assert info["likes"][0] in ("музыка", "камерно", "Джаз") and "шумно" in info["dislikes"]
    assert info["reasons"] == {"далеко": 2}
    text = describe_affinity_text(aff, decs)
    assert "чаще выбираешь" in text and "далеко (2)" in text
    assert "мало решений" in describe_affinity_text({"tag": {}, "cat": {}, "n": 0})
