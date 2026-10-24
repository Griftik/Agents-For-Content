"""Золотой тест: ядро даёт те же числа, что JS-прототип «Уикенд в Москве».

Эталон (fixtures/prototype_reference.json) получен прогоном score()/affinity()/learningBonus()/recommend()
прототипа в Node по 177 событиям для трёх профилей (fixtures/prototype_cases.json).

Единственная правка в JS-эталоне относительно артефакта: парсер времени не принимает даты («23.10 — 20:00»)
за время начала — та же семантика, что в core/timeutil.time_tokens. Это меняет одно событие seed.
"""
import json

import pytest

from leisure.core.affinity import compute_affinity, learning_bonus
from leisure.core.config import scoring_config
from leisure.core.recommend import build_digest
from leisure.core.scoring import score
from leisure.core.timeutil import is_free, slot_of

from .conftest import FIXTURES, WEEKEND

CASES = json.loads((FIXTURES / "prototype_cases.json").read_text(encoding="utf-8"))
REF = json.loads((FIXTURES / "prototype_reference.json").read_text(encoding="utf-8"))
EVENTS = json.loads((FIXTURES / "prototype_events.json").read_text(encoding="utf-8"))
BY_ID = {e["id"]: e for e in EVENTS}


def _decisions(case):
    return [{"event_id": k, **v} for k, v in case["decisions"].items()]


@pytest.mark.parametrize("name", list(CASES))
def test_scores_match_prototype(name):
    cfg = scoring_config()
    case, ref = CASES[name], REF[name]
    aff = compute_affinity(_decisions(case), cfg, events_by_id=BY_ID)
    mismatches = []
    for ev in EVENTS:
        r = score(ev, case["profile"], aff, cfg)
        j = ref["scores"][ev["id"]]
        if r.score != j["s"] or [w.text for w in r.why] != j["why"] or abs(learning_bonus(ev, aff, cfg) - j["lb"]) > 1e-9:
            mismatches.append((ev["id"], r.score, j["s"]))
        assert slot_of(ev) == j["slot"], ev["id"]
        assert is_free(ev) == j["free"], ev["id"]
    assert mismatches == []


@pytest.mark.parametrize("name", list(CASES))
def test_affinity_matches_prototype(name):
    cfg = scoring_config()
    case, ref = CASES[name], REF[name]
    aff = compute_affinity(_decisions(case), cfg, events_by_id=BY_ID)
    assert aff["n"] == ref["aff"]["n"]
    assert set(aff["tag"]) == set(ref["aff"]["tag"])
    for k, v in ref["aff"]["tag"].items():
        assert aff["tag"][k] == pytest.approx(v)
    for k, v in ref["aff"]["cat"].items():
        assert aff["cat"][k] == pytest.approx(v)


@pytest.mark.parametrize("name", list(CASES))
def test_recommendation_matches_prototype(name):
    case, ref = CASES[name], REF[name]
    d = build_digest(EVENTS, case["profile"], _decisions(case), WEEKEND)
    got = [(p.day, p.slot, p.event["id"] if p.event else None, p.chosen) for p in d.slots]
    want = [(r["day"], r["slot"], r["id"], r["chosen"]) for r in ref["reco"]]
    assert got == want
