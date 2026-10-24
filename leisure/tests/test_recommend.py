from leisure.core.recommend import build_digest, kind_bonus, recommend_slots
from leisure.core.scoring import score_events
from leisure.core.timeutil import is_horizon, reco_slot, weekend_days

from .conftest import make_event


def test_kind_bonus():
    assert kind_bonus({"kind": "событие"}) == 6 and kind_bonus({"kind": "выставка"}) == 3 and kind_bonus({"kind": "место"}) == 0


def test_five_slots_filled_from_seed(seed_events, profile, weekend):
    d = build_digest(seed_events, profile, [], weekend)
    assert [(p.day, p.slot) for p in d.slots] == [
        (weekend[0], "вечер"), (weekend[1], "день"), (weekend[1], "вечер"), (weekend[2], "день"), (weekend[2], "вечер")]
    # seed собран утром 24.10: пятница 23.10 в нём уже отсечена, поэтому слот «пт вечер» пуст, остальные четыре заполнены
    filled = [p for p in d.slots if p.event]
    assert len(filled) == 4 and d.slots[0].event is None
    ids = [p.event["id"] for p in filled]
    assert len(set(ids)) == 4
    for p in filled:
        assert p.day in weekend_days(p.event, weekend) and reco_slot(p.event) == p.slot and not p.chosen
        assert p.result is not None and p.result.score > 0
    items = d.items(why_limit=4)
    assert len(items) >= 4 and all(len(it["why"]) <= 4 for it in items)


def test_skip_and_pin(seed_events, profile, weekend):
    first = build_digest(seed_events, profile, [], weekend)
    top = first.slots[1].event
    # «мимо» — событие больше не заполняет слот
    d = build_digest(seed_events, profile, [{"event_id": top["id"], "status": "мимо", "reason": "не моё",
                                            "event_category": top["category"], "event_tags": top["tags"]}], weekend)
    assert d.slots[1].event["id"] != top["id"]
    # «иду» с днём — событие закреплено в своём слоте
    d2 = build_digest(seed_events, profile, [{"event_id": top["id"], "status": "иду", "day": weekend[1],
                                             "event_category": top["category"], "event_tags": top["tags"]}], weekend)
    assert d2.slots[1].chosen and d2.slots[1].event["id"] == top["id"]
    # «интересно» и «пропуск» тоже не заполняют слот
    for st in ("интересно", "пропуск"):
        d3 = build_digest(seed_events, profile, [{"event_id": top["id"], "status": st, "event_category": top["category"], "event_tags": top["tags"]}], weekend)
        assert d3.slots[1].event["id"] != top["id"]


def test_recently_shown_excluded(seed_events, profile, weekend):
    first = build_digest(seed_events, profile, [], weekend)
    shown = first.event_ids()
    second = build_digest(seed_events, profile, [], weekend, recently_shown=shown)
    assert not set(second.event_ids()) & set(shown)


def test_interest_zero_never_recommended(seed_events, profile, weekend):
    for c in profile["interests"]:
        profile["interests"][c] = 0
    profile["interests"]["Джаз"] = 2
    d = build_digest(seed_events, profile, [], weekend)
    assert all(p.event is None or p.event["category"] == "Джаз" for p in d.slots)


def test_horizon_picks(seed_events, profile, weekend):
    d = build_digest(seed_events, profile, [], weekend)
    assert len(d.horizon) <= 2
    for ev, r in d.horizon:
        assert is_horizon(ev, weekend) and ev["url"] and r.score >= 70
    weekend_ids = {p.event["id"] for p in d.slots if p.event}
    assert not weekend_ids & {ev["id"] for ev, _ in d.horizon}


def test_at_most_one_promoted(profile, weekend):
    evs = [make_event(id=f"e{i}", slug=f"e{i}", dates=[weekend[1]], time_text="19:00", aesthetics=5,
                      promoted_until="2999-01-01T00:00:00+00:00") for i in range(3)]
    evs.append(make_event(id="plain", slug="plain", dates=[weekend[2]], time_text="19:00", aesthetics=5))
    d = build_digest(evs, profile, [], weekend)
    picked = [p for p in d.slots if p.event]
    assert sum(1 for p in picked if p.result.promoted) == 1
    assert {p.event["id"] for p in picked} >= {"plain"}


def test_recommend_slots_direct(profile, weekend):
    evs = [make_event(id="a", dates=[weekend[0]], time_text="20:00", kind="место"),
           make_event(id="b", dates=[weekend[0]], time_text="20:00", kind="событие")]
    scores = score_events(evs, profile)
    assert scores["a"].score == scores["b"].score
    picks = recommend_slots(evs, scores, profile, {}, weekend)
    assert picks[0].event["id"] == "b"  # kindBonus: событие +6 против места 0
    assert all(p.event is None for p in picks[1:])


def test_pinned_event_not_duplicated(profile, weekend):
    """«Иду» на воскресенье: событие с двумя датами закрепляется один раз, а не предлагается ещё и в субботу."""
    ev = make_event(id="x", slug="x", dates=[weekend[1], weekend[2]], time_text="19:00")
    other = make_event(id="y", slug="y", dates=[weekend[1]], time_text="19:00", aesthetics=1)
    d = build_digest([ev, other], profile, [{"event_id": "x", "status": "иду", "day": weekend[2],
                                            "event_category": ev["category"], "event_tags": ev["tags"]}], weekend)
    ids = [(p.slot, p.day, p.event["id"] if p.event else None, p.chosen) for p in d.slots]
    assert ("вечер", weekend[2], "x", True) in ids
    assert ("вечер", weekend[1], "y", False) in ids
    assert [i for i in ids if i[2] == "x"] == [("вечер", weekend[2], "x", True)]


def test_items_keep_negative_reasons(profile, weekend):
    from leisure.core.scoring import Why
    ev = make_event(id="x", slug="x", dates=[weekend[1]], time_text="19:00", price_from=9000)
    profile["params"]["budget"] = 1000
    d = build_digest([ev], profile, [], weekend)
    item = [it for it in d.items(why_limit=1) if it["event_id"] == "x"][0]
    assert any(w["c"] == "neg" for w in item["why"])
