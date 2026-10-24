"""Каркас социального графа симулятора (ТЗ-B): детерминизм, 2–5 друзей, половина вне сервиса, близкий, но иной архетип."""
from leisure.sim import personas as P
from leisure.sim import social as S

SEED = 20261024


def test_graph_shape_and_determinism():
    ps = P.generate(50, SEED)
    g1, g2 = S.build_graph(ps, SEED), S.build_graph(ps, SEED)
    arch = {p.idx: p.archetype for p in ps}
    assert [(k, [(f.idx, f.inside) for f in v]) for k, v in g1.items()] == [(k, [(f.idx, f.inside) for f in v]) for k, v in g2.items()]
    for p in ps:
        fr = g1[p.idx]
        assert 2 <= len(fr) <= 5
        out = [f for f in fr if not f.inside]
        assert len(out) == (len(fr) + 1) // 2
        for f in out:
            assert f.persona is not None and f.idx >= S.EXTERNAL_IDX0
            assert f.persona.archetype != arch[p.idx] and f.persona.archetype in S.NEIGHBORS[arch[p.idx]]
        assert all(f.idx != p.idx for f in fr)


def test_probabilities_are_bounded_and_monotonic():
    ps = P.generate(50, SEED)
    p = ps[0]
    assert 0 <= S.p_invite(p, 0.9, 0.9) <= 0.9 and S.p_invite(p, 0.9, 0.8) > S.p_invite(p, 0.1, 0.8)
    assert S.p_accept(0.9) > S.p_accept(0.3) and S.p_accept(0.8, going=False) < S.p_accept(0.8)
    assert S.p_share(5, 0.5) > S.p_share(4, 0.5) and 0 < S.p_take_onboarding(p) < 1
