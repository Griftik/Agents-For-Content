"""Метрики и отчёт по результатам прогона: REPORT.md (для людей) и report.json (для сравнения прогонов).

Все числа считаются из словаря результатов runner.run_simulation(); модуль не ходит ни в БД, ни в сеть.
В report.json блок "volatile" (длительность, время задач) меняется от запуска к запуску, остальное — воспроизводимо.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

STEP_ORDER = ["consent", "values", "interests"]
STEP_RU = {
    "consent": "согласие и политика", "values": "Шаг 1 из 2 · пять ценностей из 19", "interests": "Шаг 2 из 2 · интересы",
}
MIN_ONBOARDING_TAPS = 9    # онбординг v2: /start, «Принять и начать», 5 ценностей, «Дальше», «Показать подборку»
TARGET_TAPS = 12           # web/FLOW-ONBOARDING.md, раздел 1: «не больше 12 нажатий у типичного пользователя; 9 при "ничего не меняю"»
SEND_RATE = 25             # сообщений в секунду (worker/send.py)
ANSWER_RU = {"values": "ценности", "company": "компания", "times": "время", "budget": "бюджет", "aesthetics": "эстетика", "notes": "заметка"}
STATUS_RU = {"ok": "достигнута", "fail": "не достигнута", "na": "нельзя оценить"}


# ───────────────────────── мелкие помощники ─────────────────────────
def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if 11 <= n % 100 <= 19:
        return many
    r = n % 10
    return one if r == 1 else few if 2 <= r <= 4 else many


def cnt(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural(n, one, few, many)}"


def ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def pct(x: float | None, d: int = 0) -> str:
    return "н/д" if x is None else f"{x * 100:.{d}f} %".replace(".", ",")


def num(x: float | None, d: int = 1) -> str:
    return "н/д" if x is None else f"{x:.{d}f}".replace(".", ",")


def med(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def ci(k: int, n: int) -> str:
    w = wilson(k, n)
    return "" if w is None else f"95 % ДИ {w[0] * 100:.0f}–{w[1] * 100:.0f} %"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def fcount(d: dict, code: str) -> int:
    return int(d["findings"].get(code, {}).get("count", 0))


def fusers(d: dict, code: str) -> int:
    return int(d["findings"].get(code, {}).get("users", 0))


def fex(d: dict, code: str, n: int = 2) -> list[str]:
    return list(d["findings"].get(code, {}).get("examples", []))[:n]


# ───────────────────────── метрики ─────────────────────────
def build_metrics(d: dict) -> dict:
    P, D, T, C = d["personas"], d["digests"], d["decisions"], d["commands"]
    weeks = int(d["meta"]["weeks"])
    m: dict = {}
    started = len(P)
    done = [p for p in P if p["completed"]]
    alive = [p for p in done if p["status"] != "deleted"]

    # ── онбординг и воронка ──
    def reached(p: dict) -> int:
        if p["completed"]:
            return len(STEP_ORDER)
        a = p.get("abandoned_at") or (p.get("stuck") or "").split(":")[0]
        return STEP_ORDER.index(a) + 1 if a in STEP_ORDER else 1

    funnel = []
    for i, st in enumerate(STEP_ORDER):
        r = sum(1 for p in P if reached(p) >= i + 1)
        left = sum(1 for p in P if not p["completed"] and reached(p) == i + 1)
        funnel.append({"step": st, "reached": r, "left": left})
    taps = [p["onboarding_taps"] for p in done if p["onboarding_taps"] is not None]
    clean = [p["onboarding_taps"] for p in done if p["onboarding_taps"] is not None and not p["redo"] and not p["misclick"]]
    step_means: dict[str, float] = {}
    for st in STEP_ORDER:
        vals = [p["steps_taps"].get(st, 0) for p in done if p.get("steps_taps")]
        step_means[st] = statistics.mean(vals) if vals else 0.0
    edits = [p["interest_edits"] for p in done if p.get("interest_edits") is not None]
    refiners = [p for p in done if p.get("refine_ops") is not None]
    no_edit = [p["onboarding_taps"] for p in done if p.get("interest_edits") == 0 and p["onboarding_taps"] is not None]
    m["refine"] = {"personas_with_menu": sum(1 for p in done if p.get("refine")), "opened": len(refiners),
                   "taps_median": med([p["refine_taps"] for p in refiners if p.get("refine_taps")]),
                   "taps_max": max((p["refine_taps"] for p in refiners if p.get("refine_taps")), default=None),
                   "rebuilt": sum(1 for p in refiners if p.get("refine_rebuilt")),
                   "ops": dict(Counter(op for p in refiners for op in (p["refine_ops"] or []))),
                   "used_all_screen": sum(1 for p in done if p.get("used_all_screen")),
                   "all_taps_median": med([p["onboarding_taps"] + (p.get("refine_taps") or 0) for p in done if p["onboarding_taps"] is not None])}
    m["onboarding"] = {
        "no_interest_edit_median": med(no_edit), "no_interest_edit_n": len(no_edit), "taps_le_target": sum(1 for t in taps if t <= TARGET_TAPS),
        "started": started, "completed": len(done), "funnel": funnel, "taps_min": min(taps) if taps else None,
        "taps_median": med(taps), "taps_max": max(taps) if taps else None, "taps_mean": statistics.mean(taps) if taps else None,
        "taps_clean_median": med(clean), "taps_clean_min": min(clean) if clean else None, "taps_clean_max": max(clean) if clean else None,
        "step_means": step_means, "theoretical_min": MIN_ONBOARDING_TAPS, "interest_edits_median": med(edits),
        "interest_edits_max": max(edits) if edits else None,
        "interest_share_of_taps": ratio(step_means.get("interests", 0), statistics.mean(taps)) if taps else None,
        "weights_share_of_taps": ratio(step_means.get("weights", 0), statistics.mean(taps)) if taps else None,
        "prefill": prefill_stats(P),
        "screens": d.get("onboarding_screens", []),
        "interest_buttons": next((p["interest_buttons"] for p in P if p.get("interest_buttons")), None),
        "interest_rows": next((p["interest_rows"] for p in P if p.get("interest_rows")), None),
        "weight_prompts": next((p["weight_prompts"] for p in P if p.get("weight_prompts")), None),
        "back_screens": sum(1 for p in P for v in (p.get("screens_back") or {}).values() if v),
        "all_screens_checked": sum(len(p.get("screens_back") or {}) for p in P),
    }
    m["activation"] = ratio(len(done), started)

    # ── подборки ──
    sent = [x for x in D if x["origin"] in ("first", "weekly", "reset")]
    by_week: dict[int, dict] = {}
    for w in range(weeks + 1):
        ds = [x for x in sent if x["week"] == w]
        if not ds:
            by_week[w] = {"digests": 0}
            continue
        by_week[w] = {
            "digests": len(ds), "cards": statistics.mean(x["cards"] for x in ds), "slots": statistics.mean(x["slot_cards"] for x in ds),
            "empty": statistics.mean(max(0, 5 - x["slot_cards"]) for x in ds), "horizon": statistics.mean(x["horizon_cards"] for x in ds),
            "opened": sum(1 for x in ds if x["opened"]), "reacted": sum(1 for x in ds if x["decisions"] > 0),
            "go": sum(1 for x in ds if x["go"] > 0),
        }
    reacted = sum(1 for x in sent if x["decisions"] > 0)
    m["reaction"] = ratio(reacted, len(sent))
    m["digests"] = {"sent": len(sent), "reacted": reacted, "opened": sum(1 for x in sent if x["opened"]), "by_week": by_week,
                    "first": sum(1 for x in sent if x["origin"] == "first"), "manual": sum(1 for x in D if x["origin"] == "manual"),
                    "avg_cards": statistics.mean(x["cards"] for x in sent) if sent else None,
                    "avg_empty": statistics.mean(max(0, 5 - x["slot_cards"]) for x in sent) if sent else None,
                    "with_empty": sum(1 for x in sent if x["slot_cards"] < 5), "multi_day_cards": sum(x.get("multi_day_cards", 0) for x in sent),
                    "total_cards": sum(x["cards"] for x in sent), "already_started": sum(x.get("already_started", 0) for x in D),
                    "resent_no_status": sum(x.get("resent_no_status", 0) for x in D),
                    "messy_time": sum(x.get("messy_time", 0) for x in D), "all_cards": sum(x["cards"] for x in D),
                    "plan_messy_lines": sum(p.get("messy_lines", 0) for p in d["plan_pushes"]),
                    "plan_lines": sum(p.get("lines", 0) for p in d["plan_pushes"]),
                    "no_interest_button": all(not x.get("has_interest_button") for x in D) if D else None}
    # тишина: человек был в базе, а подборки в эту неделю не получил
    silent = total_weeks = 0
    for p in alive:
        if p["blocked"]:
            continue                                   # заблокировавшим подборка не доходит по другой причине (см. дефект про блокировку)
        for c in range(1, weeks + 1):
            total_weeks += 1
            silent += int(c not in p["digest_cycles"])
    alive_ids = {p["user_id"] for p in alive if not p["blocked"]}
    nothing = {(u, w) for u, w in d.get("empty_sends", []) if u in alive_ids}
    m["silent"] = {"user_weeks": total_weeks, "silent": silent, "share": ratio(silent, total_weeks), "logged_nothing": len(nothing),
                   "empty_notices": len(d.get("empty_notices", []))}

    # ── решения ──
    dec = [t for t in T if t["kind"] == "decision"]
    cnt = Counter(t["status"] for t in dec)
    reasons = Counter(t["reason"] for t in T if t["kind"] == "reason")
    n_skip = cnt.get("мимо", 0)
    with_reason = sum(v for k, v in reasons.items() if k)
    m["decisions"] = {"total": len(dec), "by_status": dict(cnt), "reasons": dict(reasons), "skip_total": n_skip,
                      "skip_with_reason": with_reason, "skip_no_reason_button": reasons.get("", 0),
                      "skip_unanswered": fcount(d, "reason_not_answered"),
                      "wanted_interest": sum(1 for t in T if t["kind"] == "wanted_interest"),
                      "wanted_interest_users": len({t["u"] for t in T if t["kind"] == "wanted_interest"})}

    # ── «иду»: у скольких и после скольких нажатий ──
    first_go = [p["first_go_taps"] for p in done if p["first_go_taps"] is not None]
    after_onb = [p["first_go_taps"] - p["onboarding_taps"] for p in done if p["first_go_taps"] is not None and p["onboarding_taps"] is not None]
    go_users = {p["user_id"] for p in done if p["first_go_taps"] is not None}
    m["first_go"] = {"users": len(go_users), "of": len(done), "taps_min": min(first_go) if first_go else None,
                     "taps_median": med(first_go), "taps_max": max(first_go) if first_go else None,
                     "after_onb_median": med(after_onb), "after_onb_min": min(after_onb) if after_onb else None,
                     "in_first_digest": len({t["u"] for t in dec if t["status"] == "иду" and t.get("origin") == "first"})}
    # ── «иду» в неделю, план ──
    plan_rows = []
    go_by_week = []
    for w in range(weeks + 1):
        gu = {t["u"] for t in dec if t["status"] == "иду" and t.get("week") == w and t.get("origin") in ("first", "weekly", "reset", "manual")}
        go_by_week.append(len(gu))
        plan_rows.append(ratio(len(gu), len(done)))
    plan_users = {p["u"] for p in d["plan_pushes"]}
    cmd_plan_users = {c["u"] for c in C if c["cmd"] == "/plan" and not c.get("empty")}
    m["plan"] = {"go_users_by_week": go_by_week, "share_by_week": plan_rows,
                 "mean": statistics.mean([x for x in plan_rows if x is not None]) if any(x is not None for x in plan_rows) else None,
                 "reached_go": len(go_users), "got_push": len(plan_users), "used_cmd": len(cmd_plan_users),
                 "reached_any": len(go_users | plan_users | cmd_plan_users), "pushes": len(d["plan_pushes"]),
                 "plan_cmd_total": sum(1 for c in C if c["cmd"] == "/plan"), "plan_cmd_empty": sum(1 for c in C if c["cmd"] == "/plan" and c.get("empty")),
                 "plan_max_line": max((c.get("max_line", 0) for c in C if c["cmd"] == "/plan"), default=0),
                 "plan_lines_median": med([c["lines"] for c in C if c["cmd"] == "/plan"])}

    # ── удержание ──
    ret = []
    for w in range(weeks + 1):
        k = sum(1 for p in done if w in p["active_cycles"])
        ret.append({"week": w, "active": k, "share": ratio(k, len(done))})
    proj = None
    if weeks >= 3 and ret[1]["share"] and ret[weeks]["share"]:
        r = (ret[weeks]["share"] / ret[1]["share"]) ** (1.0 / (weeks - 1))
        proj = min(1.0, ret[weeks]["share"] * r ** (8 - weeks))
    m["retention"] = {"by_week": ret, "last": ret[weeks]["share"] if ret else None, "projected_week8": proj,
                      "churned": sum(1 for p in done if p["churn_cycle"] is not None), "blocked": sum(1 for p in done if p["blocked"])}

    # ── оценки ──
    rt = [t["rating"] for t in T if t["kind"] == "rating"]
    prompts = sum(f["n"] for f in d["feedback_sent"])
    m["rating"] = {"n": len(rt), "mean": statistics.mean(rt) if rt else None, "dist": dict(sorted(Counter(rt).items())),
                   "prompts": prompts, "answered": ratio(len(rt), prompts)}

    # ── повторы между дайджестами ──
    m["repeats"] = repeats_stats(d, sent, dec)

    # ── отправка и скоринг в масштабе (п. 10 спеки) ──
    msgs = [x["cards"] + 1 for x in sent]
    avg_msgs = statistics.mean(msgs) if msgs else None
    m["scale"] = {"avg_messages_per_digest": avg_msgs,
                  "minutes_for_10k": (avg_msgs * 10000 / SEND_RATE / 60) if avg_msgs else None,
                  "max_users_in_15min": int(15 * 60 * SEND_RATE / avg_msgs) if avg_msgs else None}
    m["plan_reminders"] = d["db"].get("plan_reminders", {})
    m["spec_table"] = spec_table(m, d, weeks)
    m["norms"] = norms_table(m, d, sent)
    return m


def norms_table(m: dict, d: dict, sent: list[dict]) -> list[dict]:
    """Операционные показатели против того, что спека требует числом (п. 3.1, 3.2, 8, 10)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    rows: list[dict] = []

    def add(name, value, norm, status, note=""):
        rows.append({"name": name, "value": value, "norm": norm, "status": status, "note": note})

    n = len(sent)
    c57 = sum(1 for x in sent if 5 <= x["cards"] <= 7)
    add("Подборка из 5–7 карточек (п. 3.2)", f"{c57} из {n} = {pct(ratio(c57, n))}; в среднем {num(m['digests']['avg_cards'], 1)}", "все", "na" if not n else "ok" if c57 == n else "fail",
        "по неделям среднее: " + ", ".join(f"{num(v['cards'], 1)}" for v in m["digests"]["by_week"].values() if v.get("digests")))
    full = sum(1 for x in sent if x["slot_cards"] >= 5)
    add("Все 5 слотов уикенда заполнены (п. 8)", f"{full} из {n} = {pct(ratio(full, n))}", "все", "na" if not n else "ok" if full == n else "fail",
        "в seed нет событий на 23.10, а на следующие уикенды их 4–18 на все категории — пустые слоты в основном недобор базы")
    mx = max((x["cards"] + 1 for x in sent), default=0)
    add("Не больше 7 сообщений за раз (п. 8)", f"максимум {mx}", "≤ 7", "na" if not n else "ok" if mx <= 7 else "fail")
    tz = {p["user_id"]: p["tz"] for p in d["personas"]}
    weekly = [x for x in d["digests"] if x["origin"] == "weekly"]
    on_time = 0
    for x in weekly:
        loc = datetime.fromisoformat(x["t"]).astimezone(ZoneInfo(tz.get(x["u"], "Europe/Moscow")))
        on_time += int(loc.weekday() == 3 and loc.hour == 19)
    add("Еженедельная подборка уходит в чт 19:00 по поясу человека (п. 3.2, 8)", f"{on_time} из {len(weekly)} = {pct(ratio(on_time, len(weekly)))}", "все",
        "na" if not weekly else "ok" if on_time == len(weekly) else "fail",
        "часовые повторные запуски дубли не создали" if not any(c > 1 for c in Counter((x['u'], x['week']) for x in weekly).values()) else "есть дубли")
    rp = m["repeats"]
    add("Не повторять показанное без реакции и после «мимо» (п. 8)", f"нарушений {rp['violate_no_reaction_3'] + rp['violate_skip']} из {rp['repeated']} повторов", "0",
        "ok" if rp["violate_no_reaction_3"] + rp["violate_skip"] == 0 else "fail", "повторов всего " + pct(rp["share"], 1) + " показов")
    sc = m["scale"]
    add("Отправка 10 000 человек за 15 минут (п. 10)", f"≈ {num(sc['minutes_for_10k'], 0)} мин при 25 сообщ./с", "≤ 15 мин",
        "na" if not sc["minutes_for_10k"] else "ok" if sc["minutes_for_10k"] <= 15 else "fail", f"{num(sc['avg_messages_per_digest'], 1)} сообщений на человека")
    di = d["db"]["decision_integrity"]
    add("Нажатия сохраняются в БД (F6, F9)", f"{di['checked'] - di['missing'] - di['mismatch']} из {di['checked']}", "все", "ok" if not di["missing"] and not di["mismatch"] else "fail")
    o = m["onboarding"]
    ok_t = o["taps_median"] is not None and o["taps_median"] <= TARGET_TAPS
    add("Нажатий до первой подборки (FLOW-ONBOARDING, разд. 1)", f"min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}; "
        f"≤ {TARGET_TAPS}: {o['taps_le_target']} из {o['completed']}", f"медиана ≤ {TARGET_TAPS}", "na" if o["taps_median"] is None else "ok" if ok_t else "fail",
        f"минимум по коду {o['theoretical_min']}; без правок интересов {('медиана ' + num(o['no_interest_edit_median'], 0) + f" (n={o['no_interest_edit_n']})") if o['no_interest_edit_n'] else 'не обошёлся никто'}; "
        f"правки интересов — {num(o['interest_edits_median'], 0)} нажатий в медиане")
    rf = m["refine"]
    add("«Уточнить под себя» — необязательный блок", f"открыли {rf['opened']} из {o['completed']}; нажатий в медиане {num(rf['taps_median'], 0)}", "необязательно", "na",
        f"пересобрали подборку {rf['rebuilt']}; с «Уточнить» вместе до готового профиля — медиана {num(rf['all_taps_median'], 0)}")
    return rows


def prefill_stats(P: list[dict]) -> dict:
    ps = [p["prefill"] for p in P if p.get("prefill")]
    if not ps:
        return {"personas": 0}
    n = len(ps)

    def avg(k: int) -> float:
        return sum(p["counts"].get(str(k), p["counts"].get(k, 0)) for p in ps) / n

    return {"personas": n, "avg_level3": avg(3), "avg_level2": avg(2), "avg_level1": avg(1), "avg_level0": avg(0),
            "match_share": sum(p["match"] for p in ps) / max(1, sum(p["total"] for p in ps)),
            "shown_match_share": sum(p.get("shown_match", 0) for p in ps) / max(1, sum(p.get("shown", 6) for p in ps)),
            "shown_match_avg": sum(p.get("shown_match", 0) for p in ps) / n}


def repeats_stats(d: dict, sent: list[dict], dec: list[dict]) -> dict:
    by_user: dict[int, list[dict]] = defaultdict(list)
    for x in sent:
        if x["week"] is not None:
            by_user[x["u"]].append(x)
    hist: dict[tuple, list[tuple[str, str]]] = defaultdict(list)       # (u, event) -> [(t, status)]
    for t in sorted(dec, key=lambda t: t["t"]):
        hist[(t["u"], t["event_id"])].append((t["t"], t["status"]))
    total = repeated = 0
    cls: Counter = Counter()
    viol_noreact = viol_skip = viol_first = 0
    seen_weeks: dict[tuple, int] = {}
    seen_origin: dict[tuple, str] = {}
    for u, ds in by_user.items():
        ds.sort(key=lambda x: (x["week"], x["t"]))
        seen_weeks = {}
        for x in ds:
            for eid in x["event_ids"]:
                total += 1
                key = (u, eid)
                if key in seen_weeks and seen_weeks[key] != x["week"]:
                    repeated += 1
                    last = None
                    for t, st in hist.get(key, []):
                        if t <= x["t"]:
                            last = st
                    gap = x["week"] - seen_weeks[key]
                    label = "без реакции" if last is None else last
                    cls[label] += 1
                    if last is None and gap <= 3:
                        viol_noreact += 1
                        viol_first += int(seen_origin.get(key) in ("first", "reset"))
                    if last in ("мимо", "интересно"):
                        viol_skip += 1
                seen_weeks[key] = x["week"]
                seen_origin[key] = x["origin"]
    return {"appearances": total, "repeated": repeated, "share": ratio(repeated, total), "classes": dict(cls),
            "violate_no_reaction_3": viol_noreact, "violate_skip": viol_skip, "violate_from_first": viol_first}


def spec_table(m: dict, d: dict, weeks: int) -> list[dict]:
    o, dg, pl, rt, rk = m["onboarding"], m["digests"], m["plan"], m["retention"], m["rating"]
    rows = []

    def add(mid, name, value, shown, target, status, note=""):
        rows.append({"id": mid, "name": name, "value": value, "shown": shown, "target": target, "status": status, "note": note})

    a = m["activation"]
    add("activation", "Активация: дошли до конца онбординга", a, f"{o['completed']} из {o['started']} = {pct(a)}", "≥ 70 %",
        "na" if a is None else "ok" if a >= 0.70 else "fail", ci(o["completed"], o["started"]))
    r = m["reaction"]
    add("reaction", "Реакция: дайджесты хотя бы с одним решением", r, f"{dg['reacted']} из {dg['sent']} = {pct(r)}", "≥ 40 %",
        "na" if r is None else "ok" if r >= 0.40 else "fail", ci(dg["reacted"], dg["sent"]))
    pm = pl["mean"]
    add("plan", "План: доля пользователей с ≥1 «иду» в неделю (среднее по неделям)", pm, f"{pct(pm)}; по неделям: " +
        ", ".join(pct(x) for x in pl["share_by_week"]), "≥ 25 %", "na" if pm is None else "ok" if pm >= 0.25 else "fail",
        "знаменатель — все прошедшие онбординг")
    last = rt["last"]
    add("retention", f"Удержание: активны на неделе {weeks} (8-недельное измерить нельзя)", last,
        f"{pct(last)}; по неделям: " + ", ".join(pct(x['share']) for x in rt["by_week"]), "8 нед. ≥ 50 %", "na",
        f"экстраполяция на неделю 8 по спаду недель 1–{weeks}: {pct(rt['projected_week8'])} (ориентир, не измерение)" if rt["projected_week8"] is not None
        else "горизонт короче 8 недель")
    q = rk["mean"]
    add("rating", "Качество: средняя оценка «как прошло»", q, f"{num(q, 2)} (n = {rk['n']})", "≥ 4,0", "na" if q is None else "ok" if q >= 4.0 else "fail",
        f"оценили {pct(rk['answered'])} из {rk['prompts']} запросов")
    add("growth", "Рост: доля новых из «Отправить другу»", None, "не измеряется", "≥ 20 %", "na",
        "кнопка «Другу» — URL, бот не видит нажатий и переходов; метрика требует редиректа через сервер")
    add("money", "Деньги: конверсия в Pro, платящий организатор", None, "не измеряется", "≥ 5 % / неделя 6", "na", "платные функции не реализованы")
    return rows


# ───────────────────────── дефекты и юзабилити ─────────────────────────
def load_baseline(name: str = "baseline.json") -> dict | None:
    p = Path(__file__).with_name(name)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# Дефекты прошлого прогона (report.json из коммита «Симулятор 50 пользователей: итоговая версия»): ключ проверки → прежний номер.
PREV_ID = {"day": "Д1", "remind": "Д2", "resurrect": "Д3", "params": "Д4", "interest": "Д5", "links": "Д6", "double": "Д7", "rewrite": "Д8",
           "opened": "Д9", "fault": "Д10", "blocked": "Д11", "stale": "Д12", "text": "Д13", "started": "Д14", "url": "Д15", "scale": "Д16",
           "noback": "Д17", "localhost": "Д18"}
# Порядок вывода открытых дефектов: по серьёзности, внутри — по важности.
DEF_ORDER = ["day", "remind", "resurrect", "params", "interest", "links", "double", "rewrite", "opened", "repeat", "stale", "text", "fault",
             "blocked", "persistent", "rebuilt", "started", "url", "scale", "noback", "localhost"]
USAB_ORDER = ["onboarding", "proposal", "defaults", "skip", "thin", "time", "resent", "text", "started", "interests", "days", "noback", "interest", "digest_btn", "pre"]


def build_defects(m: dict, d: dict) -> tuple[list[dict], list[dict]]:
    """(открытые, закрытые). Каждая проверка отвечает по данным прогона: дефект выводится только если он воспроизвёлся."""
    db = d["db"]
    dd, dr, pr = db.get("decision_day", {}), db.get("digest_rows", {}), db.get("plan_reminders", {})
    fp = d["scenarios"].get("fault_probe", {})
    base = load_baseline() or {}
    base_cnt = {x["id"]: x.get("count") for x in base.get("defects", [])}
    opened: list[dict] = []
    closed: list[dict] = []

    base_rem = sum(v.get("reminded", 0) for k, v in base.get("plan_reminders", {}).items() if isinstance(v, dict) and k in ("Пт", "Сб", "Вс", "Пн–Чт"))
    base_going = sum(v.get("going", 0) for k, v in base.get("plan_reminders", {}).items() if isinstance(v, dict) and k in ("Пт", "Сб", "Вс", "Пн–Чт"))

    def was(key: str) -> str:
        """«(было N)» — только там, где прежний count был размером дефекта (число случаев), а не знаменателем."""
        if key == "remind":
            return f" (было {base_rem} из {base_going})"
        if key == "opened":
            return f" (было opened=true у 0 из {base_cnt.get('Д9')})"
        c = base_cnt.get(PREV_ID.get(key, ""))
        return f" (было {c})" if c is not None and key in ("day", "interest", "links", "double", "rewrite", "url", "started", "text") else ""

    def chk(key, sev, title, is_open, what, where, repro, count, closed_text=""):
        if is_open:
            opened.append({"key": key, "id": key, "severity": sev, "title": title, "what": what, "where": where, "repro": repro, "count": count})
        else:
            closed.append({"key": key, "prev": PREV_ID.get(key, ""), "title": title, "evidence": closed_text})

    # Д1 день решения
    chk("day", "высокая", "«Иду» сохраняется на другой день, чем показан на карточке", dd.get("mismatch", 0) > 0,
        [f"В БД день решения отличается от дня на последней карточке события у {dd.get('mismatch', 0)} из {dd.get('checked', 0)} решений «иду» "
         f"({pct(ratio(dd.get('mismatch', 0), dd.get('checked', 0)))}): раньше карточного — {dd.get('earlier', 0)}, позже — {dd.get('later', 0)}, "
         f"из них повторных решений — {dd.get('redecided', 0)}.",
         *([f"Из лога: {dd['story']}"] if dd.get("story") else []), *[f"Пример: {x}" for x in dd.get("examples", [])[:2]]],
        "leisure/api/services.py (set_decision: выбор Decision.day), leisure/bot/callbacks.py (день в callback_data)",
        "Нажать «Иду» на карточке многодневного события и сравнить `decisions.day` с днём на карточке.", dd.get("mismatch", 0),
        f"расхождений дня 0 из {dd.get('checked', 0)} решений «иду»{was('day')}; день едет в callback_data карточки и обновляется при повторном решении")
    # Д2 напоминания и оценки
    groups = {k: v for k, v in pr.items() if isinstance(v, dict) and "going" in v and k in ("Пт", "Сб", "Вс", "Пн–Чт")}
    going = sum(v["going"] for v in groups.values())
    rem_ok = sum(v["reminded"] for v in groups.values())
    ask_ok = sum(v.get("asked_rating", 0) for v in groups.values())
    low = [k for k, v in groups.items() if v["going"] and v["reminded"] < 0.9 * v["going"]]
    rows = "; ".join(f"{k} {v['reminded']}/{v['going']}" for k, v in groups.items())
    sd = pr.get("same_day_after_9", {})
    chk("remind", "высокая", "Напоминание и запрос оценки получает меньшинство «Иду»", bool(going and (low or ask_ok < 0.9 * going)),
        [f"«План на сегодня» в день события пришёл по {rem_ok} из {going} «иду» ({pct(ratio(rem_ok, going))}): {rows}; «Как прошло?» на следующий день — "
         f"по {ask_ok} ({pct(ratio(ask_ok, going))}). Хуже всего: {', '.join(low) or '—'}."],
        "leisure/worker/schedules.py (job_plan_today, job_how_was_it), leisure/api/services.py (decisions_to_remind, decisions_to_ask)",
        "Нажать «Иду» на событие в воскресенье и проверить, что в воскресенье 09:00 пришёл план.", going - rem_ok,
        f"напоминание в день события: {rem_ok} из {going} ({rows}); «Как прошло?» на следующий день: {ask_ok} из {going}; «иду» на сегодня после 09:00 "
        f"получили напоминание на часовом запуске: {sd.get('reminded', 0)} из {sd.get('going', 0)}; флаги на решении: "
        f"reminded_at {pr.get('flags', {}).get('reminded_at', 0)}, feedback_asked_at {pr.get('flags', {}).get('feedback_asked_at', 0)} из {pr.get('flags', {}).get('total', 0)}{was('remind')}")
    # Д3 воскрешение профиля
    dels = [s for s in d["scenarios"].get("delete", []) if "stale_tap" in s]
    res = [s for s in dels if s.get("profile_after_tap")]
    chk("resurrect", "высокая", "После /delete нажатие на старую кнопку воссоздаёт профиль и решение без согласия", bool(fcount(d, "profile_resurrected") or res),
        [f"Из {len(dels)} нажавших на старую карточку после «Да, удалить всё» у {len(res)} профиль и решение появились снова.",
         *[f"Лог: {x}" for x in fex(d, "profile_resurrected", 1)]],
        "leisure/api/services.py (set_decision), leisure/bot/decisions.py", "/delete → «Да, удалить всё» → «Иду» на старой карточке → SELECT * FROM profiles.", len(res),
        f"нажатий на старые карточки после /delete: {len(dels)}, профилей воссоздано 0, ответ «{(dels[0]['stale_tap']['toast'] if dels else '—')}»{was('resurrect')}")
    # Д4 параметры без влияния
    sens = d.get("sensitivity", {})
    ch = sens.get("changed", {})
    names = {"company": "компания", "kids": "«с детьми»", "notes": "заметка"}
    zero = [k for k in names if sens.get("personas") and not ch.get(k, 0)]
    ctl = (f"Контроль: бюджет — {ch.get('budget (контроль)', 0)}, эстетика — {ch.get('aesthetics (контроль)', 0)}, время — {ch.get('times (контроль)', 0)}")
    chk("params", "средняя", "Не влияют на подборку: " + ", ".join(names[k] for k in zero), bool(zero),
        [f"Пересчёт подборки четверга для {sens.get('personas', 0)} профилей при смене одного параметра: " +
         ", ".join(f"{names[k]} — {ch.get(k, 0)}" for k in names) + f" профилей изменили состав. {ctl}.",
         "Ответ сохраняется, но нигде не используется (шаг «район» из онбординга убран)."],
        "leisure/core/scoring.py читает aesthetics, adults30, budget, times и правила «с детьми» из scoring.yaml; Profile.notes не используется",
        "Два профиля, отличающихся только заметкой, → `GET /api/digest/{id}/preview` даёт одинаковый состав.", len(zero),
        "компания и «с детьми» меняют состав: " + ", ".join(f"{names[k]} — {ch.get(k, 0)}" for k in names) + f" из {sens.get('personas', 0)}; шаг «район» убран из онбординга")
    # Д5 кнопка «Интересно»
    n_int = m["decisions"]["by_status"].get("интересно", 0)
    chk("interest", "средняя", "На карточке нет кнопки «Интересно» (требование F6)", bool(m["digests"]["no_interest_button"]),
        [f"В {m['digests']['sent']} подборках ни одной карточки с «Интересно»: {m['decisions']['wanted_interest']} попыток нажать."],
        "leisure/worker/messages.py (card_keyboard)", "Получить подборку и посмотреть клавиатуру карточки.", m["decisions"]["wanted_interest"],
        f"кнопка есть на карточках; нажата {n_int} раз ({pct(ratio(n_int, m['decisions']['total']))} решений), попыток без кнопки {m['decisions']['wanted_interest']}{was('interest')}")
    # Д6 ссылки после «Мимо»
    chk("links", "средняя", "После «Мимо» с карточки пропадают «Подробнее», «Другу», «Весь дайджест»", fcount(d, "links_lost_after_click") > 0,
        [f"{cnt(fcount(d, 'links_lost_after_click'), 'раз', 'раза', 'раз')} у {fusers(d, 'links_lost_after_click')} человек.",
         *[f"Лог: {x}" for x in fex(d, "links_lost_after_click", 2)]], "leisure/bot/decisions.py (card_rows)",
        "Нажать «Мимо» на последней карточке и выбрать причину.", fcount(d, "links_lost_after_click"),
        f"после «Мимо» ссылок потеряно 0 из {m['decisions']['skip_total']} отказов{was('links')}")
    # Д7 двойной тап
    chk("double", "средняя", "Двойной тап по кнопке карточки даёт «Что-то пошло не так» и ERROR в логе", fcount(d, "error_toast") > 0,
        [f"{fcount(d, 'error_toast')} случаев у {fusers(d, 'error_toast')} человек.", *[f"Лог: {x}" for x in fex(d, "double_tap_error", 1)]],
        "leisure/bot/decisions.py (_edit_markup)", "Быстро нажать «Иду» дважды.", fcount(d, "error_toast"),
        f"двойных тапов {fcount(d, 'double_tap_ok') + fcount(d, 'double_tap_error')}, ошибок 0, ERROR в логе 0{was('double')}")
    # Д8 среда затирает items
    chk("rewrite", "средняя", "Среда 22:00 перезаписывает состав уже отправленного дайджеста", dr.get("items_differ", 0) > 0,
        [f"{dr.get('items_differ', 0)} из {dr.get('rows_sent', 0)} строк digests: Digest.items не совпадает с тем, что реально ушло. "
         f"Следствие: {m['repeats']['violate_from_first']} повторов вопреки правилу «показанное без реакции не повторять».",
         *[f"Пример: {x}" for x in dr.get("examples", [])[:2]]],
        "leisure/worker/schedules.py (job_build_digests) → leisure/api/services.py (save_digest)",
        "Онбординг во вторник, среда 22:00, сравнить digests.items с сообщением.", dr.get("items_differ", 0),
        f"расхождений 0 из {dr.get('rows_sent', 0)} строк digests{was('rewrite')}")
    # Д9 opened/decisions_count
    dec_n = db.get("decisions_with_activity", 0)
    bad9 = dr.get("rows_sent", 0) and dec_n and dr.get("opened_true", 0) == 0 and dr.get("decisions_count_nonzero", 0) == 0
    chk("opened", "средняя", "Digest.opened и Digest.decisions_count никогда не заполняются", bool(bad9),
        [f"Из {dr.get('rows_sent', 0)} дайджестов opened=true у 0, decisions_count>0 у 0, хотя в decisions {dec_n} строк."],
        "leisure/db/models.py (Digest.opened, decisions_count)", "Нажать «Иду», SELECT opened, decisions_count FROM digests.", dr.get("rows_sent", 0),
        f"opened=true у {dr.get('opened_true', 0)} из {dr.get('rows_sent', 0)} дайджестов, decisions_count>0 у {dr.get('decisions_count_nonzero', 0)}, "
        f"сумма decisions_count {dr.get('decisions_count_sum', 0)} при {dec_n} решениях{was('opened')}")
    # повторы вопреки правилам (не из затёртых подборок)
    rp = m["repeats"]
    extra = rp["violate_no_reaction_3"] - rp["violate_from_first"] + rp["violate_skip"]
    chk("repeat", "средняя", "Событие вернулось в подборку вопреки правилам исключения (п. 8)", extra > 0,
        [f"Повторно показано в течение 3 уикендов без реакции: {rp['violate_no_reaction_3'] - rp['violate_from_first']}; после «мимо»/«интересно»: {rp['violate_skip']}."],
        "leisure/api/services.py (recently_shown_ids), leisure/core/recommend.py", "См. раздел повторов.", extra,
        f"нарушений правила исключения {rp['violate_no_reaction_3'] + rp['violate_skip']} из {rp['repeated']} повторов")
    # Д12 старые кнопки после рестарта
    after = d["scenarios"].get("fsm_restart", {}).get("after", [])
    chk("stale", "средняя", "После перезапуска бота старые кнопки онбординга молчат", fcount(d, "stale_button_dead") > 0,
        [f"{fcount(d, 'stale_button_dead')} из {len(after)} нажатий на старый экран после рестарта остались без ответа.", *[f"Лог: {x}" for x in fex(d, "stale_button_dead", 1)]],
        "leisure/bot/onboarding.py (обработчики с состоянием)", "Начать онбординг, перезапустить бота, нажать кнопку на старом экране.", fcount(d, "stale_button_dead"),
        f"{sum(1 for x in after if x.get('handled') and x.get('answered'))} из {len(after)} нажатий на старые экраны после рестарта обработаны и подтверждены "
        f"(экран онбординга хранит состояние в профиле, FSM не нужен){was('stale')}")
    # Д13 текст и команды
    chk("text", "средняя", "Свободный текст и команды на шагах онбординга: молчание или «съеденная» команда", bool(fcount(d, "text_ignored") or fcount(d, "command_eaten_by_notes")),
        [f"Текст без ответа: {fcount(d, 'text_ignored')}, команда принята за заметку: {fcount(d, 'command_eaten_by_notes')}."],
        "leisure/bot/onboarding.py", "На шаге ценностей написать текст; на шаге заметки — /help.", fcount(d, "text_ignored") + fcount(d, "command_eaten_by_notes"),
        f"текст на шагах с кнопками получил подсказку {fcount(d, 'text_answered')} раз из {fcount(d, 'text_answered') + fcount(d, 'text_ignored')}, "
        f"/help на шаге заметки отработал как команда {fcount(d, 'command_in_notes_ok')} из {fcount(d, 'command_in_notes_ok') + fcount(d, 'command_eaten_by_notes')}{was('text')}")
    # Д10 сбои доставки
    once, pers, ra, bl = fp.get("server_error_once", {}), fp.get("server_error_persistent", {}), fp.get("retry_after", {}), fp.get("blocked", {})
    chk("fault", "средняя", "Временный сбой Telegram (5xx, сеть) теряет карточку подборки", bool(once.get("lost")),
        [f"Проба: 502 на втором из трёх сообщений — доставлено {once.get('delivered')}, потеряно {once.get('lost')}."], "leisure/worker/send.py (send_with_bot)",
        "См. Sim.fault_probe.", 1,
        f"разовый 502 → повтор, доставлено {len(once.get('delivered', []))} из 3; 429 → доставлено {len(ra.get('delivered', []))} из 3; результат — SendResult{was('fault')}")
    chk("persistent", "низкая", "Карточка, не доставленная после всех повторов, не досылается", bool(pers.get("lost")),
        [f"Проба: четыре 502 подряд на втором сообщении (три повтора) — undelivered {pers.get('undelivered')}, доставлено {pers.get('delivered')}; "
         "`job_send_digests` считает подборку отправленной (ушли заголовок и карточка) и пишет только WARNING — недостающая карточка не будет дослана."],
        "leisure/worker/send.py (RETRY_DELAYS), leisure/worker/schedules.py (job_send_digests: ok = …)", "См. Sim.fault_probe.", 1, "")
    # Новый: пересобранная подборка не пишется в Digest.items
    rb = db.get("rebuilt", {})
    chk("rebuilt", "низкая", "Пересобранная подборка не записывается в Digest.items", bool(rb.get("not_logged")),
        [f"После «Пересобрать подборку» (в «Уточнить под себя») человеку показано {rb.get('cards', 0)} карточек в {rb.get('digests', 0)} подборках; "
         f"{rb.get('not_logged', 0)} из них ({rb.get('new_events', 0)} новых событий) не попали в `Digest.items` — в БД лежит только первая, прежняя подборка.",
         "`recently_shown_ids` берёт показанное из `Digest.items`, поэтому такие события без реакции в следующие уикенды не считаются показанными и могут прийти снова; "
         "`Digest.items` не совпадает с тем, что человек видел.",
         *([f"Пример: {rb['example']}"] if rb.get("example") else [])],
        "leisure/bot/onboarding.py (_digest_for: save_digest только при first=True), leisure/api/services.py (recently_shown_ids)",
        "Пройти онбординг, в «Уточнить под себя» сменить бюджет, нажать «Пересобрать подборку» и сравнить карточки с `digests.items` этого уикенда.",
        rb.get("not_logged", 0), "")
    # Д11 блокировка
    blk = db.get("blocked", [])
    chk("blocked", "средняя", "Заблокировавший бота остаётся активным и получает попытки отправки", db.get("profiles_active_after_block", 0) > 0,
        [f"{len(blk)} заблокировавших; активных после блокировки: {db.get('profiles_active_after_block', 0)}; отклонённых вызовов {sum(b['failed_sends'] for b in blk)}."],
        "leisure/worker/send.py, leisure/worker/schedules.py", "Заблокировать бота и посмотреть логи воркера.", len(blk),
        f"заблокировавших {len(blk)}, рассылки выключены у {len(blk) - db.get('profiles_active_after_block', 0)}; отклонённых вызовов {sum(b['failed_sends'] for b in blk)}; "
        f"проба: после Forbidden остальные сообщения не отправляются (blocked={bl.get('blocked')}){was('blocked')}")
    # Д14 начавшиеся события
    chk("started", "низкая", "Подборка пришла с событиями, которые уже начались", m["digests"]["already_started"] > 0,
        [f"{cnt(m['digests']['already_started'], 'карточка', 'карточки', 'карточек')}.", *[f"Лог: {x}" for x in fex(d, "card_already_started", 2)]],
        "leisure/bot/onboarding.py, leisure/bot/commands.py, leisure/api/services.py", "Пройти онбординг в воскресенье вечером.", m["digests"]["already_started"],
        f"карточек с начавшимися событиями 0 при {sum(1 for p in d['personas'] if p['completed'] and p.get('onboard_offset_h', 0) >= 96)} онбордингах в сб–вс{was('started')}")
    # Д15 длинные URL
    v = d.get("violations", {}).get("button_url_long")
    chk("url", "низкая", "URL кнопок длиннее 2 048 символов", bool(v),
        [f"{cnt(v['count'], 'карточка', 'карточки', 'карточек') if v else ''} с URL > 2048 символов."], "leisure/core/links.py", "Собрать подборку, посмотреть длину url «Другу».",
        v["count"] if v else 0, f"URL кнопок длиннее 2048 символов: 0{was('url')}")
    # Д16 масштаб
    sc = m["scale"]
    chk("scale", "низкая", "Отправка дайджеста 10 000 пользователям не укладывается в 15 минут (п. 10)", bool(sc["minutes_for_10k"] and sc["minutes_for_10k"] > 15),
        [f"В среднем {num(sc['avg_messages_per_digest'], 1)} сообщений на подборку, лимит {SEND_RATE} сообщ./с → 10 000 человек ≈ {num(sc['minutes_for_10k'], 0)} мин; "
         f"за 15 минут успеть можно ≈ {sc['max_users_in_15min']} человек."],
        "leisure/worker/send.py (SEND_INTERVAL = 1/25), leisure/worker/schedules.py (digest_messages)", "Число сообщений на подборку × 10 000 / 25.", 1,
        f"≈ {num(sc['minutes_for_10k'], 0)} мин")
    # Д17 нет «Назад»
    mm = db.get("profile_mismatch", {})
    n_back = m["onboarding"]["back_screens"]
    chk("noback", "низкая", "Ошибку в ответе онбординга исправить нельзя — сохраняется неверный профиль", n_back == 0 and m["onboarding"]["all_screens_checked"] > 0,
        [f"«Назад» на {n_back} из {m['onboarding']['all_screens_checked']} экранов; у {sum(1 for p in d['personas'] if p.get('misclick') and p['misclick'].get('recovery') == 'continue')} "
         f"нажавших не ту кнопку в БД лежат неверные ответы: {', '.join(f'{ANSWER_RU.get(k, k)} — {v}' for k, v in sorted(mm.items())) or '—'}."],
        "leisure/bot/onboarding.py (шаги без «Назад»)", "Выбрать бюджет «до 1 000 ₽» по ошибке и дойти до конца.", sum(mm.values()),
        f"«← Назад» на {n_back} из {m['onboarding']['all_screens_checked']} проверенных экранов; профилей с неверными ответами из-за ошибки: {sum(mm.values())}")
    # Д18 localhost
    lh = fp.get("localhost", {})
    chk("localhost", "низкая", "WEB_BASE_URL=localhost делает онбординг невозможным", bool(lh) and (lh.get("url_buttons", 0) > 0 or not lh.get("sent")),
        ["При localhost URL-кнопки уходят в Telegram и отклоняются."], "leisure/bot/onboarding.py", "Запустить бота без WEB_BASE_URL.", 1,
        f"проба с WEB_BASE_URL=localhost: URL-кнопок {lh.get('url_buttons', 0)}, ссылка на политику в тексте: {'да' if lh.get('link_in_text') else 'нет'}, "
        f"сообщение доставлено: {'да' if lh.get('sent') else 'нет'}{was('localhost')}")
    return opened, closed


PREV_UID = {"onboarding": "У1", "interests": "У2", "days": "У3", "noback": "У4", "interest": "У5", "skip": "У6", "thin": "У7", "time": "У8",
            "digest_btn": "У9", "text": "У10", "resent": "У11", "pre": "У12", "started": "У13"}


def build_usability(m: dict, d: dict) -> tuple[list[dict], list[dict]]:
    """(открытые, закрытые прежние). Проблема выводится, только если воспроизвелась в этом прогоне."""
    o, dg, dec = m["onboarding"], m["digests"], m["decisions"]
    base = load_baseline() or {}
    prev_title = {x["id"]: x["title"] for x in base.get("usability", [])}
    opened: list[dict] = []
    closed: list[dict] = []

    def item(key, title, is_open, evidence, advice, closed_text=""):
        if is_open:
            opened.append({"key": key, "id": key, "priority": 0, "title": title, "evidence": evidence, "advice": advice})
        elif PREV_UID.get(key):
            closed.append({"key": key, "prev": PREV_UID[key], "title": prev_title.get(PREV_UID[key], title), "evidence": closed_text})

    P = d["personas"]
    done = [p for p in P if p["completed"]]
    pf = o["prefill"]
    rf = m["refine"]
    ig = d["db"].get("intent_gap", {})
    # У1: длина онбординга
    n_screens = len(o["screens"])
    long_ = bool(o["taps_median"] and o["taps_median"] > TARGET_TAPS)
    item("onboarding", "Онбординг: нажатий до подборки больше целевых 12", long_,
         [f"До первой подборки: min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}; в пределах {TARGET_TAPS} уложились {o['taps_le_target']} из {o['completed']}. "
          f"Минимум по коду {o['theoretical_min']}; без правок интересов " + (f"медиана {num(o['no_interest_edit_median'], 0)} (n={o['no_interest_edit_n']})." if o['no_interest_edit_n'] else "не обошёлся никто."),
          f"Остальное — правки интересов: в медиане {num(o['interest_edits_median'], 0)} нажатий (макс. {o['interest_edits_max']}), на экран интересов в среднем "
          f"{num(o['step_means'].get('interests'), 1)} нажатия; «Все направления» открыли {rf['used_all_screen']} из {o['completed']}.",
          f"Не дошли {o['started'] - o['completed']} из {o['started']}; номера шагов честные: «Шаг 1 из 2», «Шаг 2 из 2» ({n_screens} экранов до сохранения)."],
         "Предлагать шесть направлений точнее (см. следующий пункт) и добавлять своё без захода в «Все направления».",
         f"нажатий до подборки: min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}; «Шаг 1 из 2», «Шаг 2 из 2» вместо 18 экранов с ложной нумерацией")
    # новое: качество предложенных шести
    weak = bool(pf.get("personas")) and pf["shown_match_share"] < 0.6
    item("proposal", "Предложенные шесть направлений слабо совпадают с тем, что хочет человек", weak,
         [f"Из шести предложенных в интерес персоны попало в среднем {num(pf.get('shown_match_avg'), 1)} ({pct(pf.get('shown_match_share'))}); по всем 19 направлениям предзаполнение совпало в {pct(pf.get('match_share'))}.",
          f"Лишнее приходится убирать, нужное — искать в «Все направления»: правок в медиане {num(o['interest_edits_median'], 0)}."],
         "Ранжировать направления по ценностям точнее; дать «Другое?» с быстрым добавлением двух-трёх направлений.")
    item("interests", "Список интересов: 19 кнопок в столбик и цикл из четырёх состояний", False, [], "",
         f"6 направлений + «Все направления» (кисть вместо цикла); на экран интересов в среднем {num(o['step_means'].get('interests'), 1)} нажатия (было 9,7)")
    # У3: день
    picks = fcount(d, "day_picked")
    item("days", "Нельзя выбрать другой день у события, идущего несколько дней", bool(dg["multi_day_cards"]) and picks == 0,
         [f"{dg['multi_day_cards']} многодневных карточек, ряда «Пт / Сб / Вс» нет."], "Ряд кнопок дня.",
         f"ряд «Пт / Сб / Вс» есть на многодневных карточках ({dg['multi_day_cards']} из {dg['total_cards']}); день выбирали {picks} раз, расхождений дня в БД {d['db'].get('decision_day', {}).get('mismatch', 0)}")
    bs, ac = o["back_screens"], o["all_screens_checked"]
    item("noback", "Нельзя вернуться или отменить шаг онбординга", ac > 0 and bs == 0,
         [f"«Назад» на {bs} из {ac} экранов."], "Кнопка «← Назад».",
         f"«← Назад» на {bs} из {ac} проверенных экранов; ошибку в ценностях исправили через «Назад» {fcount(d, 'misclick_fixed_with_back')} чел.")
    item("interest", "Нет кнопки «Интересно» на карточке (F6)", bool(dec["wanted_interest"]), [f"{dec['wanted_interest']} попыток нажать."], "",
         f"«Интересно» нажато {dec['by_status'].get('интересно', 0)} раз ({pct(ratio(dec['by_status'].get('интересно', 0), dec['total']))} решений)")
    # У6: причины «Мимо»
    reasons = dec["reasons"]
    first3 = sum(reasons.get(k, 0) for k in ("не моё", "дорого", "далеко"))
    hidden = sum(v for k, v in reasons.items() if k and k not in ("не моё", "дорого", "далеко"))
    tot_r = first3 + hidden
    item("skip", "«Мимо»: причины в два шага, а блок остаётся на карточке, если не отвечать", dec["skip_total"] > 0 and (hidden > 0 or dec["skip_unanswered"] > 0),
         [f"{dec['skip_total']} нажатий «Мимо»: причину выбрали {dec['skip_with_reason']}, блок оставили без ответа {dec['skip_unanswered']}.",
          f"{hidden} из {tot_r} выбранных причин ({pct(ratio(hidden, tot_r))}) спрятаны за «Ещё…» (второе нажатие): «уже был», «не то время», «не та компания»."],
         "Вынести «Уже был» в первый ряд или сворачивать блок через минуту без ответа.")
    silent = m["silent"]
    thin = [v["empty"] for v in dg["by_week"].values() if v.get("digests")]
    item("thin", "Подборки худеют к концу прогона", bool(silent["user_weeks"]) and bool(thin) and max(thin) - min(thin) >= 1,
         ["Пустых слотов из 5 по неделям: " + ", ".join(f"неделя {w} — {num(v['empty'], 1)}" for w, v in dg["by_week"].items() if v.get("digests")) + ".",
          f"Человеко-недель без подборки: {silent['silent']} из {silent['user_weeks']} ({pct(silent['share'])}); сообщение «ничего не нашлось» получено {silent['empty_notices']} раз."],
         "Показывать лучшее из «на горизонте»; в проде база будет богаче seed.")
    item("time", "Время события — сырой текст источника, а не время выбранного дня", bool(dg["messy_time"] or dg["plan_messy_lines"]),
         [f"{dg['messy_time']} из {dg['all_cards']} карточек ({pct(ratio(dg['messy_time'], dg['all_cards']))}) показывают расписание сразу на несколько дат; "
          f"в «Плане на сегодня» {dg['plan_messy_lines']} из {dg['plan_lines']} строк."], "Подставлять время выбранного дня.",
         f"время выбранного дня на карточке и в плане; сырое расписание в {dg['messy_time']} из {dg['all_cards']} карточек и {dg['plan_messy_lines']} из {dg['plan_lines']} строк плана")
    plan_btn = sum(1 for c in d["commands"] if c.get("via") == "button")
    item("digest_btn", "«Весь дайджест» висит только на последней карточке", False, [], "",
         f"«Весь дайджест» и «Мой план» стоят под заголовком подборки; «Мой план» нажали {plan_btn} раз")
    item("text", "Свободный текст в чат игнорируется", bool(fcount(d, "text_ignored")), [f"{fcount(d, 'text_ignored')} раз без ответа."], "",
         f"ответ на текст получен {fcount(d, 'text_answered')} раз из {fcount(d, 'text_answered') + fcount(d, 'text_ignored')}")
    item("resent", "Повторно присланная карточка не показывает прежнее решение", bool(dg["resent_no_status"]),
         [f"{cnt(dg['resent_no_status'], 'карточка', 'карточки', 'карточек')} без отметки ●."], "Рисовать ● из БД.",
         "карточек с принятым решением без отметки ●: 0 (было 25); «Прежний ответ» в тексте карточки")
    item("pre", "/plan приходит одним моноширинным блоком", bool(m["plan"]["plan_cmd_total"] and m["plan"]["plan_max_line"] > 120),
         [f"Строки в /plan до {m['plan']['plan_max_line']} символов."], "Плоский текст с переносами.",
         f"/plan обычным текстом и карточками; самая длинная строка {m['plan']['plan_max_line']} символов, `<pre>` нет")
    item("started", "Подборка показывает уже начавшиеся события", bool(dg["already_started"]), [f"{dg['already_started']} карточек."], "Отсекать по времени начала.",
         f"карточек с начавшимися событиями {dg['already_started']} при {sum(1 for p in done if p.get('onboard_offset_h', 0) >= 96)} онбордингах в сб–вс")
    # новое: умолчания у тех, кто не открыл «Уточнить»
    nr = ig.get("not_refined", {"n": 0, "with_gap": 0, "fields": {}})
    exp_skip = Counter()
    ref_of = {p["user_id"]: p.get("refine_ops") is not None for p in P}
    budget_of = {p["user_id"]: p for p in P}
    for t in d["decisions"]:
        if t["kind"] == "reason" and t.get("reason") == "дорого":
            exp_skip["refined" if ref_of.get(t["u"]) else "not_refined"] += 1
    item("defaults", "Не открывшие «Уточнить под себя» остаются с умолчаниями, которые им не подходят", nr["n"] > 0 and nr["with_gap"] > 0.3 * nr["n"],
         [f"Из {nr['n']} прошедших онбординг без «Уточнить» у {nr['with_gap']} ({pct(ratio(nr['with_gap'], nr['n']))}) профиль расходится с тем, что они ответили бы: "
          + ", ".join(f"{ANSWER_RU.get(k, {'kids': 'с детьми'}.get(k, k))} — {v}" for k, v in sorted(nr["fields"].items(), key=lambda kv: -kv[1])) + ".",
          f"Меню открыли {rf['opened']} из {o['completed']} (в среднем {num(rf['taps_median'], 0)} нажатий); пересобрали подборку {rf['rebuilt']}.",
          f"Причина «дорого» в «Мимо»: у не открывших «Уточнить» {exp_skip['not_refined']}, у открывших {exp_skip['refined']}."],
         "Спрашивать бюджет сразу в «Шаге 2» одной строкой или подсказывать «Уточнить» после первых «Мимо — дорого».")
    _ = budget_of
    return opened, closed


def renumber(defects: list[dict], usab: list[dict], closed: list[dict]) -> None:
    """Идентификаторы Д1…/У1… присваиваются после сортировки; ссылки вида @ключ@ в текстах заменяются на присвоенный номер."""
    order = {k: i for i, k in enumerate(DEF_ORDER)}
    defects.sort(key=lambda x: order.get(x["key"], 99))
    ids = {x["key"]: f"Д{i}" for i, x in enumerate(defects, 1)}
    for x in defects:
        x["id"] = ids[x["key"]]
    uo = {k: i for i, k in enumerate(USAB_ORDER)}
    usab.sort(key=lambda x: uo.get(x["key"], 99))
    for i, x in enumerate(usab, 1):
        x["id"], x["priority"] = f"У{i}", i
    for x in closed:
        x["id"] = x["prev"]


# ───────────────────────── вывод ─────────────────────────
def compare_rows(m: dict, d: dict, defects: list[dict], closed: list[dict], usab: list[dict]) -> list[list[str]] | None:
    """Строки «метрика | было | после правок бота | стало». «Было» — sim/baseline.json (исходный прогон), «после правок» — baseline_fixes.json
    (прогон после закрытия дефектов бота и воркера, до онбординга v2), «стало» — этот прогон."""
    b = load_baseline()
    if not b:
        return None
    f = load_baseline("baseline_fixes.json") or {}

    def val(src: dict, mid: str):
        return next((r["value"] for r in src.get("spec_metrics", []) if r["id"] == mid), None)

    def p(x):
        return pct(x) if x is not None else "н/д"

    def taps(src: dict) -> str:
        o = src.get("onboarding", {})
        return f"{o.get('taps_min')} / {num(o.get('taps_median'), 0)} / {o.get('taps_max')}" if o else "н/д"

    o = m["onboarding"]
    now_taps = f"{o['taps_min']} / {num(o['taps_median'], 0)} / {o['taps_max']}"

    def row(name, fn, now):
        return [name, fn(b), fn(f) if f else "—", now]

    rows = [
        row("Активация", lambda s: p(val(s, "activation")), p(m["activation"])),
        row("Реакция (подборки с решением)", lambda s: p(val(s, "reaction")), p(m["reaction"])),
        row("«Иду» в неделю (среднее)", lambda s: p(val(s, "plan")), p(m["plan"]["mean"])),
        row("Удержание на последней неделе", lambda s: p(val(s, "retention")), p(m["retention"]["last"])),
        row("Средняя оценка", lambda s: num(val(s, "rating"), 2), num(m["rating"]["mean"], 2)),
        row("Нажатий до первой подборки: min / медиана / max", taps, now_taps),
        row("Нажатий до первого «Иду» (медиана)", lambda s: num(s.get("first_go", {}).get("taps_median"), 0), num(m["first_go"]["taps_median"], 0)),
        row("Бросили онбординг (из 50)", lambda s: str(s.get("onboarding", {}).get("started", 0) - s.get("onboarding", {}).get("completed", 0)),
            str(o["started"] - o["completed"])),
        row("Карточек в подборке (среднее)", lambda s: num(s.get("digests", {}).get("avg_cards"), 1), num(m["digests"]["avg_cards"], 1)),
        row("Пустых слотов из 5 (среднее)", lambda s: num(s.get("digests", {}).get("avg_empty"), 2), num(m["digests"]["avg_empty"], 2)),
        row("Повторные показы, доля", lambda s: pct(s.get("repeats", {}).get("share"), 1), pct(m["repeats"]["share"], 1)),
        row("Дошли до плана", lambda s: str(s.get("plan", {}).get("reached_any")), str(m["plan"]["reached_any"])),
        row("Решений «Интересно»", lambda s: str(s.get("decisions", {}).get("by_status", {}).get("интересно", 0)), str(m["decisions"]["by_status"].get("интересно", 0))),
        row("«Мимо»: причина не выбрана", lambda s: str(s.get("decisions", {}).get("skip_unanswered")), str(m["decisions"]["skip_unanswered"])),
    ]
    for k in ("Пт", "Вс", "Пн–Чт"):
        def fn(s, k=k):
            v = s.get("plan_reminders", {}).get(k, {})
            return f"{v.get('reminded', 0)} из {v.get('going', 0)}"
        new = m["plan_reminders"].get(k, {})
        rows.append(row(f"Напоминание в день события, {k}", fn, f"{new.get('reminded', 0)} из {new.get('going', 0)}"))
    sev_b = Counter(x["severity"] for x in b.get("defects", []))
    sev_f = Counter(x["severity"] for x in f.get("defects", []))
    nsev = Counter(x["severity"] for x in defects)
    rows += [["Открытых дефектов, всего", str(len(b.get("defects", []))), str(len(f.get("defects", []))) if f else "—", str(len(defects))],
             ["  высокой серьёзности", str(sev_b.get("высокая", 0)), str(sev_f.get("высокая", 0)) if f else "—", str(nsev.get("высокая", 0))],
             ["  средней", str(sev_b.get("средняя", 0)), str(sev_f.get("средняя", 0)) if f else "—", str(nsev.get("средняя", 0))],
             ["  низкой", str(sev_b.get("низкая", 0)), str(sev_f.get("низкая", 0)) if f else "—", str(nsev.get("низкая", 0))],
             ["Закрыто из дефектов исходного прогона", "—", str(len(f.get("closed_defects", []))) if f else "—", f"{len(closed)} из {len(PREV_ID)}"],
             ["Проблем юзабилити (открытых)", str(len(b.get("usability", []))), str(len(f.get("usability", []))) if f else "—", str(len(usab))]]
    return rows


def render_md(m: dict, d: dict, defects: list[dict], usab: list[dict], closed: list[dict] | None = None,
              closed_u: list[dict] | None = None) -> str:
    closed = closed or []
    closed_u = closed_u or []
    meta, o, dg, dec, pl, rk = d["meta"], m["onboarding"], m["digests"], m["decisions"], m["plan"], m["rating"]
    L: list[str] = []
    w = meta["weeks"]
    L += ["# Отчёт симуляции пользователей — «Планировщик досуга»", "",
          f"Прогон: seed `{meta['seed']}`, {meta['users']} персон ({', '.join(f'{k} {v}' for k, v in sorted(meta['archetypes'].items()))}), "
          f"неделя онбординга и {w} {'недели' if w in (2, 3, 4) else 'недель'} после неё — {w + 1} уикендов (23.10 – {(date_str(meta, w))}), {meta['updates_fed']} апдейтов через `Dispatcher.feed_update`, "
          f"{meta['world_calls']} исходящих вызовов Bot API (в поддельной сессии, без сети). События: seed {meta['events_seeded']} шт.", "",
          f"Команда: `python -m leisure.sim.runner --users {meta['users']} --weeks {w} --seed {meta['seed']}`. База `{meta['db_name']}` создаётся и удаляется прогоном, база разработки не затрагивается. "
          "Один seed — один и тот же отчёт (кроме строки о длительности в конце).", "",
          "> **Как читать.** Код продукта — настоящий: бот, фильтры, FSM, клавиатуры, задачи воркера и БД. Люди — модель: ответы онбординга, вероятности отвала, "
          "открытия, решений и оценок заданы допущениями в `personas.py` (п. «Ограничения»). Поэтому абсолютные доли (активация, реакция, удержание) — "
          "«что будет при таком поведении», а не прогноз; надёжны находки о механике продукта: дефекты и юзабилити ниже подтверждены логом.", ""]
    cr = compare_rows(m, d, defects, closed, usab)
    if cr:
        L += ["## 0. Было → стало (против прошлого прогона)", "",
              "«Было» — `leisure/sim/baseline.json` (исходный прогон до правок), «после правок» — `baseline_fixes.json` (бот и воркер после закрытия дефектов, "
              "онбординг ещё прежний), «стало» — этот прогон (онбординг v2, 19 ценностей, карточка 2×2, причины в два шага, ежедневные план и оценки). "
              "Тот же seed и те же 50 архетипов (горизонт этого прогона — 4 недели после недели онбординга, в прошлых было 5, поэтому «удержание на последней неделе» и средние сравнивать надо с оговоркой); у персон прежние интересы, время и вероятности отвала, но ценности теперь выбираются из 19 (у 40 из 50 в пятёрке "
              "есть новые), а часть персон открывает «Уточнить под себя». Новых отвалов на удалённых шагах нет по построению, поэтому активацию сравнивать надо с оговоркой: "
              "доля 78 % → выше в основном потому, что убраны экраны, на которых прежде бросали.", "",
              table(["Показатель", "Было (исходный прогон)", "После правок бота и воркера", "Стало (онбординг v2, 19 ценностей)"], cr), ""]
    L += ["## 1. Метрики п. 11 спеки", "",
          table(["Метрика", "Значение", "Цель", "Статус", "Примечание"],
                [[r["name"], r["shown"], r["target"], STATUS_RU[r["status"]], r["note"]] for r in m["spec_table"]]), ""]
    L += ["## 2. Операционные метрики", "", "### Показатели против норм спеки", "",
          table(["Показатель", "Значение", "Норма", "Статус", "Примечание"], [[r["name"], r["value"], r["norm"], STATUS_RU[r["status"]], r["note"]] for r in m["norms"]]), "",
          "### Онбординг", "",
          f"Начали {o['started']}, прошли {o['completed']} ({pct(m['activation'])}). Нажатий до первой подборки (включая /start): "
          f"**min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}** (минимум по коду — {o['theoretical_min']}; цель FLOW-ONBOARDING — "
          f"не больше {TARGET_TAPS}: уложились {o['taps_le_target']} из {o['completed']}; у не ошибавшихся: min {o['taps_clean_min']}, медиана {num(o['taps_clean_median'], 0)}, "
          f"max {o['taps_clean_max']}). Без правок интересов " + (f"медиана {num(o['no_interest_edit_median'], 0)} (n={o['no_interest_edit_n']})." if o['no_interest_edit_n'] else "не обошёлся никто (у всех персон интересы отличаются от предложенных шести).") + "", "",
          f"«Уточнить под себя» открыли {m['refine']['opened']} из {o['completed']} (меню хотели {m['refine']['personas_with_menu']}); нажатий в блоке — медиана "
          f"{num(m['refine']['taps_median'], 0)}, макс. {m['refine']['taps_max']}; пункты: " + (", ".join(f"{ANSWER_RU.get(k, {'kids': 'с детьми'}.get(k, k))} — {v}" for k, v in sorted(m['refine']['ops'].items())) or "—")
          + f"; «Пересобрать подборку» нажали {m['refine']['rebuilt']}. Профиль целиком (подборка + меню) — медиана {num(m['refine']['all_taps_median'], 0)} нажатий.", "",
          table(["Шаг", "Дошли до экрана", "Бросили на нём", "Нажатий в среднем"],
                [[STEP_RU[f["step"]], f["reached"], f["left"], num(o["step_means"].get(f["step"], 0), 1)] for f in o["funnel"]]), "",
          "### Решения и причины", "",
          table(["Статус", "Нажатий", "Доля"], [[k, v, pct(ratio(v, dec["total"]))] for k, v in sorted(dec["by_status"].items(), key=lambda kv: -kv[1])]
                + ([["интересно (кнопки нет)", f"0 (хотели {dec['wanted_interest']})", "—"]] if dec["wanted_interest"] else [])), "",
          f"«Мимо» — {dec['skip_total']}; причины: " + (", ".join(f"{k or 'без причины'} {v}" for k, v in sorted(dec['reasons'].items(), key=lambda kv: -kv[1])) or "—")
          + f"; блок причин оставили без ответа: {dec['skip_unanswered']}.", "",
          f"Нажатий до первого «Иду» (от первого /start, включая онбординг): min {num(m['first_go']['taps_min'], 0)}, медиана {num(m['first_go']['taps_median'], 0)}, "
          f"max {num(m['first_go']['taps_max'], 0)}; «Иду» нажимали {m['first_go']['users']} из {m['first_go']['of']} прошедших, в самой первой подборке — {m['first_go']['in_first_digest']}.", "",
          "### Подборки по неделям", "",
          table(["Уикенд", "Дайджестов", "Карточек", "Слотов заполнено из 5", "Пустых слотов", "«На горизонте»", "Открыли", "С решением", "С «Иду»"],
                [[("0 (23–25.10)" if wk == 0 else wk), v["digests"], num(v["cards"], 1), num(v["slots"], 1), num(v["empty"], 1), num(v["horizon"], 1),
                  v["opened"], v["reacted"], v["go"]] for wk, v in dg["by_week"].items() if v.get("digests")]), "",
          f"Всего отправлено {dg['sent']} подборок (в т.ч. первых {dg['first']}), ещё {dg['manual']} по /digest. Пустых слотов в среднем {num(dg['avg_empty'], 2)} из 5; "
          f"подборок с пустыми слотами {dg['with_empty']} из {dg['sent']}. Человеко-недель без подборки: {m['silent']['silent']} из {m['silent']['user_weeks']} ({pct(m['silent']['share'])}), в лог «нечего отправить» воркер записал {m['silent']['logged_nothing']}.", "",
          "### Повторы между дайджестами", "",
          f"Показов события: {m['repeats']['appearances']}, из них повторных (то же событие тому же человеку в другом уикенде): {m['repeats']['repeated']} ({pct(m['repeats']['share'], 1)}). "
          "Состояние решения на момент повтора: " + (", ".join(f"{k} — {v}" for k, v in sorted(m['repeats']['classes'].items())) or "—")
          + f". Нарушений правила исключения: без реакции в пределах 3 уикендов — {m['repeats']['violate_no_reaction_3']}, после «мимо»/«интересно» — {m['repeats']['violate_skip']}.", "",
          "### План и оценки", "",
          f"Дошли до плана: {pl['reached_any']} из {o['completed']} (нажали «Иду» — {pl['reached_go']}, получили «План на сегодня» — {pl['got_push']} ({pl['pushes']} сообщений), "
          f"открыли /plan с непустым планом — {pl['used_cmd']}). /plan вызывали {pl['plan_cmd_total']} раз, пустой план — {pl['plan_cmd_empty']}.", "",
          f"Оценок {rk['n']} на {rk['prompts']} запросов «Как прошло?» ({pct(rk['answered'])}); распределение: " + ", ".join(f"{k}★ — {v}" for k, v in rk["dist"].items()) + ".", "",
          "«Иду», по которым можно было напомнить (человек нажал не позже дня события):", "",
          table(["День события «Иду»", "Всего «Иду»", "«План на сегодня» в день события", "«Как прошло?» на следующий день"],
                [[k, v["going"], v["reminded"], v["asked_rating"]] for k, v in m["plan_reminders"].items() if isinstance(v, dict) and "going" in v and k in ("Пт", "Сб", "Вс", "Пн–Чт")]), "",
          f"«Иду» на сегодня после 09:00: напоминание на ближайшем часовом запуске — {m['plan_reminders'].get('same_day_after_9', {}).get('reminded', 0)} из "
          f"{m['plan_reminders'].get('same_day_after_9', {}).get('going', 0)}; нажали, когда день события уже прошёл: {m['plan_reminders'].get('stale_taps', 0)}.", "",
          "### Масштаб и целостность", "",
          f"Сообщений на подборку в среднем {num(m['scale']['avg_messages_per_digest'], 1)} → 10 000 человек при 25 сообщ./с ≈ {num(m['scale']['minutes_for_10k'], 0)} мин (цель п. 10 — 15 мин). "
          f"Целостность: нажатий не найдено в БД — {d['db']['decision_integrity']['missing']}, расхождений статуса/причины — {d['db']['decision_integrity']['mismatch']} "
          f"из {d['db']['decision_integrity']['checked']}; профилей с неверными ответами из-за ошибки без «Назад» — {sum(d['db'].get('profile_mismatch', {}).values())}. "
          f"Нарушения правил Bot API в поддельной сессии: " + (", ".join(f"{k} — {v['count']}" for k, v in sorted(d['violations'].items())) or "нет") + ". "
          f"Исключения обработчиков бота: {d['handler_errors']}; записи ERROR/WARNING продукта: {len(d['log_errors'])}.", ""]
    L += ["## 3. Дефекты продукта", "", "### 3.1 Открытые", "",
          "Каждый воспроизведён прогоном; «где» — файл (и функция), «как воспроизвести» — минимальные шаги.", ""]
    for x in defects:
        L += [f"### {x['id']} [{x['severity']}] {x['title']}", ""]
        L += [f"- {line}" for line in x["what"]]
        L += [f"- **Где:** {x['where']}", f"- **Как воспроизвести:** {x['repro']}", ""]
    if not defects:
        L += ["Открытых дефектов нет.", ""]
    if closed:
        L += ["### 3.2 Закрыто с прошлого прогона", "",
              table(["Было", "Дефект", "Что показал этот прогон"], [[x["prev"], x["title"], x["evidence"] or "—"] for x in sorted(
                  (c for c in closed if c["prev"]), key=lambda x: int(x["prev"][1:]))]), ""]
    L += ["## 4. Проблемы юзабилити (по убыванию важности)", ""]
    for x in usab:
        L += [f"### {x['id']}. {x['title']}", ""]
        L += [f"- {line}" for line in x["evidence"]]
        L += [f"- **Что сделать:** {x['advice']}", ""]
    if not usab:
        L += ["Проблем не найдено.", ""]
    if closed_u:
        L += ["### 4.1 Закрыто с прошлых прогонов", "",
              table(["Было", "Проблема", "Что показал этот прогон"], [[x["prev"], x["title"], x["evidence"] or "—"] for x in sorted(
                  closed_u, key=lambda x: int(x["prev"][1:]))]), ""]
    L += ["## 5. Что подтвердилось и что нет (контрольные проверки)", ""]
    vio = d.get("violations", {})
    st = d["scenarios"].get("startup", {})
    cmds = Counter(c["cmd"] for c in d["commands"])
    fp = d["scenarios"].get("fault_probe", {})
    fsm = d["scenarios"].get("fsm_restart", {})
    dl = d["scenarios"].get("delete", [])
    L += [f"- Пробы доставки (настоящий `send_with_bot` на трёх сообщениях): разовый 502 → доставлено {len(fp.get('server_error_once', {}).get('delivered', []))} из 3; "
          f"429 → {len(fp.get('retry_after', {}).get('delivered', []))} из 3; Forbidden → заблокирован {fp.get('blocked', {}).get('blocked')}, доставлено "
          f"{len(fp.get('blocked', {}).get('delivered', []))} из 3; стойкий 502 → доставлено {len(fp.get('server_error_persistent', {}).get('delivered', []))} из 3.",
          f"- Рестарт бота (пустой MemoryStorage): нажатий на старые экраны онбординга до рестарта {len(fsm.get('before', []))} (работали: "
          f"{sum(1 for x in fsm.get('before', []) if x.get('handled'))}), после — {len(fsm.get('after', []))}, ответ получили "
          f"{sum(1 for x in fsm.get('after', []) if x.get('answered') and x.get('reply'))}.",
          f"- /delete: удалено профилей {len(dl)}; профиль после удаления был в БД у {sum(1 for x in dl if x.get('profile_after_delete'))}, после нажатия на старую карточку — у "
          f"{sum(1 for x in dl if x.get('profile_after_tap'))}.",
          f"- Запуск бота выполнен настоящим `leisure.bot.main.run()` (токен, класс Bot и start_polling подменены): меню команд {', '.join('/' + c for c in st.get('commands', []))}; "
          f"allowed_updates {st.get('allowed_updates')}; parse_mode по умолчанию {st.get('parse_mode', '').replace('ParseMode.', '')}. "
          "Вызовы команд в прогоне: " + ", ".join(f"{k} — {v}" for k, v in sorted(cmds.items())) +
          f"; /reset — {len(d['scenarios'].get('reset', []))} (сценарий) и {sum(p['redo'] for p in d['personas'])} после ошибки в ответе.",
          f"- Формат исходящих сообщений по правилам Bot API: ошибок разбора HTML — {vio.get('html_parse', {}).get('count', 0)}, текстов длиннее 4096 — "
          f"{vio.get('text_too_long', {}).get('count', 0)}, callback_data длиннее 64 байт — {vio.get('callback_data_len', {}).get('count', 0)}, "
          f"недопустимых URL кнопок — {vio.get('button_url_invalid', {}).get('count', 0)}, повторных ответов на callback — "
          f"{vio.get('callback_answered_twice', {}).get('count', 0)}.",
          f"- Через настоящие обработчики прошли {meta['updates_fed']} апдейтов; callback без ответа: {fcount(d, 'callback_unanswered')}, "
          f"исключений обработчиков: {d['handler_errors']}, нажатий, не дошедших до БД: {d['db']['decision_integrity']['missing']}.",
          f"- Дубли отправки: число подборок на человека и уикенд > 1 по повторным часовым запускам — "
          f"{sum(1 for k, c in Counter((x['u'], x['week']) for x in d['digests'] if x['origin'] == 'weekly').items() if c > 1)}.",
          *([f"- Команды без пройденной настройки ({len(d['scenarios']['not_ready'])} вызовов): ответ — " + "; ".join(sorted({f"«{x['reply']}»" for x in d['scenarios']['not_ready']})) + "."]
            if d['scenarios'].get('not_ready') else []),
          f"- Часовые пояса: {cnt(sum(1 for p in d['personas'] if p['tz'] != 'Europe/Moscow'), 'персона', 'персоны', 'персон')} не в Москве; рассылка ушла каждому в 19:00 по его поясу (запуски по каждому поясу и стрэгглеры).", ""]
    L += ["## 6. Ограничения прогона", "",
          "- Поведение людей — допущения (`leisure/sim/personas.py`, `actors.py`): вероятности отвала по экранам (`STEP_HAZARD`), открытия, решений, оценок, "
          "усталость и порог ухода. Новые ценности (Удовольствие, Веселье, Азарт, Покой, Близость, Смысл) персоны получают отдельным розыгрышем поверх прежних 13, чтобы когорта оставалась сравнимой с прошлыми прогонами; интересы персон заданы заранее и редко совпадают с шестью предложенными ботом, поэтому число нажатий на экране интересов — оценка сверху. Другие допущения дадут другие абсолютные доли; механика продукта от них не зависит.",
          "- Seed — 177 событий; на первом уикенде их 93, дальше 18, 8, 6, 4, 6 на уикенд: часть «пустых слотов» — недобор базы, а не логики подборки.",
          "- Не проверялись: живой Telegram (лимиты, форматирование, превью), поток сбоев сети и 429/5xx (проверены только двумя пробами на трёх сообщениях: 502 и 429), "
          "веб-приложение, переходы по URL-кнопкам («Подробнее», «Другу», календари), параллельные нажатия, несколько городов.",
          "- Время: часы подменены (`services.utcnow`), воркер вызывается с `now_utc`: среда 22:00 (сборка), четверг 19:00 по поясу каждого (подборка) с повторными запусками "
          "(ловят дубли), «План на сегодня» ежедневно в 09:00 и «Как прошло?» ежедневно в 12:00 по поясу каждого; «Иду» на сегодня после 09:00 получает дополнительный запуск "
          "плана в ближайший :00 (эмуляция часового cron). Остальные часы суток не гонялись. Пауза между сообщениями и паузы повторов 5xx отключены "
          "(`SEND_INTERVAL = 0`, `RETRY_DELAYS = (0, 0, 0)`).", ""]
    L += ["## 7. Как воспроизвести", "",
          "```", f"python -m leisure.sim.runner --users {meta['users']} --weeks {w} --seed {meta['seed']}", "cd leisure && python -m pytest tests/test_sim_smoke.py", "```",
          "Журнал вызовов — `leisure/sim/out/sim_log.jsonl` (не в git), сырые результаты — `leisure/sim/out/run_data.json`.", "",
          f"---\nДлительность прогона: {d['volatile']['duration_s']} с (единственная строка отчёта, которая меняется от запуска к запуску)."]
    return "\n".join(L) + "\n"


def date_str(meta: dict, w: int) -> str:
    from datetime import date, timedelta

    d = date(2026, 10, 25) + timedelta(days=7 * w)
    return d.strftime("%d.%m")


def write_reports(d: dict, out_dir: Path | str) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    m = build_metrics(d)
    defects, closed = build_defects(m, d)
    usab, closed_u = build_usability(m, d)
    renumber(defects, usab, closed)
    (out / "REPORT.md").write_text(render_md(m, d, defects, usab, closed, closed_u), encoding="utf-8")
    cr = compare_rows(m, d, defects, closed, usab)
    payload = {
        "meta": {k: v for k, v in d["meta"].items() if k != "log_file"},
        "norms": m["norms"],
        "spec_metrics": [{k: r[k] for k in ("id", "name", "value", "target", "status", "note")} for r in m["spec_table"]],
        "onboarding": {k: v for k, v in m["onboarding"].items() if k != "screens"},
        "digests": m["digests"], "decisions": m["decisions"], "first_go": m["first_go"], "plan": m["plan"], "retention": m["retention"],
        "rating": m["rating"], "repeats": m["repeats"], "silent": m["silent"], "scale": m["scale"], "plan_reminders": m["plan_reminders"],
        "defects": [{k: x[k] for k in ("id", "severity", "title", "count", "where")} for x in defects],
        "closed_defects": [{k: x[k] for k in ("id", "title", "evidence")} for x in closed],
        "vs_previous": [{"metric": r[0], "was": r[1], "after_fixes": r[2], "now": r[3]} for r in (cr or [])],
        "usability": [{k: x[k] for k in ("id", "priority", "title")} for x in usab],
        "findings": {k: {"count": v["count"], "users": v["users"]} for k, v in d["findings"].items()},
        "violations": {k: v["count"] for k, v in d["violations"].items()},
        "volatile": d["volatile"],
    }
    (out / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    m["_defects"], m["_usability"], m["_closed"] = defects, usab, closed
    return m


def console_summary(m: dict, d: dict) -> str:
    lines = [f"[sim] готово за {d['volatile']['duration_s']} с: {d['meta']['users']} персон, {d['meta']['weeks'] + 1} уикендов, {d['meta']['updates_fed']} апдейтов"]
    for r in m["spec_table"]:
        lines.append(f"  {r['name'][:70]:<70} {r['shown'][:40]:<40} цель {r['target']:<14} {STATUS_RU[r['status']]}")
    o = m["onboarding"]
    lines.append(f"  онбординг: нажатий min/медиана/max = {o['taps_min']}/{num(o['taps_median'], 0)}/{o['taps_max']}; до первого «Иду» медиана {num(m['first_go']['taps_median'], 0)}")
    lines.append(f"  дефектов: {len(m['_defects'])}, проблем юзабилити: {len(m['_usability'])} — подробности в leisure/sim/REPORT.md")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out" / "run_data.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    mm = write_reports(data, Path(__file__).parent)
    print(console_summary(mm, data))
