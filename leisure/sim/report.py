"""Метрики и отчёт по результатам прогона: REPORT.md (для людей) и report.json (для сравнения прогонов).

Все числа считаются из словаря результатов runner.run_simulation(); модуль не ходит ни в БД, ни в сеть.
В report.json блок "volatile" (длительность, время задач) меняется от запуска к запуску, остальное — воспроизводимо.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

STEP_ORDER = ["consent", "values", "weights", "interests", "company", "times", "budget", "aesthetics", "areas", "notes"]
STEP_RU = {
    "consent": "согласие и политика", "values": "5 главных ценностей", "weights": "8 вопросов «важно / не очень»",
    "interests": "интересы (19 категорий)", "company": "с кем ходишь", "times": "любимое время", "budget": "бюджет",
    "aesthetics": "эстетика", "areas": "район", "notes": "заметка текстом",
}
MIN_ONBOARDING_TAPS = 23   # /start, согласие, 5 ценностей, «Дальше», 8 × важно/не очень, «Готово», компания, «Дальше», бюджет, эстетика, район, «Пропустить»
SEND_RATE = 25             # сообщений в секунду (worker/send.py)
ANSWER_RU = {"values": "ценности", "company": "компания", "times": "время", "budget": "бюджет", "aesthetics": "эстетика", "areas": "район", "notes": "заметка"}
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
    m["onboarding"] = {
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
                 "plan_max_line": max((c.get("max_line", 0) for c in C if c["cmd"] == "/plan" and c.get("first_pre")), default=0),
                 "plan_lines_median": med([c["lines"] for c in C if c["cmd"] == "/plan" and c.get("first_pre")])}

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
    add("Онбординг «три минуты» (п. 3.1)", f"нажатий: min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}", "3 мин", "na",
        "времени на нажатие в симуляции нет; при 4–5 с на нажатие медиана ≈ 2,5–3 мин без чтения экранов")
    return rows


def prefill_stats(P: list[dict]) -> dict:
    ps = [p["prefill"] for p in P if p.get("prefill")]
    if not ps:
        return {"personas": 0}
    n = len(ps)
    return {"personas": n, "avg_level3": sum(p["counts"].get("3", p["counts"].get(3, 0)) for p in ps) / n,
            "avg_level2": sum(p["counts"].get("2", p["counts"].get(2, 0)) for p in ps) / n,
            "avg_level1": sum(p["counts"].get("1", p["counts"].get(1, 0)) for p in ps) / n,
            "avg_level0": sum(p["counts"].get("0", p["counts"].get(0, 0)) for p in ps) / n,
            "match_share": sum(p["match"] for p in ps) / max(1, sum(p["total"] for p in ps))}


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
def build_defects(m: dict, d: dict) -> list[dict]:
    db = d["db"]
    dd, dr, pr = db.get("decision_day", {}), db.get("digest_rows", {}), db.get("plan_reminders", {})
    out: list[dict] = []

    def add(did, sev, title, what, where, repro, count):
        out.append({"id": did, "severity": sev, "title": title, "what": what, "where": where, "repro": repro, "count": count})

    if dd.get("mismatch"):
        add("Д1", "высокая", "«Иду» сохраняется на другой день, чем показан на карточке",
            [f"В БД день решения отличается от дня на карточке у {dd['mismatch']} из {dd['checked']} решений «иду» ({pct(ratio(dd['mismatch'], dd['checked']))}). "
             f"В {dd.get('earlier', 0)} случаях день в БД раньше карточного: его выбирает `_default_day` (первая дата события не раньше «сегодня» на момент нажатия), "
             f"карточка тут ни при чём; в {dd.get('later', 0)} — позже (нажали, когда дата карточки уже прошла). Повторное решение по тому же событию день не "
             f"обновляет (старая дата остаётся) — таких среди расхождений {dd.get('redecided', 0)}.",
             "Следствие: план строится на не тот день, «План на сегодня» приходит в день, которого человек не выбирал, или не приходит.",
             *([f"Из лога: {dd['story']}"] if dd.get("story") else []),
             *[f"Пример: {x}" for x in dd.get("examples", [])[:2]]],
            "leisure/api/services.py:151-156 (_default_day), :170 (`d.day = day or d.day or _default_day(...)`); callback_data без дня — "
            "leisure/bot/callbacks.py:10-11, leisure/bot/decisions.py:33-37",
            "Онбординг во вторник; в первой подборке карточка «Воскресенье, 25 окт» у события с датами 24 и 25 октября; нажать «Иду»; "
            "`SELECT day FROM decisions` → 2026-10-24 (суббота).", dd["mismatch"])
    tot_going = sum(v["going"] for k, v in pr.items() if isinstance(v, dict))
    if tot_going:
        rem_ok = sum(v["reminded"] for k, v in pr.items() if isinstance(v, dict))
        ask_ok = sum(v.get("asked_rating", 0) for k, v in pr.items() if isinstance(v, dict))
        rows = "; ".join(f"{k}: {v['reminded']} из {v['going']}" for k, v in pr.items() if isinstance(v, dict))
        fri = pr.get("Пт", {})
        add("Д2", "высокая", "Напоминание и запрос оценки получает меньшинство «Иду»",
            [f"Напоминание «План на сегодня» пришло по {rem_ok} из {tot_going} «иду» ({pct(ratio(rem_ok, tot_going))}); по дню события — {rows}. "
             f"Запрос «Как прошло?» — по {ask_ok} из {tot_going} ({pct(ratio(ask_ok, tot_going))}).",
             "Тост на «Иду» обещает «Напомню в субботу утром», но воркер собирает план только на субботу (`plan['days'][today]`): воскресенье, будни "
             f"и «на горизонте» не напоминаются никогда, в пятницу напоминаний нет вовсе (из {fri.get('going', 0)} пятничных «иду» {fri.get('reminded', 0)} дошли только "
             "в субботу — о событии, которое уже прошло: `plan()` переносит пропавшую пятницу на первый оставшийся день). Оценка спрашивается только за Пт–Вс "
             f"прошедшего уикенда. Флаг plan_sent_at ставится при первом запуске: «Иду», нажатое в субботу после 09:00, осталось без напоминания — "
             f"{pr.get('saturday_missed_decided_after_plan_job', 0)} случаев.",
             ],
            "leisure/worker/schedules.py:122-146 (job_plan_today: флаг :136, выборка дня :141), :149-170 (job_how_was_it: фильтр :161-162); "
            "перенос дня в плане — leisure/api/services.py:282-283; тост — leisure/bot/decisions.py:21-22",
            "Нажать «Иду» на событие в воскресенье (и больше ни на что) → в субботу 09:00 `job_plan_today` не шлёт ничего (text пустой), в воскресенье — тоже.", tot_going)
    if fcount(d, "profile_resurrected") or any(s.get("profile_after_tap") for s in d["scenarios"].get("delete", [])):
        n = fcount(d, "profile_resurrected")
        add("Д3", "высокая", "После /delete нажатие на старую кнопку воссоздаёт профиль и решение без согласия",
            [f"На старую карточку после «Да, удалить всё» нажали {sum(1 for s in d['scenarios'].get('delete', []) if 'stale_tap' in s)} чел.; у {n} из них «Иду» снова создаёт "
             "строку profiles (consent_at и onboarded_at пусты) и строку decisions. Это данные, которые пользователь только что потребовал стереть "
             "(отзыв согласия, 152-ФЗ).",
             *[f"Лог: {x}" for x in fex(d, "profile_resurrected", 1)]],
            "leisure/api/services.py:163 (`get_or_create_profile` внутри set_decision); вызов из leisure/bot/decisions.py:33-37",
            "/delete → «Да, удалить всё» → нажать «Иду» на любой старой карточке → `SELECT * FROM profiles WHERE user_id=…`.", n)
    if dr.get("rows_sent"):
        add("Д4", "средняя", "Digest.opened и Digest.decisions_count никогда не заполняются",
            [f"Из {dr['rows_sent']} отправленных дайджестов в БД opened=true у {dr['opened_true']}, decisions_count>0 у {dr['decisions_count_nonzero']}, "
             f"хотя в decisions {db.get('decisions_with_activity', 0)} строк. Метрику «реакция» (п. 11) из БД посчитать нельзя; спека п. 6.7 хранит их ради конверсии."],
            "leisure/db/models.py:189-190 — поля есть, записи в bot/, worker/, api/ нет (grep по opened|decisions_count)",
            "Получить дайджест, нажать «Иду», `SELECT opened, decisions_count FROM digests`.", dr["rows_sent"])
    if dr.get("items_differ"):
        add("Д5", "средняя", "Среда 22:00 перезаписывает состав уже отправленного дайджеста",
            [f"{dr['items_differ']} из {dr['rows_sent']} строк digests: Digest.items не совпадает с тем, что реально ушло (подборки, отправленные до среды 22:00: "
             "первая после онбординга и после /reset). `job_build_digests` вызывает save_digest(sent=False), а он затирает items строки с sent_at. "
             "Журнал «что показывали» врёт, а `recently_shown_ids` берёт его для исключения повторов"
             + (f": {cnt(m['repeats']['violate_from_first'], 'событие', 'события', 'событий')} из подборки, отправленной до среды (первой или после /reset), вернулись "
                 "в следующие три недели вопреки правилу «показанное без реакции не повторять»."
                if m['repeats']['violate_from_first'] else "."),
             *[f"Пример: {x}" for x in dr.get("examples", [])[:2]]],
            "leisure/worker/schedules.py:78-81 → leisure/api/services.py:248-254 (:250 `row.items = …` без проверки sent_at)",
            "Пройти онбординг во вторник (первая подборка помечена sent), дождаться среды 22:00, сравнить digests.items с сообщением.", dr["items_differ"])
    if fcount(d, "error_toast"):
        add("Д6", "средняя", "Двойной тап по кнопке карточки даёт «Что-то пошло не так» и ERROR в логе",
            [f"{fcount(d, 'error_toast')} случаев у {fusers(d, 'error_toast')} людей: повторное нажатие той же кнопки → Telegram отвечает «message is not modified», "
             "исключение попадает в общий except. Решение при этом уже записано, но человек видит ошибку.",
             *[f"Лог: {x}" for x in fex(d, 'double_tap_error', 1)]],
            "leisure/bot/decisions.py:70-75 (edit_reply_markup без разбора TelegramBadRequest), :86-88 (общий except → тост об ошибке)",
            "Быстро нажать «Иду» дважды на одной карточке.", fcount(d, "error_toast"))
    if fcount(d, "links_lost_after_click"):
        add("Д7", "средняя", "После «Мимо» с карточки пропадают «Подробнее», «Другу», а на последней — «Весь дайджест»",
            [f"{cnt(fcount(d, 'links_lost_after_click'), 'раз', 'раза', 'раз')} у {fusers(d, 'links_lost_after_click')} человек. Клавиатура пересобирается как `base[:1] + причины`, "
             "а после выбора причины — `rows[:1]`: второй ряд (ссылки) и футер выбрасываются.",
             *[f"Лог: {x}" for x in fex(d, 'links_lost_after_click', 2)]],
            "leisure/bot/decisions.py:72 и :79", "Нажать «Мимо» на последней карточке подборки и выбрать причину.", fcount(d, "links_lost_after_click"))
    if m["digests"]["no_interest_button"]:
        add("Д8", "средняя", "На карточке нет кнопки «Интересно» (требование F6)",
            [f"В {m['digests']['sent']} отправленных дайджестах ни одной карточки с «Интересно». Обработчик `d:i:` и вес 0.9 в обучении есть, кнопки нет: "
             f"{cnt(m['decisions']['wanted_interest'], 'раз', 'раза', 'раз')} ({m['decisions']['wanted_interest_users']} чел.) персона хотела отметить «интересно» и не смогла."],
            "leisure/worker/messages.py:66-73 (card_keyboard: Иду / Может быть / Мимо); спека п. 4 F6, п. 6.5",
            "Получить любую подборку и посмотреть клавиатуру карточки.", m["decisions"]["wanted_interest"])
    sens = d.get("sensitivity", {})
    if sens.get("personas"):
        ch = sens["changed"]
        add("Д9", "средняя", "Ответы «с кем ходишь», «куда готов ехать», дети и заметка не влияют на подборку",
            [f"Пересчёт подборки четверга для {sens['personas']} профилей при смене одного параметра: компания — {ch.get('company', 0)}, район — {ch.get('areas', 0)}, "
             f"флаг «с детьми» — {ch.get('kids', 0)}, заметка — {ch.get('notes', 0)} профилей изменили состав. Контроль: бюджет — {ch.get('budget (контроль)', 0)}, "
             f"эстетика — {ch.get('aesthetics (контроль)', 0)}, время — {ch.get('times (контроль)', 0)}.",
             "Три экрана онбординга (компания, район, заметка) собирают ответ, который нигде не используется; «с детьми» не повышает события для детей."],
            "leisure/core/scoring.py:73-140 читает только aesthetics, adults30, budget, times; params.company/areas/kids и Profile.notes не используются",
            "Два профиля, отличающихся только company/areas, → `GET /api/digest/{id}/preview` даёт одинаковый состав.", sum(1 for k in ("company", "areas", "kids", "notes") if not ch.get(k)))
    if fcount(d, "text_ignored") or fcount(d, "command_eaten_by_notes"):
        add("Д10", "средняя", "Свободный текст и команды на шагах онбординга: молчание или «съеденная» команда",
            [f"Текст на шаге кнопок — без ответа бота: {cnt(fcount(d, 'text_ignored'), 'раз', 'раза', 'раз')}. На шаге «заметка» команда /help принята за текст заметки "
             f"и онбординг завершён: {cnt(fcount(d, 'command_eaten_by_notes'), 'раз', 'раза', 'раз')}. Fallback-обработчика нет, handled=False.",
             *[f"Лог: {x}" for x in (fex(d, 'text_ignored', 1) + fex(d, 'command_eaten_by_notes', 1))]],
            "leisure/bot/onboarding.py:211-213 (`@router.message(Onb.notes, F.text)` стоит раньше commands.router), "
            "leisure/bot/main.py:21-26 (нет общего message-обработчика)", "На шаге «Напиши пару слов» отправить /help; на шаге ценностей — любой текст.",
            fcount(d, "text_ignored") + fcount(d, "command_eaten_by_notes"))
    if fcount(d, "stale_button_dead"):
        add("Д11", "средняя", "После перезапуска бота старые кнопки онбординга молчат",
            [f"{fcount(d, 'stale_button_dead')} из {len(d['scenarios'].get('fsm_restart', {}).get('after', []))} нажатий на старый экран после рестарта: "
             "апдейт не обработан и на callback нет ответа (у человека бесконечный индикатор загрузки). До рестарта те же кнопки работали. "
             "FSM — MemoryStorage, фильтры `Onb.*` не пускают callback без состояния, общего обработчика с `cb.answer()` нет.",
             *[f"Лог: {x}" for x in fex(d, 'stale_button_dead', 1)]],
            "leisure/bot/main.py:22 (MemoryStorage), leisure/bot/onboarding.py:77,127,139,… (callback-обработчики с состоянием)",
            "Начать онбординг, перезапустить `python -m leisure.bot.main`, нажать кнопку на старом экране.", fcount(d, "stale_button_dead"))
    bl = db.get("blocked", [])
    if bl:
        add("Д12", "средняя", "Заблокировавший бота остаётся активным и получает попытки отправки",
            [f"{len(bl)} заблокировавших; профилей с active=true после блокировки: {db.get('profiles_active_after_block', 0)}. Ни одно сообщение не ушло → "
             "дайджест не помечается отправленным и собирается заново на каждом часовом запуске до воскресенья (до ~77 раз за уикенд на человека). "
             "Внутри одной попытки `send_with_bot` после Forbidden переходит к следующему сообщению подборки и снова получает отказ (6–7 отклонённых вызовов на попытку). "
             f"В прогоне при 3–4 запусках в неделю: {sum(b.get('failed_digest_attempts', 0) for b in bl)} отклонённых попыток отправить подборку, "
             f"{sum(b['failed_sends'] for b in bl)} отклонённых вызовов."],
            "leisure/worker/send.py:36-38 (только лог), leisure/worker/schedules.py:112-115 (`if not send_sync(...): return False`)",
            "Заблокировать бота и посмотреть логи воркера в четверг: пересборка каждый час.", len(bl))
    if m["digests"]["already_started"]:
        add("Д13", "низкая", "Подборка пришла с событиями, которые уже начались",
            [f"{cnt(m['digests']['already_started'], 'карточка', 'карточки', 'карточек')}: подборка при онбординге/по /digest строится по дате, без учёта времени суток; в воскресенье вечером "
             "приходят события «Воскресенье, …11:00».", *[f"Лог: {x}" for x in fex(d, 'card_already_started', 2)]],
            "leisure/bot/onboarding.py:251 и leisure/bot/commands.py:30 (`local_today` → date); leisure/api/services.py:48-51 (trim_past по дате)",
            "Пройти онбординг в воскресенье вечером.", m["digests"]["already_started"])
    v = d.get("violations", {}).get("button_url_long")
    if v:
        add("Д14", "низкая", "URL кнопки «Другу» длиннее 2 000 символов",
            [f"{cnt(v['count'], 'карточка', 'карточки', 'карточек')} с URL > 2048 символов (до 2,5 тыс.: в t.me/share/url кириллица кодируется по 6 символов на букву). "
             "Лимит Telegram на URL кнопки в документации не указан, на практике — 2048; это риск BUTTON_URL_INVALID, который уронит всю карточку. "
             "Нужно проверить на живом боте."],
            "leisure/worker/messages.py:71-72 + leisure/core/links.py:83-86", "Собрать подборку, посмотреть длину url кнопки «Другу».", v["count"])
    rp = m["repeats"]
    if rp["violate_no_reaction_3"] - rp["violate_from_first"] > 0 or rp["violate_skip"]:
        add("Д15", "средняя", "Событие вернулось в подборку вопреки правилам исключения (п. 8)",
            [f"Показано повторно в течение 3 дайджестов без реакции (не из подборок, затёртых средой, см. Д5): {rp['violate_no_reaction_3'] - rp['violate_from_first']}; "
             f"после «мимо»/«интересно»: {rp['violate_skip']}."],
            "leisure/api/services.py:198-206 (recently_shown_ids), leisure/core/recommend.py:105", "См. REPORT, раздел повторов.", rp["violate_no_reaction_3"] + rp["violate_skip"])
    fp = d["scenarios"].get("fault_probe", {}).get("server_error")
    if fp and fp["lost"]:
        add("Д19", "средняя", "Временный сбой Telegram (5xx, сеть) навсегда теряет карточку подборки",
            [f"Проба: из трёх сообщений второе получило 502 Bad Gateway — `send_with_bot` вернул {fp['returned']}, доставлено {fp['delivered']}, потеряно {fp['lost']}: "
             "повтора нет (повторяется только 429), а `job_send_digests` считает рассылку успешной, раз ушло хотя бы одно сообщение, и помечает подборку отправленной — "
             "недостающая карточка не будет дослана. 429 при этом обрабатывается (проба с TelegramRetryAfter: доставлено "
             f"{len(d['scenarios'].get('fault_probe', {}).get('retry_after', {}).get('delivered', []))} из 3)."],
            "leisure/worker/send.py:39-41 (`except Exception: log.exception; break`), leisure/worker/schedules.py:113-115 (`if not send_sync(...)` — только «ни одного»)",
            "Подставить в aiogram-сессию ошибку 502 на второй вызов sendMessage в рассылке (см. Sim.fault_probe в leisure/sim/runner.py).", 1)
    sc = m["scale"]
    if sc["minutes_for_10k"] and sc["minutes_for_10k"] > 15:
        add("Д16", "низкая", "Отправка дайджеста 10 000 пользователям не укладывается в 15 минут (п. 10)",
            [f"В среднем {num(sc['avg_messages_per_digest'], 1)} сообщений на подборку (заголовок + карточки), лимит отправки {SEND_RATE} сообщ./с → "
             f"10 000 человек ≈ {num(sc['minutes_for_10k'], 0)} мин; за 15 минут успеть можно ≈ {sc['max_users_in_15min']} человек. "
             "Нужно или объединять сообщения, или добиваться повышенного лимита, или растягивать окно рассылки."],
            "leisure/worker/send.py:19 (SEND_INTERVAL = 1/25), leisure/worker/schedules.py:87-94", "Умножить число сообщений на подборку на 10 000 и разделить на 25.", 1)
    if d["db"].get("profile_mismatch"):
        mm = d["db"]["profile_mismatch"]
        add("Д17", "низкая", "Ошибка в ответе онбординга исправить нельзя — сохраняется неверный профиль",
            [f"У {sum(1 for p in d['personas'] if p.get('misclick') and p['misclick'].get('recovery') == 'continue')} людей, нажавших не ту кнопку и не пожелавших начинать заново, "
             f"в БД лежат неверные ответы: {', '.join(f'{ANSWER_RU.get(k, k)} — {v}' for k, v in sorted(mm.items()))}."], "leisure/bot/onboarding.py:157-208 (шаги без «Назад»)", "Выбрать бюджет «до 1 000 ₽» по ошибке и дойти до конца.", sum(mm.values()))
    if "localhost" in (d["meta"].get("web_base_url_original") or "") or not d["meta"].get("web_base_url_original"):
        add("Д18", "низкая", "Значение WEB_BASE_URL по умолчанию (localhost) делает онбординг невозможным",
            ["С WEB_BASE_URL=http://localhost:8000 кнопка «Политика обработки данных» (URL) в первом же сообщении, как правило, отклоняется Telegram "
             "(BUTTON_URL_INVALID: localhost не принимается; проверить на живом боте) — бот не пришлёт ни согласие, ни подборки. "
             "Симулятор подставил публичный домен; в проде переменная обязана быть задана."],
            "leisure/settings.py:35, leisure/bot/onboarding.py:42,58", "Запустить бота без WEB_BASE_URL и отправить /start.", 1)
    order = {"высокая": 0, "средняя": 1, "низкая": 2}
    out.sort(key=lambda x: (order[x["severity"]], int(x["id"][1:])))
    return out


def build_usability(m: dict, d: dict) -> list[dict]:
    o, dg, dec = m["onboarding"], m["digests"], m["decisions"]
    out: list[dict] = []

    def add(uid, pri, title, evidence, advice):
        out.append({"id": uid, "priority": pri, "title": title, "evidence": evidence, "advice": advice})

    if o["completed"]:
        lost = o["started"] - o["completed"]
        top = max(o["funnel"], key=lambda f: f["left"])
        n1 = sum(1 for s in o["screens"] if s.startswith("Шаг 1 из 5"))
        seq = " → ".join(s[:28] for s in o["screens"][:2]) + " … " + " → ".join(s[:28] for s in o["screens"][-6:])
        add("У1", 1, "Онбординг длиннее обещанного, а счётчик шагов не соответствует экранам",
            [f"Приветствие обещает «три минуты». Нужно минимум {cnt(o['theoretical_min'], 'нажатие', 'нажатия', 'нажатий')}, у прошедших — от {o['taps_min']} до {o['taps_max']}, медиана {num(o['taps_median'], 0)} "
             f"(у не ошибавшихся — {num(o['taps_clean_median'], 0)}); экранов {len(o['screens'])}.",
             f"Не дошли {lost} из {o['started']} ({pct(ratio(lost, o['started']))}); больше всего уходят на шаге «{STEP_RU[top['step']]}» ({top['left']}).",
             f"Нумерация: «Шаг 1 из 5» стоит на {n1} экранах подряд, затем «Шаг 2», «Шаг 3», потом четыре экрана без номера (время, бюджет, эстетика, район), "
             f"«Шаг 4», «Шаг 5» — человек не видит, сколько осталось. Экраны по порядку: {seq}",
             f"До первого «Иду» от первого /start: медиана {num(m['first_go']['taps_median'], 0)} (после онбординга ещё {num(m['first_go']['after_onb_median'], 0)})."],
            "Свернуть онбординг до 3–4 экранов, общий прогресс «N из 10», первую подборку показывать после ценностей, остальное спрашивать позже.")
        add("У2", 2, "Список интересов: 19 кнопок в столбик и цикл из четырёх состояний",
            [f"На экране {o['interest_buttons']} кнопок в {o['interest_rows']} рядах (по одной в ряд) — это {num(o['interest_rows'] * 0.6, 0)}+ экранов прокрутки на телефоне. "
             f"Каждое нажатие сдвигает уровень по кругу «— → иногда → интересно → в первую очередь → —»: понизить с «в первую очередь» до «интересно» — 3 нажатия, "
             f"убрать категорию с «интересно» — 2.",
             f"Персоны правили в среднем до {num(o['interest_edits_median'], 0)} категорий (макс. {o['interest_edits_max']}), на экран приходится "
             f"{pct(o['interest_share_of_taps'])} всех нажатий онбординга; восемь вопросов «важно / не очень» — ещё {pct(o['weights_share_of_taps'])}.",
             *([f"Предзаполнение по ценностям совпало с заданными персонами интересами лишь в {pct(o['prefill']['match_share'])} категорий; на «в первую очередь» "
                f"в среднем {num(o['prefill']['avg_level3'], 1)} из 19 категорий, на «—» — {num(o['prefill']['avg_level0'], 1)}: уровень 3 перестаёт быть приоритетом, а "
                "ненужные категории человек должен обнулять сам."] if o["prefill"].get("personas") else [])],
            "Показать 5–6 предзаполненных категорий с кнопками «убрать / добавить», остальное — «Показать все»; прямой выбор уровня вместо цикла.")
    if o["all_screens_checked"]:
        add("У3", 3, "Нельзя вернуться или отменить шаг онбординга",
            [f"Кнопок «Назад / Отмена / Изменить» на {o['back_screens']} из {o['all_screens_checked']} проверенных экранов онбординга. "
             f"{fcount(d, 'no_back_after_misclick')} человек нажали не ту кнопку; единственный выход — /reset с самого начала "
             f"(у {sum(1 for p in d['personas'] if p['redo'] and p['completed'])} это стоило {', '.join(str(p['onboarding_taps']) for p in d['personas'] if p['redo'] and p['completed'])} нажатий всего), "
             "иначе неверный ответ остаётся в профиле.",
             *[f"Лог: {x}" for x in fex(d, 'no_back_after_misclick', 1)]],
            "Кнопка «← Назад» на каждом экране и общий «Отмена».")
    if dec["wanted_interest"]:
        total_wish = dec["wanted_interest"]
        add("У4", 4, "Нет кнопки «Интересно» на карточке (F6)",
            [f"{cnt(total_wish, 'раз', 'раза', 'раз')} персоны пытались отметить «интересно» ({dec['wanted_interest_users']} чел.); это {pct(ratio(total_wish, total_wish + dec['total']))} всех реакций, "
             "которые захотели дать. Вместо этого они нажимали «Может быть» (сигнал 0,4 вместо 0,9) или молчали."], "Добавить четвёртую кнопку, либо объяснить «Может быть».")
    if dec["skip_total"]:
        add("У5", 5, "«Мимо» сразу спрашивает причину и перекраивает карточку",
            [f"{dec['skip_total']} нажатий «Мимо»: из них причину выбрали {dec['skip_with_reason']}, «Без причины» — {dec['skip_no_reason_button']}, "
             f"оставили открытыми кнопки причин {dec['skip_unanswered']}. Один отказ = 2 нажатия, клавиатура карточки вырастает до 5 рядов "
             "(ряд из 3 кнопок + 4 ряда причин) и остаётся такой, пока не выбрать причину.",
             f"Тост «Понял. Почему мимо?» не объясняет, что причина необязательна. Ссылки «Подробнее/Другу» после этого пропадают ({fcount(d, 'links_lost_after_click')} раз)."],
            "Причину — отдельным необязательным сообщением или одной строкой «Почему? дорого · далеко · не моё»; ссылки оставить.")
    if m["silent"]["user_weeks"]:
        add("У6", 6, "Подборки худеют, а при пустом составе бот молчит",
            [f"{m['silent']['silent']} из {m['silent']['user_weeks']} человеко-недель ({pct(m['silent']['share'])}) прошли без единой подборки; "
             f"в {m['silent']['logged_nothing']} случаях воркер сам записал в лог «нечего отправить»: при пустом составе он ничего не шлёт и ничего не объясняет. "
             "В среднем пустых слотов из 5: " + ", ".join(
                 f"неделя {w} — {num(v['empty'], 1)}" for w, v in dg["by_week"].items() if v.get("digests")) + ".",
             f"Сообщение «ничего не нашлось» увидели {cnt(m['silent']['empty_notices'], 'раз', 'раза', 'раз')} (только в онбординге и по /digest)."],
            "Писать «на этих выходных мало подходящего, вот ближайшее/что включить» или показывать лучшее из «на горизонте»; слот «пт вечер» пуст всегда, когда в базе нет пятничных событий.")
    if dg["multi_day_cards"]:
        add("У7", 7, "Нельзя выбрать день у события, идущего несколько дней",
            [f"{dg['multi_day_cards']} из {dg['total_cards']} карточек ({pct(ratio(dg['multi_day_cards'], dg['total_cards']))}) — события с несколькими датами внутри уикенда; "
             "карточка показывает один день, кнопки дня нет (callback_data `d:g:<id>` без даты), поэтому день потом угадывается по часам нажатия (см. Д1)."],
            "Кнопки «Сб / Вс» под многодневными событиями.")
    if dg["sent"]:
        add("У8", 8, "«Весь дайджест» висит только на последней карточке и исчезает после «Мимо»",
            [f"Кнопка есть в 1 из ~{num(dg['avg_cards'], 1)} карточек подборки; заголовок без кнопок. После «Мимо» на последней карточке она пропадает "
             f"({fcount(d, 'links_lost_after_click')} случаев потери ссылок). Страница, на которую она ведёт, в этой версии не реализована (веб — недели 5–6 плана).",
             ], "Кнопки под заголовком подборки: «Весь дайджест», «Мой план».")
    if fcount(d, "text_ignored"):
        add("У9", 9, "Свободный текст в чат игнорируется", [f"{cnt(fcount(d, 'text_ignored'), 'раз', 'раза', 'раз')} бот не ответил на текст. Человек не получает даже «я принимаю только кнопки»."],
            "Общий обработчик: подсказка и возврат к текущему шагу.")
    if dg["resent_no_status"]:
        add("У10", 10, "Повторно присланная карточка не показывает прежнее решение",
            [f"{cnt(dg['resent_no_status'], 'карточка', 'карточки', 'карточек')}, присланных по /digest и после /reset, пришли без отметки ●, хотя решение по ним уже было; человек видит чистые кнопки и не понимает, что уже отвечал."], "Рисовать ● из БД при отправке.")
    if m["plan"]["plan_cmd_total"]:
        add("U11".replace("U", "У"), 11, "/plan приходит одним моноширинным блоком",
            [f"Ответ /plan в блоке `<pre>`: до {m['plan']['plan_max_line']} символов в строке, строк в медиане {num(m['plan']['plan_lines_median'], 0)}; в Telegram такие строки не переносятся и уходят за экран."],
            "Плоский текст с переносами, события — отдельными карточками (они уже есть).")
    if dg["already_started"]:
        add("У12", 12, "Подборка показывает уже начавшиеся события", [f"{cnt(dg['already_started'], 'карточка', 'карточки', 'карточек')} (см. Д13)."], "Отсекать события по времени начала.")
    if dg["messy_time"] or dg["plan_messy_lines"]:
        add("У13", 13, "Время события — сырой текст источника, а не время выбранного дня",
            [f"{dg['messy_time']} из {dg['all_cards']} карточек ({pct(ratio(dg['messy_time'], dg['all_cards']))}) показывают расписание сразу на несколько дат "
             "(«23.10 — 20:00; 24.10 и 25.10 — 17:00 и 20:00») под заголовком с одним днём; в «Плане на сегодня» так же: "
             f"{dg['plan_messy_lines']} из {dg['plan_lines']} строк плана ({pct(ratio(dg['plan_messy_lines'], dg['plan_lines']))}). Что именно в этот день — человеку приходится разбирать самому."],
            "Подставлять время выбранного дня (`event_times(ev, day)` уже умеет) или показывать «ещё даты: …» отдельной строкой.")
    out.sort(key=lambda x: x["priority"])
    return out


# Порядок вывода: по важности внутри серьёзности. Идентификаторы присваиваются уже после сортировки, ссылки «Дn» в текстах пересчитываются.
DEF_ORDER = ["Д1", "Д2", "Д3", "Д9", "Д8", "Д7", "Д6", "Д5", "Д4", "Д19", "Д12", "Д11", "Д10", "Д15", "Д13", "Д14", "Д16", "Д17", "Д18"]
USAB_ORDER = ["У1", "У2", "У7", "У3", "У4", "У5", "У6", "У13", "У8", "У9", "У10", "У11", "У12"]


def renumber(defects: list[dict], usab: list[dict]) -> None:
    dmap: dict[str, str] = {}
    ordered = sorted(defects, key=lambda x: DEF_ORDER.index(x["id"]) if x["id"] in DEF_ORDER else 99)
    for i, x in enumerate(ordered, 1):
        dmap[x["id"]] = f"Д{i}"
    pat = re.compile(r"Д\d+")

    def sub(s: str) -> str:
        return pat.sub(lambda mm: dmap.get(mm.group(0), mm.group(0)), s)

    for x in ordered:
        x["what"] = [sub(t) for t in x["what"]]
        x["repro"], x["title"] = sub(x["repro"]), sub(x["title"])
    for x in ordered:
        x["id"] = dmap[x["id"]]
    defects[:] = ordered
    uo = sorted(usab, key=lambda x: USAB_ORDER.index(x["id"]) if x["id"] in USAB_ORDER else 99)
    for i, x in enumerate(uo, 1):
        x["evidence"] = [sub(t) for t in x["evidence"]]
        x["advice"] = sub(x["advice"])
        x["id"], x["priority"] = f"У{i}", i
    usab[:] = uo


# ───────────────────────── вывод ─────────────────────────
def render_md(m: dict, d: dict, defects: list[dict], usab: list[dict]) -> str:
    meta, o, dg, dec, pl, rk = d["meta"], m["onboarding"], m["digests"], m["decisions"], m["plan"], m["rating"]
    L: list[str] = []
    w = meta["weeks"]
    L += ["# Отчёт симуляции пользователей — «Планировщик досуга»", "",
          f"Прогон: seed `{meta['seed']}`, {meta['users']} персон ({', '.join(f'{k} {v}' for k, v in sorted(meta['archetypes'].items()))}), "
          f"{w + 1} уикендов (23.10 – {(date_str(meta, w))}), {meta['updates_fed']} апдейтов через `Dispatcher.feed_update`, "
          f"{meta['world_calls']} исходящих вызовов Bot API (в поддельной сессии, без сети). События: seed {meta['events_seeded']} шт.", "",
          f"Команда: `python -m leisure.sim.runner --users {meta['users']} --weeks {w} --seed {meta['seed']}`. База `{meta['db_name']}` создаётся и удаляется прогоном, база разработки не затрагивается. "
          "Один seed — один и тот же отчёт (кроме строки о длительности в конце).", "",
          "> **Как читать.** Код продукта — настоящий: бот, фильтры, FSM, клавиатуры, задачи воркера и БД. Люди — модель: ответы онбординга, вероятности отвала, "
          "открытия, решений и оценок заданы допущениями в `personas.py` (п. «Ограничения»). Поэтому абсолютные доли (активация, реакция, удержание) — "
          "«что будет при таком поведении», а не прогноз; надёжны находки о механике продукта: дефекты и юзабилити ниже подтверждены логом.", ""]
    L += ["## 1. Метрики п. 11 спеки", "",
          table(["Метрика", "Значение", "Цель", "Статус", "Примечание"],
                [[r["name"], r["shown"], r["target"], STATUS_RU[r["status"]], r["note"]] for r in m["spec_table"]]), ""]
    L += ["## 2. Операционные метрики", "", "### Показатели против норм спеки", "",
          table(["Показатель", "Значение", "Норма", "Статус", "Примечание"], [[r["name"], r["value"], r["norm"], STATUS_RU[r["status"]], r["note"]] for r in m["norms"]]), "",
          "### Онбординг", "",
          f"Начали {o['started']}, прошли {o['completed']} ({pct(m['activation'])}). Нажатий (включая /start и текст заметки): "
          f"**min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}** (теоретический минимум по коду — {o['theoretical_min']}; "
          f"без ошибок и повторов: min {o['taps_clean_min']}, медиана {num(o['taps_clean_median'], 0)}, max {o['taps_clean_max']}).", "",
          table(["Шаг", "Дошли до экрана", "Бросили на нём", "Нажатий в среднем"],
                [[STEP_RU[f["step"]], f["reached"], f["left"], num(o["step_means"].get(f["step"], 0), 1)] for f in o["funnel"]]), "",
          "### Решения и причины", "",
          table(["Статус", "Нажатий", "Доля"], [[k, v, pct(ratio(v, dec["total"]))] for k, v in sorted(dec["by_status"].items(), key=lambda kv: -kv[1])]
                + [["интересно (кнопки нет)", f"0 (хотели {dec['wanted_interest']})", "—"]]), "",
          f"«Мимо» — {dec['skip_total']}; причины: " + (", ".join(f"{k or 'без причины'} {v}" for k, v in sorted(dec['reasons'].items(), key=lambda kv: -kv[1])) or "—")
          + f"; причину не выбрали вовсе: {dec['skip_unanswered']}.", "",
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
          table(["День события «Иду»", "Всего «Иду»", "Пришло напоминание", "Спросили оценку"],
                [[k, v["going"], v["reminded"], v["asked_rating"]] for k, v in m["plan_reminders"].items() if isinstance(v, dict)]), "",
          "### Масштаб и целостность", "",
          f"Сообщений на подборку в среднем {num(m['scale']['avg_messages_per_digest'], 1)} → 10 000 человек при 25 сообщ./с ≈ {num(m['scale']['minutes_for_10k'], 0)} мин (цель п. 10 — 15 мин). "
          f"Целостность: нажатий не найдено в БД — {d['db']['decision_integrity']['missing']}, расхождений статуса/причины — {d['db']['decision_integrity']['mismatch']} "
          f"из {d['db']['decision_integrity']['checked']}; профилей с неверными ответами из-за ошибки без «Назад» — {sum(d['db'].get('profile_mismatch', {}).values())}. "
          f"Нарушения правил Bot API в поддельной сессии: " + (", ".join(f"{k} — {v['count']}" for k, v in sorted(d['violations'].items())) or "нет") + ". "
          f"Исключения обработчиков бота: {d['handler_errors']}; записи ERROR/WARNING продукта: {len(d['log_errors'])}.", ""]
    L += ["## 3. Дефекты продукта", "", "Каждый подтверждён прогоном; «где» — файл и строки (на момент прогона), «как воспроизвести» — минимальные шаги.", ""]
    for x in defects:
        L += [f"### {x['id']} [{x['severity']}] {x['title']}", ""]
        L += [f"- {line}" for line in x["what"]]
        L += [f"- **Где:** {x['where']}", f"- **Как воспроизвести:** {x['repro']}", ""]
    if not defects:
        L += ["Дефектов не найдено.", ""]
    L += ["## 4. Проблемы юзабилити (по убыванию важности)", ""]
    for x in usab:
        L += [f"### {x['id']}. {x['title']}", ""]
        L += [f"- {line}" for line in x["evidence"]]
        L += [f"- **Что сделать:** {x['advice']}", ""]
    if not usab:
        L += ["Проблем не найдено.", ""]
    L += ["## 5. Что подтвердилось и что нет (контрольные проверки)", ""]
    vio = d.get("violations", {})
    st = d["scenarios"].get("startup", {})
    cmds = Counter(c["cmd"] for c in d["commands"])
    L += [f"- Запуск бота выполнен настоящим `leisure.bot.main.run()` (токен, класс Bot и start_polling подменены): меню команд {', '.join('/' + c for c in st.get('commands', []))}; "
          f"allowed_updates {st.get('allowed_updates')}; parse_mode по умолчанию {st.get('parse_mode', '').replace('ParseMode.', '')}. "
          "Вызовы команд в прогоне: " + ", ".join(f"{k} — {v}" for k, v in sorted(cmds.items())) +
          f"; /reset — {len(d['scenarios'].get('reset', []))} (сценарий) и {sum(p['redo'] for p in d['personas'])} после ошибки в ответе.",
          f"- Формат исходящих сообщений по правилам Bot API: ошибок разбора HTML — {vio.get('html_parse', {}).get('count', 0)}, текстов длиннее 4096 — "
          f"{vio.get('text_too_long', {}).get('count', 0)}, callback_data длиннее 64 байт — {vio.get('callback_data_len', {}).get('count', 0)}, "
          f"недопустимых URL кнопок — {vio.get('button_url_invalid', {}).get('count', 0)}, повторных ответов на callback — "
          f"{vio.get('callback_answered_twice', {}).get('count', 0)}.",
          f"- Через настоящие обработчики прошли {meta['updates_fed']} апдейтов; callback без ответа: {fcount(d, 'callback_unanswered')} (сценарий {m.get('_stale_ref', '')}), "
          f"исключений обработчиков: {d['handler_errors']}, нажатий, не дошедших до БД: {d['db']['decision_integrity']['missing']}.",
          f"- Дубли отправки: число подборок на человека и уикенд > 1 по повторным часовым запускам — "
          f"{sum(1 for k, c in Counter((x['u'], x['week']) for x in d['digests'] if x['origin'] == 'weekly').items() if c > 1)}.",
          *([f"- Команды без пройденной настройки ({len(d['scenarios']['not_ready'])} вызовов): ответ — " + "; ".join(sorted({f"«{x['reply']}»" for x in d['scenarios']['not_ready']})) + "."]
            if d['scenarios'].get('not_ready') else []),
          f"- Часовые пояса: {cnt(sum(1 for p in d['personas'] if p['tz'] != 'Europe/Moscow'), 'персона', 'персоны', 'персон')} не в Москве; рассылка ушла каждому в 19:00 по его поясу (запуски по каждому поясу и стрэгглеры).", ""]
    L += ["## 6. Ограничения прогона", "",
          "- Поведение людей — допущения (`leisure/sim/personas.py`, `actors.py`): вероятности отвала по экранам (`STEP_HAZARD`), открытия, решений, оценок, "
          "усталость и порог ухода. Другие допущения дадут другие абсолютные доли; механика продукта от них не зависит.",
          "- Seed — 177 событий; на первом уикенде их 93, дальше 18, 8, 6, 4, 6 на уикенд: часть «пустых слотов» — недобор базы, а не логики подборки.",
          "- Не проверялись: живой Telegram (лимиты, форматирование, превью), поток сбоев сети и 429/5xx (проверены только двумя пробами на трёх сообщениях: 502 и 429), "
          "веб-приложение, переходы по URL-кнопкам («Подробнее», «Другу», календари), параллельные нажатия, несколько городов.",
          "- Время: часы подменены (`services.local_today`), воркер вызывается с `now_utc` в ключевые моменты (ср 22:00, чт 19:00, сб 09:00, пн 12:00 по поясу каждого) "
          "плюс повторные «часовые» запуски; не гонялся каждый час. Пауза между сообщениями отключена (`SEND_INTERVAL = 0`).", ""]
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
    defects, usab = build_defects(m, d), build_usability(m, d)
    renumber(defects, usab)
    m["_stale_ref"] = next((x["id"] for x in defects if "старые кнопки онбординга" in x["title"]), "")
    (out / "REPORT.md").write_text(render_md(m, d, defects, usab), encoding="utf-8")
    payload = {
        "meta": {k: v for k, v in d["meta"].items() if k != "log_file"},
        "norms": m["norms"],
        "spec_metrics": [{k: r[k] for k in ("id", "name", "value", "target", "status", "note")} for r in m["spec_table"]],
        "onboarding": {k: v for k, v in m["onboarding"].items() if k != "screens"},
        "digests": m["digests"], "decisions": m["decisions"], "first_go": m["first_go"], "plan": m["plan"], "retention": m["retention"],
        "rating": m["rating"], "repeats": m["repeats"], "silent": m["silent"], "scale": m["scale"], "plan_reminders": m["plan_reminders"],
        "defects": [{k: x[k] for k in ("id", "severity", "title", "count", "where")} for x in defects],
        "usability": [{k: x[k] for k in ("id", "priority", "title")} for x in usab],
        "findings": {k: {"count": v["count"], "users": v["users"]} for k, v in d["findings"].items()},
        "violations": {k: v["count"] for k, v in d["violations"].items()},
        "volatile": d["volatile"],
    }
    (out / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    m["_defects"], m["_usability"] = defects, usab
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
