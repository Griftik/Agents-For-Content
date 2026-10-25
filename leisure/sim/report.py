"""Метрики и отчёт по прогону симулятора приложения «Успею» (версия 2): REPORT.md для людей и report.json для сравнения прогонов.

Все числа считаются из словаря результатов app.sim.run_app_simulation(); модуль не ходит ни в БД, ни в сеть. В report.json блок
"volatile" меняется от запуска к запуску, остальное воспроизводимо при том же seed."""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path

TARGET_TAPS = 12            # web/FLOW-ONBOARDING.md: не больше 12 нажатий у типичного, 9 при «ничего не меняю»
MIN_TAPS = 8                # согласие 1, «Начать» 1, пять ценностей, «Показать подборку» 1 (9 — с бюджетом строкой)
EVENING_TARGET_TAPS = 3     # «освободился вечер»: до «Иду» не больше трёх нажатий
STATUS_RU = {"ok": "достигнута", "fail": "не достигнута", "na": "нельзя оценить"}
SEV_ORDER = {"высокая": 0, "средняя": 1, "низкая": 2}
DAY_RU = {"today": "Сегодня", "tomorrow": "Завтра", "week": "Неделя"}
SEG_RU = {"leisure": "Досуг", "business": "Дело", "all": "Всё"}
GROWTH_NAMES = {"invite_share": "Доля «иду» с приглашением", "acceptance": "Принятие приглашения", "activation_invited": "Активация приглашённых",
                "onboarding_invited": "Онбординг приглашённых", "new_via_friends": "Доля новых через друзей", "virality": "Коэффициент виральности",
                "positive_experience": "Положительный опыт", "recommendation": "Рекомендация", "together_going": "Совместные походы"}
GROWTH_FORMULA = {"invite_share": "приглашений / решений «иду»", "acceptance": "открывших с «иду» или «может быть» / всех открывших",
                  "activation_invited": "согласие + решение / открывших без профиля", "onboarding_invited": "полный профиль за 2 недели / принявших",
                  "new_via_friends": "source ∈ {invite, ref, share} / все новые", "virality": "новых через друзей / активных",
                  "positive_experience": "оценок 4–5 / всех оценок", "recommendation": "нажали «Поделиться» / показов момента",
                  "together_going": "«иду» вдвоём / всех «иду»"}
GROWTH_TARGET = {"invite_share": 0.15, "acceptance": 0.30, "activation_invited": 0.60, "onboarding_invited": 0.40, "new_via_friends": 0.20,
                 "virality": 0.2, "positive_experience": 0.70, "recommendation": 0.10, "together_going": None}


# ───────────────────────── помощники ─────────────────────────
def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if 11 <= n % 100 <= 19:
        return many
    r = n % 10
    return one if r == 1 else few if 2 <= r <= 4 else many


def cnt(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural(n, one, few, many)}"


def ratio(a, b) -> float | None:
    return (a / b) if b else None


def pct(x: float | None, d: int = 0) -> str:
    return "н/д" if x is None else f"{x * 100:.{d}f} %".replace(".", ",")


def num(x: float | None, d: int = 1) -> str:
    return "н/д" if x is None else f"{x:.{d}f}".replace(".", ",")


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
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def fcount(d: dict, code: str) -> int:
    return int(d.get("findings", {}).get(code, {}).get("count", 0))


def fex(d: dict, code: str, n: int = 2) -> list[str]:
    return d.get("findings", {}).get(code, {}).get("examples", [])[:n]


def load_baseline(name: str = "baseline_v4.json") -> dict | None:
    p = Path(__file__).with_name(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def growth_value(x: dict | None) -> str:
    if not x:
        return "н/д"
    return f"{pct(x['value'], 1) if x['value'] is not None else 'н/д'} ({x['numerator']} из {x['denominator']})"


# ───────────────────────── метрики п. 11 в редакции приложения ─────────────────────────
def spec_table(d: dict) -> list[dict]:
    m, weeks = d["metrics"], d["meta"]["weeks"]
    g = d.get("growth") or {}
    rows: list[dict] = []

    def add(mid, name, value, shown, target, status, note=""):
        rows.append({"id": mid, "name": name, "value": value, "shown": shown, "target": target, "status": status, "note": note})

    a = m["activation"]
    act = ratio(a["completed"], a["started"])
    add("activation", "Активация: дошли до ленты (онбординг)", act, f"{a['completed']} из {a['started']} = {pct(act)}", "≥ 70 %",
        "ok" if act is not None and act >= 0.7 else "fail", ci(a["completed"], a["started"]))
    o = m["opens"]
    r = o["with_decision_share"]
    add("reaction", "Реакция: открытия приложения хотя бы с одним решением", r, f"{o['with_decision']} из {o['total']} = {pct(r)}", "≥ 40 %",
        "na" if r is None else "ok" if r >= 0.4 else "fail", f"прежняя метрика считала подборки с решением; открытий в среднем {num(o['per_user_week'], 1)} на человека в неделю")
    gp = [v for k, v in sorted(m["go_per_week"].items(), key=lambda kv: int(kv[0]))]
    pm = sum(gp) / len(gp) if gp else None
    add("plan", "План: доля пользователей с ≥1 «иду» в неделю (среднее по неделям)", pm, f"{pct(pm)}; по неделям: " + ", ".join(pct(x) for x in gp), "≥ 25 %",
        "na" if pm is None else "ok" if pm >= 0.25 else "fail", "знаменатель — все прошедшие онбординг")
    rt = [v for k, v in sorted(m["retention"].items(), key=lambda kv: int(kv[0]))]
    last = rt[-1] if rt else None
    add("retention", f"Удержание: открывали приложение на неделе {weeks} (8-недельное измерить нельзя)", last,
        f"{pct(last)}; по неделям: " + ", ".join(pct(x) for x in rt), "8 нед. ≥ 50 %", "na", "удержание = хотя бы одно открытие приложения за неделю")
    q = m["rating"]["mean"]
    add("rating", "Качество: средняя оценка «сходил» (★ в плане)", q, f"{num(q, 2)} (n = {m['rating']['n']})", "≥ 4,0", "na" if q is None else "ok" if q >= 4.0 else "fail",
        f"доля 4–5: {pct(ratio(sum(v for k, v in m['rating']['dist'].items() if int(k) >= 4), m['rating']['n']))}")
    gm = (g.get("metrics") or {}).get("new_via_friends", {}).get("own") if g else None
    if gm and gm["value"] is not None:
        add("growth", "Рост: доля новых через друзей (приглашения и ссылка-рекомендация)", gm["value"], f"{pct(gm['value'], 1)} ({gm['numerator']} из {gm['denominator']})", "≥ 20 %",
            "ok" if gm["value"] >= 0.2 else "fail", "source ∈ {invite, ref} среди новых профилей с согласием (в знаменателе и вторые профили аккаунтов); остальные метрики роста — в разделе 5")
    else:
        add("growth", "Рост: доля новых через друзей", None, "не измерялась", "≥ 20 %", "na", "прогон без графа друзей")
    add("money", "Деньги: конверсия в Pro, платящий организатор", None, "не измеряется", "≥ 5 % / неделя 6", "na", "платные функции не реализованы")
    return rows


# ───────────────────────── дефекты и наблюдения ─────────────────────────
def build_defects(d: dict) -> tuple[list[dict], list[dict]]:
    m, g = d["metrics"], d.get("growth") or {}
    ck = g.get("checks", {}) if g else {}
    gx = g.get("examples", {}) if g else {}
    sc = d.get("scenarios", {})
    db = d.get("db", {})
    opened: list[dict] = []
    closed: list[dict] = []

    def chk(key, sev, title, is_open, what, where, repro, count, closed_text=""):
        (opened if is_open else closed).append({"key": key, "severity": sev, "title": title, "what": what, "where": where, "repro": repro, "count": count, "evidence": closed_text})

    api = d.get("api", {})
    chk("api5xx", "высокая", "API отвечает 5xx на обычные действия приложения", api.get("n_errors", 0) > 0,
        [f"Ответов 5xx: {api.get('n_errors', 0)}.", *[f"Пример: {x['path']} → {x['status']} {x['body'][:80]}" for x in api.get("errors", [])[:3]]],
        "leisure/api", "Повторить вызов из примера.", api.get("n_errors", 0), f"вызовов API {d['meta'].get('api_calls')}, ответов 5xx 0")
    bad_calls = fcount(d, "decision_failed") + fcount(d, "feed_failed") + fcount(d, "plan_failed") + fcount(d, "rating_failed") + fcount(d, "onboarded_failed") \
        + fcount(d, "consent_failed") + fcount(d, "session_failed") + fcount(d, "profile_create_failed") + fcount(d, "values_failed")
    chk("appcalls", "высокая", "Действие в приложении не записалось (ошибка API на решении, ленте, плане, профиле)", bad_calls > 0,
        [f"Неудачных вызовов: {bad_calls}.", *[f"Лог: {x}" for k in ("decision_failed", "feed_failed", "plan_failed", "rating_failed", "onboarded_failed", "profile_create_failed") for x in fex(d, k, 1)]],
        "leisure/api/routers (decisions, feed, digest, profiles, accounts)", "См. примеры из лога.", bad_calls,
        "решения, лента, план, профили и оценки записались с первого раза: неудачных вызовов 0")
    di = db.get("decision_integrity", {})
    chk("integrity", "высокая", "Решение из приложения не совпадает с БД", (di.get("missing", 0) + di.get("mismatch", 0)) > 0,
        [f"Не найдено в БД {di.get('missing', 0)}, расходится статус или оценка {di.get('mismatch', 0)} из {di.get('checked', 0)}."],
        "leisure/api/services.py (set_decision)", "Сравнить `decisions` с журналом симулятора.", di.get("missing", 0) + di.get("mismatch", 0),
        f"нажатий сверено с БД {di.get('checked', 0)}, расхождений 0")
    pi = db.get("profile_isolation", {})
    chk("isolation_db", "высокая", "Решения второго профиля попадают в основной (или наоборот)", pi.get("bad", 0) > 0,
        [f"Аккаунтов с перепутанными решениями: {pi.get('bad', 0)} из {pi.get('ok', 0) + pi.get('bad', 0)}."],
        "leisure/api/services.py (set_decision, create_profile)", "Два профиля в аккаунте, решить по каждому, сравнить `decisions.user_id`.", pi.get("bad", 0),
        f"у {pi.get('ok', 0)} аккаунтов с двумя профилями решения лежат под своими user_id и привязаны к одному account_id")
    ln = m["learning"]
    chk("learn_neg", "средняя", "После трёх «не моё» категория остаётся в первой пятёрке ленты", ln["neg_ran"] > 0 and ln["neg_passed"] < ln["neg_ran"],
        [f"Проб {ln['neg_ran']}, категория ушла из пятёрки в {ln['neg_passed']}.", *[f"Пример: {p['category']}: до {p['before']}, после {p['after']}" for p in d["probes"] if p["kind"] == "neg" and p.get("ran") and not p.get("passed")][:2]],
        "leisure/core/affinity.py, leisure/core/feed.py (hidden_by_learning)", "Три «не моё» по событиям одной категории → GET /api/feed?date=week.",
        ln["neg_ran"] - ln["neg_passed"], f"проб {ln['neg_ran']}, категория ушла из первой пятёрки ленты профиля в {ln['neg_passed']}")
    pos_fail = [p for p in d["probes"] if p["kind"] == "pos" and "passed" in p and not p["passed"]]
    pos_na = ln.get("pos_not_evaluable", 0)
    chk("learn_pos", "средняя", "Три «сходил, 5» не поднимают категорию в ленте профиля", ln["pos_ran"] > 0 and ln["pos_passed"] < ln["pos_ran"],
        [f"Проб {ln['pos_ran']}, поднялась в {ln['pos_passed']}" + (f" (ещё {pos_na} не оценить: после отметок событий категории в ленте не осталось)" if pos_na else "") +
         ". Сравнение с «двойником» (тот же профиль без этих решений): " +
         "; ".join(f"{p['category']}: профиль {[c for c in p['after']]}, двойник {[c for c in p.get('twin_after', [])]}" for p in pos_fail[:2]),
         *[f"Баллы первых карточек: профиль {p.get('after_scores', [])[:5]}, двойник {p.get('twin_scores', [])[:5]}" for p in pos_fail[:1]]],
        "leisure/core/affinity.py (decision_weights «сходил», rating_scale), leisure/core/feed.py", "«Иду» на три события категории вне пятёрки, после даты — «сходил» с оценкой 5, сравнить GET /api/feed с профилем-двойником.",
        len(pos_fail), f"проб {ln['pos_ran']}, категория поднялась выше, чем у двойника, в {ln['pos_passed']}")
    chk("learn_iso", "средняя", "Обучение одного профиля меняет ленту другого профиля того же аккаунта", ln["isolation_checked"] > 0 and ln["isolation_ok"] < ln["isolation_checked"],
        [f"Проверок {ln['isolation_checked']}, лента второго профиля не изменилась в {ln['isolation_ok']}."],
        "leisure/api/services.py (recompute_affinity по user_id профиля)", "Три «не моё» в профиле «я», сравнить первую пятёрку ленты профиля «ребёнок» до и после.",
        ln["isolation_checked"] - ln["isolation_ok"], f"проверок {ln['isolation_checked']}, лента второго профиля не изменилась в {ln['isolation_ok']}")
    vm = db.get("values_mismatch", 0)
    chk("values", "средняя", "Пятёрка ценностей профиля в БД не совпадает с выбранной на «Шаге 1»", vm > 0, [f"Профилей с другой пятёркой: {vm}."],
        "leisure/api/services.py (update_profile: values)", "Пройти Шаг 1 и сравнить `profiles.values` (вес 5).", vm, f"пятёрка ценностей совпала у всех проверенных профилей (расхождений {vm})")
    ap = sc.get("api_probe", {})
    fb = ap.get("feed_before_onboarding", {})
    chk("feed409", "низкая", "Лента отдаётся профилю без онбординга", bool(fb) and fb.get("status") != 409, [f"GET /api/feed до онбординга → {fb.get('status')}."],
        "leisure/api/routers/feed.py", "Согласие без Шага 1–2 → GET /api/feed.", 1 if fb and fb.get("status") != 409 else 0, f"лента до онбординга → {fb.get('status')} {fb.get('detail')}")
    wb = ap.get("went_before_day", {})
    chk("went400", "средняя", "«Сходил» принимается до дня события", bool(wb) and wb.get("status") != 400, [f"POST «сходил» на будущее событие → {wb.get('status')}."],
        "leisure/api/services.py (set_decision: DecisionTooEarly)", "«Сходил» с оценкой на событие завтрашнего дня.", 1 if wb and wb.get("status") != 400 else 0,
        f"«сходил» до дня события → {wb.get('status')}: {wb.get('detail')}")
    da = sc.get("delete_account", {})
    chk("delete", "средняя", "Удаление аккаунта оставляет второй профиль или его решения", bool(da) and (not da.get("second_gone") or da.get("second_decisions_left")),
        [f"После DELETE основного профиля: основной {'удалён' if da.get('main_gone') else 'остался'}, второй {'удалён' if da.get('second_gone') else 'остался'}, решений второго осталось {da.get('second_decisions_left')}."],
        "leisure/api/services.py (delete_profile)", "Аккаунт с двумя профилями → DELETE /api/profile/{основной}.", int(bool(da) and (not da.get("second_gone") or da.get("second_decisions_left"))),
        f"DELETE основного профиля стёр аккаунт целиком: второй профиль {'удалён' if da.get('second_gone') else '—'}, решений второго осталось {da.get('second_decisions_left')}" if da else "проба не выполнялась (не нашлось аккаунта с двумя профилями)")
    nr = fcount(d, "feed_today_not_reachable")
    chk("reach", "средняя", "В «Сегодня» есть события, на которые уже не успеть", nr > 0, [f"Открытий с такими карточками: {nr}.", *[f"Лог: {x}" for x in fex(d, "feed_today_not_reachable", 2)]],
        "leisure/core/feed.py (can_make_it)", "Открыть «Сегодня» вечером и посмотреть `can_make_it`.", nr, "в «Сегодня» не было событий с can_make_it=false")
    if g:
        mism = g.get("mismatch", [])
        fn = g["funnel"]
        chk("growthmetrics", "средняя", "Метрики роста API расходятся с формулами GROWTH.md §4", bool(mism),
            [f"Не совпали: {', '.join(GROWTH_NAMES[k] for k in mism)}.", *[f"{GROWTH_NAMES[k]}: симулятор {growth_value(g['metrics'][k]['own'])}, API {growth_value(g['metrics'][k]['api'])}." for k in mism],
             f"В версии 2 «иду» после даты события превращается в «сходил» / «не сходил»: сейчас в БД «иду» {fn.get('going_now')}, а «иду» когда-либо — {fn.get('going_ever')}. "
             "`growth_metrics` делит на текущие «иду», поэтому доля «иду» с приглашением и совместные походы растут по мере отметок в плане; симулятор делит на «иду» когда-либо."],
            "leisure/api/invites.py (growth_metrics: going)", "Отметить «сходил» несколько «иду» и сравнить GET /api/metrics/growth до и после.", len(mism), "все девять метрик §4 совпали с расчётом симулятора")
        bad = sum(ck.get(k, 0) for k in ("invite_contract_bad", "accept_bad", "view_bad", "together_name_bad", "accept_failed", "declined_has_decision", "open_failed", "invite_create_failed"))
        chk("invitecontract", "высокая", "API приглашений нарушает контракт GROWTH.md §6", bad > 0 or g.get("n_api_errors", 0) > 0,
            [f"Нарушений контракта: {bad}, ответов 5xx: {g.get('n_api_errors', 0)}.", *[f"Пример: {x}" for k in ("invite_contract_bad", "accept_bad", "view_bad", "accept_failed", "together_name_bad") for x in gx.get(k, [])[:1]]],
            "leisure/api/invites.py, leisure/api/routers/invites.py", "См. раздел 5.4.", bad + g.get("n_api_errors", 0),
            f"контракт §6 соблюдён: проверок {ck.get('invite_contract_ok', 0) + ck.get('accept_ok', 0) + ck.get('view_ok', 0)}, нарушений 0")
        chk("companion", "средняя", "Пригласивший не видит «вдвоём с Имя» в плане", ck.get("inviter_not_notified", 0) > 0,
            [f"Не увидели {ck.get('inviter_not_notified', 0)} из {g['funnel']['going']} «иду» по приглашениям.", *[f"Пример: {x}" for x in gx.get("inviter_not_notified", [])[:2]]],
            "leisure/api/services.py (plan: companions), leisure/api/invites.py (companion_names)", "Принять приглашение «Иду» и открыть план пригласившего.",
            ck.get("inviter_not_notified", 0), f"«вдвоём с Имя» в плане пригласившего: {ck.get('inviter_sees_companion', 0)} из {g['funnel']['going']}; имя с <, > или & показано корректно {ck.get('companion_special_chars', 0)} раз, неверно {ck.get('companion_name_bad', 0)}")
        late = sum(ck.get(k, 0) for k in ("ref_ask_too_soon", "ref_ask_missing", "ref_ask_on_low_rating", "ref_ask_bad", "ref_source_bad", "ask_reason_missing"))
        chk("refmoment", "средняя", "Момент рекомендации в ответе на оценку работает не по правилу", late > 0,
            [f"Слишком рано {ck.get('ref_ask_too_soon', 0)}, пропущен {ck.get('ref_ask_missing', 0)}, на оценку 1–2 {ck.get('ref_ask_on_low_rating', 0)}, без ссылки {ck.get('ref_ask_bad', 0)}, "
             f"нет ask_reason на 1–2 {ck.get('ask_reason_missing', 0)}, source по ссылке неверен {ck.get('ref_source_bad', 0)}.",
             *[f"Пример: {x}" for k in ("ref_ask_too_soon", "ref_ask_missing", "ref_source_bad", "ask_reason_missing") for x in gx.get(k, [])[:1]]],
            "leisure/api/routers/decisions.py (ref_ask, ask_reason), leisure/api/invites.py (ref_ask_due, apply_ref_code)", "Две оценки 4–5 в течение 14 дней; оценка 2.", late,
            f"ref_ask пришёл {g['funnel']['ref_asks']} раз у {g['funnel']['ref_ask_users']} профилей, раньше срока 0; source=ref по ссылке верно {ck.get('ref_source_ok', 0)}")
    opened.sort(key=lambda x: SEV_ORDER[x["severity"]])
    for i, x in enumerate(opened, 1):
        x["id"] = f"Д{i}"
    return opened, closed


def build_usability(d: dict) -> list[dict]:
    m = d["metrics"]
    o, ev, op = m["onboarding"], m["evening"], m["opens"]
    out: list[dict] = []

    def item(key, title, is_open, evidence, advice):
        if is_open:
            out.append({"key": key, "title": title, "evidence": evidence, "advice": advice})

    item("onboarding", "Онбординг: нажатий до ленты больше целевых 12", bool(o["taps_median"] and o["taps_median"] > TARGET_TAPS),
         [f"min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}; в пределах 12 уложились {o['taps_le_12']} из {m['activation']['completed']}, в 9 — {o['taps_le_9']}.",
          f"Правок направлений в медиане {num(o['interest_edits_median'], 0)}; «Все направления» открыли {o['used_all_screen']}; из восьми предложенных в интерес попало в среднем {num(o['shown_match_avg'], 1)}."],
         "Предлагать направления точнее и дать быстрое добавление без экрана «Все направления».")
    item("proposal", "Предложенные восемь направлений слабо совпадают с тем, что хочет человек", o["shown_match_avg"] < 4.8,
         [f"Из восьми в интерес персоны попало в среднем {num(o['shown_match_avg'], 1)} ({pct(ratio(o['shown_match_avg'], 8))}); правок в медиане {num(o['interest_edits_median'], 0)}."],
         "Ранжировать направления по ценностям точнее.")
    item("evening_empty", "«Освободился вечер»: в будний вечер «Сегодня» часто пусто", ev["opens"] > 0 and ev["empty"] + ev["fallback_tomorrow"] > 0.3 * ev["opens"],
         [f"Из {ev['opens']} вечерних открытий лента «Сегодня» была пустой в {ev['empty'] + ev['fallback_tomorrow']} ({pct(ratio(ev['empty'] + ev['fallback_tomorrow'], ev['opens']))}); "
          f"в {ev['fallback_tomorrow']} человек переключился на «Завтра». В seed события по будням редки (после первого уикенда 4–18 событий на неделю)."],
         "Пока база бедна, показывать в «Сегодня» ближайшие дни с подписью «Завтра» и «Послезавтра», а не пустой экран.")
    item("empty_feed", "Пустая лента", op["total"] > 0 and op["empty"] > 0.15 * op["total"],
         [f"Из {op['total']} открытий лента пуста в {op['empty']} ({pct(ratio(op['empty'], op['total']))}); по дням: " + ", ".join(f"{DAY_RU.get(k, k)} — {v}" for k, v in op["by_day"].items()) + "."],
         "Коллекторы: больше событий по будням; интерфейс: предлагать другой день, а не пустоту.")
    item("evening_taps", "«Освободился вечер»: до «Иду» больше трёх нажатий", bool(ev["taps_to_go_median"] and ev["taps_to_go_median"] > EVENING_TARGET_TAPS),
         [f"Медиана {num(ev['taps_to_go_median'], 0)}, максимум {ev['taps_to_go_max']}; в три уложились {ev['taps_le_3']} из {ev['with_go']}."], "Показывать лучшее первым, крупная карточка на экран.")
    return out


# ───────────────────────── «было → стало» ─────────────────────────
def compare_rows(d: dict, spec: list[dict], defects: list[dict]) -> list[list[str]] | None:
    b = load_baseline("baseline_v4.json")
    if not b:
        return None
    m = d["metrics"]

    def bval(mid):
        return next((r["value"] for r in b.get("spec_metrics", []) if r["id"] == mid), None)

    def sval(mid):
        return next((r["value"] for r in spec if r["id"] == mid), None)

    def p(x):
        return pct(x) if x is not None else "н/д"

    bo, o = b.get("onboarding", {}), m["onboarding"]
    rows = [
        ["Активация", p(bval("activation")), p(sval("activation")), "онбординг тот же: согласие, Шаг 1, Шаг 2"],
        ["Реакция", f"{p(bval('reaction'))} подборок с решением", f"{p(sval('reaction'))} открытий приложения с решением", "разные определения: рассылки нет, человек открывает сам"],
        ["«Иду» в неделю (среднее)", p(bval("plan")), p(sval("plan")), ""],
        ["Удержание на последней неделе", p(bval("retention")), p(sval("retention")), "было: активен в боте; стало: открыл приложение"],
        ["Средняя оценка", num(bval("rating"), 2), num(sval("rating"), 2), "было: «Как прошло?» в чате; стало: ★ у «сходил» в плане"],
        ["Нажатий до первой подборки / ленты: min / медиана / max", f"{bo.get('taps_min')} / {num(bo.get('taps_median'), 0)} / {bo.get('taps_max')}",
         f"{o['taps_min']} / {num(o['taps_median'], 0)} / {o['taps_max']}", "в приложении нет /start и «Принять»: галочка согласия и «Начать»"],
        ["Нажатий до первого «Иду» (медиана)", num(b.get("first_go", {}).get("taps_median"), 0), num(m["first_go"]["taps_median"], 0), ""],
        ["Бросили онбординг (из 50)", str(bo.get("started", 0) - bo.get("completed", 0)), str(m["activation"]["started"] - m["activation"]["completed"]), ""],
    ]
    bg = (b.get("growth") or {}).get("metrics", {})
    g = (d.get("growth") or {}).get("metrics", {})
    for k, name in GROWTH_NAMES.items():
        if k in bg or k in g:
            rows.append([name, growth_value(bg.get(k, {}).get("own")), growth_value(g.get(k, {}).get("own")), ""])
    sev_b = Counter(x["severity"] for x in b.get("defects", []))
    sev = Counter(x["severity"] for x in defects)
    rows += [["Открытых дефектов, всего", str(len(b.get("defects", []))), str(len(defects)), "дефект про отправку 10 000 за 15 минут снят вместе с рассылкой"],
             ["  высокой серьёзности", str(sev_b.get("высокая", 0)), str(sev.get("высокая", 0)), ""],
             ["  средней", str(sev_b.get("средняя", 0)), str(sev.get("средняя", 0)), ""],
             ["  низкой", str(sev_b.get("низкая", 0)), str(sev.get("низкая", 0)), ""]]
    return rows


# ───────────────────────── рост через друзей ─────────────────────────
def growth_rows(g: dict) -> list[list[str]]:
    rows = []
    for k, name in GROWTH_NAMES.items():
        v = g["metrics"][k]
        own, t = v["own"], GROWTH_TARGET[k]
        status = "наблюдаем" if t is None else "нельзя оценить" if own["value"] is None else "достигнута" if own["value"] >= t else "не достигнута"
        target = "наблюдаем" if t is None else "≥ 0,2" if k == "virality" else f"≥ {pct(t)}"
        fmt = (lambda x: f"{num(x['value'], 2)} ({x['numerator']} из {x['denominator']})" if x and x["value"] is not None else growth_value(x)) if k == "virality" else growth_value
        rows.append([name, GROWTH_FORMULA[k], target, fmt(own), status, fmt(v["api"])])
    return rows


def growth_lines(d: dict) -> list[str]:
    g = d.get("growth")
    if not g:
        return ["## 5. Рост через друзей", "", "Прогон без графа друзей (`--no-social`).", ""]
    f, cmp_, ck, fr = g["funnel"], g["compare"], g["checks"], g["friends"]
    L = ["## 5. Рост через друзей (docs/GROWTH.md)", "",
         f"Граф дружбы: у каждой из {len(d['personas'])} персон 2–5 друзей (в среднем {num(fr['avg'], 1)}), из них {fr['inside']} внутри сервиса и {fr['outside']} вне его "
         "(новые персоны близкого, но другого архетипа). После «иду» персона зовёт друга с вероятностью от общительности и от того, подходит ли событие другу; друг принимает "
         "с вероятностью от скоринга события под его скрытый вкус. Всё через API приложения: `POST /api/invites`, у друга — гостевая сессия, `GET /api/invites/{code}`, `POST …/open`, "
         "`POST …/accept` (согласие при первом касании), затем предложение онбординга и `PUT /api/profile`. «Имя идёт с тобой» пригласивший видит в плане (`companions`), момент "
         "рекомендации — `ref_ask` в ответе на оценку 4–5. Гости в основные метрики п. 11 не входят.", "",
         "### 5.1 Метрики таблицы §4", "",
         "«Симулятор» считает по формулам GROWTH.md из своего журнала и БД; «API» — ответ `GET /api/metrics/growth`.", "",
         table(["Метрика", "Формула §4", "Цель", "Симулятор", "Статус", "API"], growth_rows(g)), "",
         f"Рекомендация: «Поделиться» нажали {g['metrics']['recommendation']['own']['numerator']} из {g['metrics']['recommendation']['own']['denominator']} показов — это системный диалог, сервер нажатий не видит "
         f"и считает ссылки, которые кто-то открыл: симулятор по тому же правилу {f.get('ref_codes_seen')}, API {growth_value(g['metrics']['recommendation']['api'])}. "
         f"В знаменателе «доли новых через друзей» у API все профили с согласием, включая вторые профили аккаунтов ({f.get('second_profiles_in_new_total')}).", ""]
    if g["mismatch"]:
        L += ["Расходятся с API: " + ", ".join(GROWTH_NAMES[k] for k in g["mismatch"]) + ".", ""]
    L += ["### 5.2 Воронка приглашений", "",
          table(["Шаг", "Значение"], [
              ["Приглашений создано", f"{f['invites']}; позвали {f['inviters']} человек; друзей внутри сервиса {f['to_inside']}, вне его {f['to_outside']}"],
              ["Открыли страницу приглашения", f"{f['opened']}; из них без профиля и согласия {f['new_openers']}; друг внутри сервиса ещё не открывал приложение: {ck.get('friend_without_app', 0)}"],
              ["Приняли «Иду» / «Может быть»", f"{f['accepted']} ({f['going']} / {f['maybe']}); «Другие выходные под меня»: {f['declined']}"],
              ["Согласие при первом касании (409 → галочка)", f"{f['consent_409']} из {f['new_openers']} новых; ушли без согласия {ck.get('consent_not_given', 0)}"],
              ["Событие уже прошло к открытию (410)", str(ck.get("accept_gone_410", 0))],
              ["Пригласивший видит «вдвоём с Имя» в плане", f"{f['notified']} из {f['going']} «иду»"],
              ["Предложение онбординга: «Давай» сразу / в повторе", f"{f['offers_yes1']} из {f['offers_round1']} / {f['offers_yes2']} из {f['offers_round2']}"],
              ["Онбординг гостей: начали / закончили", f"{f['onboarding_started']} / {f['onboarding_done']}"],
              ["Гостей всего", f"{f['guests_total']}; прошли онбординг и живут в приложении {f['guests_active']}; открывали приложение потом {f['guests_opened_app']}"],
              ["Момент рекомендации", f"{f['ref_asks']} показов у {f['ref_ask_users']} профилей; «Поделиться» {f['ref_shares']}; ссылку открыли {f['ref_newcomers']} человек, согласились {f['ref_newcomers_consented']}"],
          ]), ""]
    org, inv = cmp_["activation"]["organic"], cmp_["activation"]["invited"]
    o2, i2 = cmp_["onboarding"]["organic"], cmp_["onboarding"]["invited"]
    rt = cmp_["ratings"]

    def rrow(label, x):
        return [label, x["n"], num(x["mean"], 2), pct(x["share_4_5"])]

    L += ["### 5.3 Приглашённые и органические", "",
          table(["Показатель", "Органические (50 персон)", "Приглашённые", "Как считали"], [
              ["Активация", f"{pct(ratio(org['num'], org['den']))} ({org['num']} из {org['den']})", f"{pct(ratio(inv['num'], inv['den']))} ({inv['num']} из {inv['den']})",
               "дошли до ленты / начали; согласие + решение / открыли без профиля"],
              ["Онбординг", f"{pct(ratio(o2['num'], o2['den']))} ({o2['num']} из {o2['den']})", f"{pct(ratio(i2['num'], i2['den']))} ({i2['num']} из {i2['den']})",
               "прошли онбординг / дали согласие; полный профиль за 2 недели / принявшие с source=invite"]]), "",
          table(["Оценки «сходил»", "Оценок", "Средняя", "Доля 4–5"],
                [rrow("Органические", rt["organic"]), rrow("Решения по приглашению", rt["invited_decisions"]), rrow("Все оценки приглашённых", rt["invited_users_all"]),
                 rrow("Совместные походы", rt["together"]), rrow("Одиночные органические", rt["solo"])]), "",
          "Оценка в модели — функция скрытого вкуса человека и события; «вдвоём приятнее» намеренно не заложено. Малые n дают ориентир, не вывод.", "",
          "### 5.4 Контрольные проверки API приглашений", "",
          f"- Контракт `POST /api/invites` (код из 8 символов без 0/1/I/L/O/U, ссылка `{'{WEB_BASE_URL}'}/e/<slug>?inv=<код>`, текст со ссылкой): верно {ck.get('invite_contract_ok', 0)}, "
          f"нарушено {ck.get('invite_contract_bad', 0)}; повторное «Позвать друга» вернуло тот же код {ck.get('invite_idempotent', 0)} раз, другой — {ck.get('invite_not_idempotent', 0)}.",
          f"- `GET /api/invites/{{code}}`: карточка, день, имя пригласившего верны {ck.get('view_ok', 0)}, событие уже прошло {ck.get('view_past', 0)}, ошибок {ck.get('view_bad', 0)}.",
          f"- `POST …/accept`: решение с верным статусом и днём {ck.get('accept_ok', 0)}, без согласия 409 {ck.get('consent_required_409', 0)}, событие прошло 410 {ck.get('accept_gone_410', 0)}, "
          f"другие ошибки {ck.get('accept_failed', 0)}; «declined» без решения {ck.get('declined_ok', 0)}; имя пригласившего в ответе верно {ck.get('together_name_ok', 0)} из "
          f"{ck.get('together_name_ok', 0) + ck.get('together_name_bad', 0)}.",
          f"- Момент рекомендации: раньше 14 дней {ck.get('ref_ask_too_soon', 0)}, пропущен {ck.get('ref_ask_missing', 0)}, на оценку 1–2 {ck.get('ref_ask_on_low_rating', 0)}; "
          f"`PUT /api/profile` с `ref_code` ставит `source=ref`: верно {ck.get('ref_source_ok', 0)}, неверно {ck.get('ref_source_bad', 0)}; открывшие ссылку без согласия профиля не получили: {ck.get('ref_no_profile_without_consent', 0)}.",
          f"- Ответы сервера 5xx: {g['n_api_errors']}.", ""]
    return L


# ───────────────────────── вывод ─────────────────────────
def render_md(d: dict, spec: list[dict], defects: list[dict], closed: list[dict], usab: list[dict]) -> str:
    meta, m = d["meta"], d["metrics"]
    o, op, ev, pr, ln = m["onboarding"], m["opens"], m["evening"], m["profiles"], m["learning"]
    w = meta["weeks"]
    L = ["# Отчёт симуляции пользователей — «Успею» (приложение, версия 2)", "",
         f"Прогон: seed `{meta['seed']}`, {meta['users']} персон ({', '.join(f'{k} {v}' for k, v in sorted(meta['archetypes'].items()))}), неделя онбординга и {w} "
         f"{'недели' if w in (2, 3, 4) else 'недель'} после неё, {meta.get('api_calls')} вызовов API через FastAPI TestClient. События: seed {meta['events_seeded']} шт.", "",
         f"Команда: `python -m leisure.sim.runner --users {meta['users']} --weeks {w} --seed {meta['seed']}`. База `{meta['db_name']}` создаётся и удаляется прогоном, база разработки "
         "не затрагивается. Один seed — один и тот же отчёт (кроме строки о длительности в конце).", "",
         "> **Как читать.** Код продукта — настоящий: API, лента, скоринг, обучение, приглашения, БД. Люди — модель: когда открыть приложение, какой день и направление выбрать, "
         "нажать ли «Иду», сколько терпеть онбординг (`personas.py`, `app/driver.py`). Абсолютные доли — «что будет при таком поведении»; надёжны находки о механике: "
         "дефекты и наблюдения ниже подтверждены журналом вызовов.", ""]
    cr = compare_rows(d, spec, defects)
    if cr:
        L += ["## 0. Было → стало (против четвёртого прогона, `baseline_v4.json`)", "",
              "Четвёртый прогон — бот и Mini App с рассылкой по четвергам; этот — приложение без рассылок: человек сам открывает ленту. Сопоставимы онбординг, «иду» в неделю, оценка и "
              "метрики роста; «реакция» и «удержание» переопределены (в примечании). Тот же seed и те же 50 архетипов.", "",
              table(["Показатель", "Четвёртый прогон (бот)", "Стало (приложение)", "Примечание"], cr), ""]
    L += ["## 1. Метрики п. 11 спеки в редакции приложения", "",
          table(["Метрика", "Значение", "Цель", "Статус", "Примечание"], [[r["name"], r["shown"], r["target"], STATUS_RU[r["status"]], r["note"]] for r in spec]), ""]
    a = m["activation"]
    L += ["## 2. Как люди пользуются приложением", "", "### Первый вход и онбординг", "",
          f"Начали {a['started']}, дошли до ленты {a['completed']} ({pct(ratio(a['completed'], a['started']))}); бросили: " +
          (", ".join(f"{k} — {v}" for k, v in a["abandoned_at"].items()) or "никто") + ". Нажатий от открытия ссылки до ленты (галочка согласия, «Начать», пять ценностей с автопереходом, "
          f"правки направлений, бюджет строкой, «Показать подборку»): **min {o['taps_min']}, медиана {num(o['taps_median'], 0)}, max {o['taps_max']}**; минимум по схеме {MIN_TAPS}–9, "
          f"цель FLOW-ONBOARDING — не больше {TARGET_TAPS}: уложились {o['taps_le_12']} из {a['completed']}, в 9 — {o['taps_le_9']}. Правок направлений в медиане {num(o['interest_edits_median'], 0)}, "
          f"«Все направления» открыли {o['used_all_screen']}, бюджет строкой задали {o['budget_on_step']}; из восьми предложенных направлений в интерес персоны попало в среднем {num(o['shown_match_avg'], 1)}."
          + (f" Предзаполнение интересов сервером отличалось от схемы FLOW у {o['server_prefill_differs']} профилей." if o.get("server_prefill_differs") else ""), "",
          f"До первого «Иду» (от открытия ссылки): медиана {num(m['first_go']['taps_median'], 0)} нажатий; «Иду» нажали {m['first_go']['users']} из {m['first_go']['of']}.", "",
          "### Открытия приложения", "",
          f"Всего открытий {op['total']} — {num(op['per_user_week'], 1)} на человека в неделю (запланировано по характеру: " +
          ", ".join(f"{v} чел. × {k}/нед." for k, v in sorted(op["planned_per_week"].items())) + f"); с хотя бы одним решением {op['with_decision']} ({pct(op['with_decision_share'])}); "
          f"лента пуста в {op['empty']}; карточек в ленте в среднем {num(op['cards_avg'], 1)}. Выбор дня: " + ", ".join(f"{DAY_RU.get(k, k)} — {v}" for k, v in op["by_day"].items()) +
          "; направление: " + ", ".join(f"{SEG_RU.get(k, k)} — {v}" for k, v in op["by_segment"].items()) + ". По неделям: " +
          ", ".join(f"{k} — {v}" for k, v in op["by_cycle"].items()) + ". Решений: " + ", ".join(f"{k} — {v}" for k, v in m["decisions"].items()) +
          f"; отметок «сходил» с оценкой {m['rating']['went']}, распределение: " + ", ".join(f"{k}★ — {v}" for k, v in sorted(m["rating"]["dist"].items())) + f". Ушли (перестали открывать): {m['churned']}.", "",
          "### Сценарий «освободился вечер»", "",
          f"Открытий в будний день с 17:00 до 19:59 по местному времени: {ev['opens']}; человек смотрит «Сегодня» (3–5 карточек). С «Иду» закончились {ev['with_go']} ({pct(ev['go_share'])}), "
          f"с любым решением {ev['with_decision']}. «Сегодня» было пусто в {ev['empty'] + ev['fallback_tomorrow']} открытиях, в {ev['fallback_tomorrow']} из них человек переключился на «Завтра». "
          f"Нажатий до «Иду» (свайпы мимо + «Иду»): медиана {num(ev['taps_to_go_median'], 0)}, максимум {ev['taps_to_go_max']}; в три уложились {ev['taps_le_3']} из {ev['with_go']} (цель 3). "
          f"Карточек в вечерней ленте в среднем {num(ev['cards_avg'], 1)}.", "",
          "### Несколько профилей", "",
          f"Второй профиль завели {pr['accounts_with_second']} из {a['completed']} ({pct(pr['share'])}; по модели второй профиль у 20 % персон — {pr['planned_second']} из {a['started']}, "
          f"из них {pr['planned_second_abandoned']} бросили онбординг): " + (", ".join(f"{k} — {v}" for k, v in pr["second_kinds"].items()) or "—") +
          f". Онбординг второго профиля — нажатий {pr['second_onboarding_taps']}. Решений по профилям (основной, второй): {pr['decisions_by_profile']}; открытий со вторым профилем "
          f"{pct(pr['opens_second_share'])} от всех. В БД решения второго профиля лежат под его user_id: аккаунтов проверено {d['db']['profile_isolation']['ok'] + d['db']['profile_isolation']['bad']}, "
          f"перепутано {d['db']['profile_isolation']['bad']}.", "",
          "### Персональное обучение", "",
          f"Пробы на живых профилях (лента `date=week&segment=all`, первая пятёрка по категориям). Три «не моё» по категории из пятёрки: проб {ln['neg_ran']}, категория ушла из пятёрки в {ln['neg_passed']}. "
          f"Три «сходил, 5» по категории вне пятёрки (сравнение с профилем-двойником без этих решений): проб {ln['pos_ran']}, категория поднялась в {ln['pos_passed']}" + (f", ещё {ln.get('pos_not_evaluable', 0)} не оценить — после отметок событий категории в ленте не осталось" if ln.get("pos_not_evaluable") else "") + ". Обучение одного профиля "
          f"не тронуло ленту второго профиля того же аккаунта: проверок {ln['isolation_checked']}, без изменений {ln['isolation_ok']}." +
          (f" Не выполнены (не нашлось подходящей категории с достаточным числом событий): {ln['not_run']}." if ln["not_run"] else ""), ""]
    probe_rows = [[p["kind"], p["category"], " · ".join(x or "?" for x in p.get("before", [])), " · ".join(x or "?" for x in p.get("after", [])),
                   "не оценить" if p.get("not_evaluable") else "да" if p.get("passed") else "нет", {True: "да", False: "нет"}.get(p.get("isolated"), "—")] for p in d["probes"] if p.get("ran")]
    if probe_rows:
        L += [table(["Проба", "Категория", "Пятёрка до", "Пятёрка после", "Сработало", "Второй профиль не изменился"], probe_rows), ""]
    L += ["## 3. Дефекты продукта", "", "### 3.1 Открытые", ""]
    for x in defects:
        L += [f"### {x['id']} [{x['severity']}] {x['title']}", "", *[f"- {line}" for line in x["what"]], f"- **Где:** {x['where']}", f"- **Как воспроизвести:** {x['repro']}", ""]
    if not defects:
        L += ["Открытых дефектов нет.", ""]
    L += ["### 3.2 Проверено и закрыто", "", table(["Проверка", "Что показал прогон"], [[x["title"], x["evidence"] or "—"] for x in closed]), "",
          "Дефект четвёртого прогона «отправка дайджеста 10 000 пользователям не укладывается в 15 минут» снят вместе с рассылкой.", ""]
    L += ["## 4. Наблюдения и юзабилити (по убыванию важности)", ""]
    for i, x in enumerate(usab, 1):
        L += [f"### У{i}. {x['title']}", "", *[f"- {line}" for line in x["evidence"]], f"- **Что сделать:** {x['advice']}", ""]
    if not usab:
        L += ["Проблем не найдено.", ""]
    L += growth_lines(d)
    sc = d.get("scenarios", {})
    ap, da = sc.get("api_probe", {}), sc.get("delete_account", {})
    L += ["## 6. Контрольные проверки", "",
          f"- Лента до онбординга: `GET /api/feed` → {ap.get('feed_before_onboarding', {}).get('status')} ({ap.get('feed_before_onboarding', {}).get('detail')}); «сходил» до дня события → "
          f"{ap.get('went_before_day', {}).get('status')}; удалённый профиль после `DELETE` → {'404' if ap.get('deleted_profile_gone') else 'ещё есть'}.",
          f"- Удаление аккаунта с двумя профилями: основной {'удалён' if da.get('main_gone') else '—'}, второй {'удалён' if da.get('second_gone') else 'остался'}, решений второго осталось {da.get('second_decisions_left', '—')}." if da else "- Удаление аккаунта с двумя профилями: проба не выполнялась.",
          f"- Целостность: решений сверено с БД {d['db']['decision_integrity']['checked']}, не найдено {d['db']['decision_integrity']['missing']}, расхождений {d['db']['decision_integrity']['mismatch']}; "
          f"профилей в БД {d['db']['profiles']['total']} (настроенных {d['db']['profiles']['onboarded']}, только согласие {d['db']['profiles']['consent_only']}).",
          "- Вызовы API: " + "; ".join(f"{k} — {v}" for k, v in d["api"]["calls"].items()) + f". Ответов 5xx: {d['api']['n_errors']}; записей ERROR/WARNING продукта: {len(d.get('log_errors', []))}.",
          f"- Воркер: журнал показанного (среда 22:00) запускался {len(d['volatile'].get('jobs', []))} раз.", ""]
    L += ["## 7. Ограничения прогона", "",
          "- Поведение людей — допущения (`leisure/sim/personas.py`, `app/driver.py`, `app/social.py`): частота открытий 1–5 в неделю по вовлечённости, чаще вечером четверга и пятницы; выбор дня "
          "по характеру (спонтанные — «Сегодня», планирующие — «Неделя»), направление «Дело» чаще у нетворкеров и занятых; вероятности «Иду» / «Не моё», оценок, ухода. Другие допущения дадут другие доли.",
          "- Нажатия считаются на клиенте по схеме FLOW-ONBOARDING и экранам v2 (свайп мимо карточки = 1); на сервер уходят только вызовы API.",
          "- Seed — 177 событий, почти все на первом уикенде; по будням событий мало, поэтому «Сегодня» вечером часто пусто — это ограничение базы, а не ленты.",
          "- Часы: `services.utcnow` и `datetime.now()` в модулях профилей и приглашений подменены часами симуляции, `created_at`/`updated_at` в БД — триггерами; окно «сегодня» в ленте считается по ним.",
          "- Удержание — доля открывших приложение за неделю; открытия запланированы по характеру и прекращаются только при уходе (вовлечённость ниже порога), поэтому доля высока по построению.",
          "- Не проверялись: веб-клиент (Next.js), установка PWA, системный «Поделиться», почта (magic link), параллельные запросы, несколько городов.", ""]
    L += ["## 8. Как воспроизвести", "", "```", f"python -m leisure.sim.runner --users {meta['users']} --weeks {w} --seed {meta['seed']}",
          "cd leisure && python -m pytest tests/test_sim_smoke.py", "```", "Сырые результаты — `leisure/sim/out/run_data.json` (не в git).", "",
          f"---\nДлительность прогона: {d['volatile']['duration_s']} с (единственная строка отчёта, которая меняется от запуска к запуску)."]
    return "\n".join(L) + "\n"


def write_reports(d: dict, out_dir: Path | str) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = spec_table(d)
    defects, closed = build_defects(d)
    usab = build_usability(d)
    (out / "REPORT.md").write_text(render_md(d, spec, defects, closed, usab), encoding="utf-8")
    cr = compare_rows(d, spec, defects)
    g = d.get("growth")
    payload = {
        "meta": d["meta"], "spec_metrics": spec,
        "onboarding": {**d["metrics"]["onboarding"], "started": d["metrics"]["activation"]["started"], "completed": d["metrics"]["activation"]["completed"]},
        "first_go": d["metrics"]["first_go"], "metrics": d["metrics"],
        "defects": [{k: x[k] for k in ("id", "severity", "title", "count", "where")} for x in defects],
        "closed_defects": [{k: x[k] for k in ("key", "title", "evidence")} for x in closed],
        "usability": [{"id": f"У{i}", "title": x["title"]} for i, x in enumerate(usab, 1)],
        "vs_previous": [{"metric": r[0], "was": r[1], "now": r[2], "note": r[3]} for r in (cr or [])],
        "growth": ({"metrics": g["metrics"], "funnel": g["funnel"], "compare": g["compare"], "mismatch": g["mismatch"], "checks": g["checks"]} if g else None),
        "db": d["db"], "scenarios": d.get("scenarios"), "findings": {k: v["count"] for k, v in d["findings"].items()}, "api_calls": d["api"]["calls"],
        "volatile": d["volatile"],
    }
    (out / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return {"spec": spec, "defects": defects, "usability": usab}


def console_summary(m: dict, d: dict) -> str:
    o, ev = d["metrics"]["onboarding"], d["metrics"]["evening"]
    lines = [f"[sim] готово за {d['volatile']['duration_s']} с: {d['meta']['users']} персон, {d['meta']['weeks'] + 1} недель, {d['meta'].get('api_calls')} вызовов API"]
    for r in m["spec"]:
        lines.append(f"  {r['name'][:70]:<70} {r['shown'][:40]:<40} цель {r['target']:<14} {STATUS_RU[r['status']]}")
    lines.append(f"  онбординг: нажатий min/медиана/max = {o['taps_min']}/{num(o['taps_median'], 0)}/{o['taps_max']}; вечер: «Иду» в {pct(ev['go_share'])} открытий, до «Иду» медиана {num(ev['taps_to_go_median'], 0)}")
    lines.append(f"  дефектов: {len(m['defects'])}, наблюдений: {len(m['usability'])} — подробности в leisure/sim/REPORT.md")
    return "\n".join(lines)


_ = statistics
