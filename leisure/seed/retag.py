"""Доразметка seed по детерминированным правилам (без модели): теги по VALUES-AUDIT.md, разделы 3–4, и переклассификация деловых
событий в четыре бизнес-категории каталога (сегмент «Дело» ленты, docs/PIVOT-PWA.md v2).

    python -m leisure.seed.retag             # переписывает seed/events_2026-10-23.json и seed/RETAG.md
    python -m leisure.seed.retag --check     # ничего не пишет; код 1, если файл не совпадает с результатом правил

Правило = (категория и/или регулярное выражение по тексту события) → теги. Текст — название, подкатегория, описание и
«почему подойдёт», в нижнем регистре. Теги только добавляются (ни один прежний не удаляется), порядок детерминирован,
повторный запуск ничего не меняет. Отчёт RETAG.md — для выборочной проверки куратором.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from leisure.core.catalog import BUSINESS_CATS, KNOWN_TAGS, VALUE_MAP, VALUES

HERE = Path(__file__).parent
SEED = HERE / "events_2026-10-23.json"
REPORT = HERE / "RETAG.md"
STRONG = 0.6  # «событие сильно задевает ценность»: вес тега не ниже (замер из аудита, раздел 1)


@dataclass(frozen=True)
class Rule:
    id: str
    what: str                         # человекочитаемое описание для отчёта
    tags: tuple[str, ...]
    category: str | None = None       # точное совпадение категории
    pattern: str | None = None        # регулярное выражение по тексту
    exclude: str | None = None        # если встретилось в тексте — правило не применяется
    needs_kids: bool = False          # только если у события уже стоит audience_kids


RULES: tuple[Rule, ...] = (
    Rule("cat-wine", "категория «Винные бары»", ("вкус",), category="Винные бары"),
    Rule("cat-party", "категория «Вечеринки»", ("веселье",), category="Вечеринки"),
    Rule("cat-matches", "категория «Волейбол: матчи»", ("болеть", "азарт"), category="Волейбол: матчи"),
    Rule("cat-volley", "категория «Волейбол»", ("соревнование",), category="Волейбол"),
    Rule("kw-calm", "баня, медитация, ретрит", ("покой",), pattern=r"\bбан[яеию]\b|медитац|\bретрит"),
    Rule("kw-quiet", "тишина как обстановка (не название песни «Тишина», не «громкая тишина» и не пауза группы «будет тишина»)",
         ("тишина",), pattern=r"в (полной )?тишине|тихий (вечер|зал|концерт)|тихая музыка|тишина и покой",
         exclude=r"громкая тишина|«тишина»|потом будет тишина"),
    Rule("kw-quiet2", "«тихое, уютное», спокойный вечер, неспешный, умиротворение", ("тишина",),
         pattern=r"тихое, уютное|спокойный (субботний )?вечер|неспешн|умиротвор"),
    Rule("kw-cozy", "уютный", ("комфорт",), pattern=r"\bуютн"),
    Rule("kw-romance", "свидание, вдвоём, романтический", ("романтика",), pattern=r"свидани|вдвоём|романтич",
         exclude=r"не в студии для свиданий"),
    Rule("kw-fun", "стендап, квиз, караоке, настолки", ("веселье", "игра"), pattern=r"стендап|\bквиз|караоке|настольн|настолк"),
    Rule("kw-play", "игровая дегустация, казино", ("игра",), pattern=r"игров(ая|ой|ую) дегустац|казино"),
    Rule("kw-gamble", "азарт", ("азарт",), pattern=r"азарт"),
    Rule("kw-contest", "турнир, соревнование", ("соревнование",), pattern=r"турнир|соревнован"),
    Rule("kw-meaning", "философия, духовное, смысл", ("смысл",), pattern=r"философ|\bсмысл"),
    Rule("kw-spiritual", "духовные гимны, буддийское", ("духовно",), pattern=r"духовн|буддийск"),
    Rule("kw-volunteer", "волонтёрство, добровольцы, субботник, экоакция, сбор вещей", ("волонтёрство", "забота"),
         pattern=r"волонт|добровол|субботник|экоакци|эко-акци|помогите проводить уборк|сбор (вещей|одежды|гуманитарн)"),
    Rule("kw-charity", "благотворительность, «в поддержку фонда», приют, хоспис", ("забота",),
         pattern=r"благотвор|в поддержку фонда|в пользу фонда|сбор средств|\bприют\b|хоспис|подопечн|нуждающ"),
    Rule("kw-care", "помощь животным, дома престарелых, одиноким пожилым", ("забота",),
         pattern=r"помощь животным|дом(а|е|ов)? престарел|одинок\w+ пожил|пожилым людям"),
    Rule("kw-body-calm", "йога, пилатес, цигун, дыхательные практики, звуковые ванны", ("покой", "тело"),
         pattern=r"\bйог|пилатес|цигун|дыхательн\w+ практик|звуков\w+ ванн|хатха|аштанг|кундалини"),
    Rule("kw-spa", "термы, хаммам, парение, сауна, банный день", ("покой",),
         pattern=r"\bтерм[аы]\b|хаммам|парени|\bсауна|банн(ый|ая|ое|ые) (день|ритуал|вечер)|спа-(день|программа)"),
    Rule("kw-reading", "читальный зал, чтения вслух (без «читка»: читка сценария с музыкой не тишина)", ("тишина",),
         pattern=r"читальн|чтени[яе] вслух|библиотечн\w+ вечер"),
    Rule("kw-walk", "неспешная прогулка, лесные тропы, ботанический сад, дендрарий", ("покой", "природа"),
         pattern=r"неспешн\w+ прогулк|тих\w+ прогулк|лесны\w+ тропы|ботаническ\w+ сад|дендрарий"),
    Rule("kw-nostalgia", "ретро (кроме «ретроспективы»), 80-х, 90-х, пластинки", ("ностальгия",),
         pattern=r"\bретро(?!спектив)|\b80-х|\b90-х|пластинк"),
    Rule("kw-ritual", "ритуалы, обряды, традиционное", ("ритуал",), pattern=r"ритуал|\bобряд|традиционн|буддийск"),
    Rule("kw-freedom", "импровизация, свобода", ("свобода",), pattern=r"импровизац|\bсвобод(а|ы|е|у|ой)\b"),
    Rule("kw-adventure", "квест, приключение, картинг, экстрим", ("приключение",), pattern=r"\bквест|приключен|картинг|экстрим"),
    Rule("kw-taste", "дегустация, гастрономия, тематический ужин", ("вкус",),
         pattern=r"дегустац|гастрошапито|гастрономическ|тематический ужин|поужинать"),
    Rule("kw-status", "закрытый деловой вечер, гала, премия", ("статус",), pattern=r"закрыт(ый|ого) (деловой )?вечер|\bгала\b|\bпремия\b"),
    Rule("kids-audience", "уже стоит audience_kids и в тексте дети/семейное", ("дети",), pattern=r"\bдет|семейн", needs_kids=True),
    Rule("kw-family", "семейный формат (аудитория без audience_kids): «семейный — в 13:00», «семейно-дружеский», «детская»",
         ("семья",), pattern=r"семейный — в|семейно-дружеск|воскресная — детская|для всей семьи|для детей|с детьми",
         exclude=r"без детей"),
)
assert all(t in KNOWN_TAGS for r in RULES for t in r.tags), "правило ссылается на неизвестный тег"


# ─── Переклассификация в деловые категории (сегмент «Дело») ───
@dataclass(frozen=True)
class CategoryRule:
    id: str
    what: str                         # для отчёта куратору
    target: str                       # одна из BUSINESS_CATS
    pattern: str                      # формат события по тексту
    require: str | None = None        # деловой признак, без которого правило не срабатывает
    exclude: str | None = None


# Откуда забираем: только категории, где деловые события прятались среди досуга. Театр, вечеринки, джаз и спорт не трогаем
# («клуб» там значит площадку, а не бизнес-клуб).
BUSINESS_SOURCE = ("Управление и стратегия", "Предприниматели и клубы", "ИИ и технологии", "Нетривиальное")
BUSINESS_SIGNAL = (r"бизнес|компани|корпоратив|руководител|предпринимат|\bb2b|\bceo\b|\bcfo\b|индустри|отрасл|рынк|стартап|инвест|"
                   r"менеджер|управленц|управля|директор|основател|фаундер|маркетинг|финанс|кредит|грант|стратеги|нетворкинг")
CATEGORY_RULES: tuple[CategoryRule, ...] = (
    CategoryRule("biz-breakfast", "бизнес-завтрак, деловой завтрак, утро основателей", "Бизнес-завтраки",
                 r"бизнес-завтрак|деловой завтрак|утро основателей|founders coffee|завтрак (для )?предпринимат"),
    CategoryRule("biz-conference", "конференция, форум, саммит, симпозиум, демодень, митап, круглый стол, открытые дни — с деловым "
                 "признаком в тексте; лекции не трогаем", "Конференции и форумы",
                 r"конференц|\bфорум|саммит|симпозиум|демодень|демо-день|митап|круглый стол|открытые дни|открытие технологического центра",
                 require=BUSINESS_SIGNAL, exclude=r"\bлекци"),
    CategoryRule("biz-education", "мастер-класс, деловая игра, интенсив, практикум, программа для руководителей и управленцев",
                 "Образование для управленцев",
                 r"мастер-класс|деловая игра|интенсив|практикум|для руководител|для управленц|как управлять|программ[аы] .{0,40}(сколково|mba)",
                 require=r"руководител|управленц|управля|переговор|предпринимат|менеджер|лидер|основател"),
    CategoryRule("biz-club", "бизнес-клуб, закрытый деловой вечер, нетворкинг предпринимателей, вечер историй клуба", "Закрытые клубы",
                 r"бизнес-клуб|деловой вечер|нетворкинг|клуб предпринимат|вечер историй", require=BUSINESS_SIGNAL),
)
assert all(r.target in BUSINESS_CATS for r in CATEGORY_RULES)


def category_rule_for(ev: dict) -> CategoryRule | None:
    """Первое правило, подходящее событию по тексту (без учёта текущей категории) — для отчёта и переклассификации."""
    text = event_text(ev)
    for rule in CATEGORY_RULES:
        if not re.search(rule.pattern, text):
            continue
        if rule.require and not re.search(rule.require, text):
            continue
        if rule.exclude and re.search(rule.exclude, text):
            continue
        return rule
    return None


def reclassify_event(ev: dict) -> tuple[dict, CategoryRule | None]:
    """Событие из досуговой категории-источника, по тексту деловое → бизнес-категория. Уже деловое не трогаем (идемпотентно)."""
    if ev.get("category") not in BUSINESS_SOURCE:
        return ev, None
    rule = category_rule_for(ev)
    if rule is None:
        return ev, None
    return {**ev, "category": rule.target}, rule


def homepage_links(events: list[dict]) -> list[dict]:
    """Ссылки «К билетам», ведущие на главную сайта источника (путь пустой, без запроса и якоря) — проверить куратору."""
    from urllib.parse import urlparse

    out = []
    for ev in events:
        u = urlparse(ev.get("url") or "")
        if u.scheme and not u.path.strip("/") and not u.query and not u.fragment:
            out.append(ev)
    return out


def event_text(ev: dict) -> str:
    return " ".join(str(ev.get(k) or "") for k in ("title", "subcategory", "description", "why_fit_hint")).lower()


def matches(rule: Rule, ev: dict) -> bool:
    if rule.category and ev.get("category") != rule.category:
        return False
    if rule.needs_kids and not ev.get("audience_kids"):
        return False
    text = event_text(ev)
    if rule.pattern and not re.search(rule.pattern, text):
        return False
    if rule.exclude and re.search(rule.exclude, text):
        return False
    return True


def retag_event(ev: dict) -> tuple[dict, list[tuple[str, list[str]]]]:
    """(событие с добавленными тегами, [(id правила, добавленные им теги)])."""
    tags = list(ev.get("tags") or [])
    fired: list[tuple[str, list[str]]] = []
    for rule in RULES:
        if matches(rule, ev):
            added = [t for t in rule.tags if t not in tags]
            tags += added
            if added:
                fired.append((rule.id, added))
    return {**ev, "tags": tags}, fired


# Теги прототипа, которые правила тоже умеют ставить: в исходной разметке они были, поэтому в «до» их не снимаем.
PROTOTYPE_TAGS = frozenset({"тело", "природа"})


def baseline(events: list[dict]) -> list[dict]:
    """Исходная разметка: событие без тегов, которые умеют ставить правила (кроме тегов прототипа). Нужна, чтобы отчёт «было → стало»
    не терял смысл после первого прогона (файл seed уже размечен, повторный запуск ничего не меняет)."""
    added = {t for r in RULES for t in r.tags} - PROTOTYPE_TAGS
    return [{**e, "tags": [t for t in e.get("tags") or [] if t not in added]} for e in events]


def coverage(events: list[dict]) -> dict[str, int]:
    """Сколько событий сильно задевают каждую ценность (вес тега не ниже 0.6) — замер из аудита, раздел 1."""
    out = {v: 0 for v in VALUES}
    for ev in events:
        for v in {v for t in ev.get("tags") or [] for v, k in VALUE_MAP.get(t, ()) if k >= STRONG}:
            out[v] += 1
    return out


def multi_value_stats(events: list[dict]) -> float:
    return sum(len({v for t in e.get("tags") or [] for v, k in VALUE_MAP.get(t, ()) if k >= STRONG}) for e in events) / len(events)


def retag(events: list[dict]) -> tuple[list[dict], dict]:
    out, info = [], {"fired": defaultdict(list), "tagged": 0, "added": Counter(), "moved": defaultdict(list)}
    for ev in events:
        ev, crule = reclassify_event(ev)
        if crule is not None:
            info["moved"][crule.id].append(ev)
        new, fired = retag_event(ev)
        out.append(new)
        if fired:
            info["tagged"] += 1
            for rid, tags in fired:
                info["fired"][rid].append(ev)
                info["added"].update(tags)
    return out, info


def render_report(before: list[dict], after: list[dict], info: dict) -> str:
    cb, ca = coverage(before), coverage(after)
    L = ["# Доразметка seed (seed/retag.py)", "",
         "Детерминированные правила по категории и ключевым словам в названии, описании и «почему подойдёт»; без модели. "
         "Теги только добавляются. «Было» — исходная разметка (без тегов, которые умеют ставить правила). Основание — `docs/VALUES-AUDIT.md`, разделы 3–4. Файл `RETAG.md` пересоздаётся командой "
         "`python -m leisure.seed.retag`; повторный запуск на уже размеченном seed ничего не меняет.", "",
         f"Событий в seed: {len(after)}. Получили хотя бы один новый тег: **{info['tagged']}**. "
         f"Добавлено тегов: {sum(info['added'].values())} ({', '.join(f'{t} {n}' for t, n in info['added'].most_common())}).", "",
         f"Ценностей на событие с весом тега не ниже 0.6: было {multi_value_stats(before):.2f}, стало {multi_value_stats(after):.2f}.", "",
         "## Покрытие 19 ценностей (замер из аудита, раздел 1)", "", "| Ценность | Было | Стало |", "|---|---|---|"]
    for v in VALUES:
        flag = " **(нет событий)**" if ca[v] == 0 else ""
        L.append(f"| {v} | {cb[v]} | {ca[v]}{flag} |")
    empty = [v for v in VALUES if ca[v] == 0]
    L += ["", "Ценности без единого события: " + (", ".join(empty) if empty else "нет") + "."]
    if empty:
        L += ["", "Это не недоработка правил, а отсутствие таких событий в seed: ни в названиях, ни в описаниях нет слов про "
              "заботу, помощь, волонтёрство или благотворительность, и ставить тег «на всякий случай» значило бы врать подборке. "
              "Закрывается новыми источниками (волонтёрские и благотворительные события) или ручной разметкой куратора."]
    care = [e for e in after if any(v == "Забота" and k >= STRONG for t in e.get("tags") or [] for v, k in VALUE_MAP.get(t, ()))]
    calm = [e for e in after if any(v == "Покой" and k >= STRONG for t in e.get("tags") or [] for v, k in VALUE_MAP.get(t, ()))]
    motive = ("kw-volunteer", "kw-charity", "kw-care", "kw-body-calm", "kw-spa", "kw-reading", "kw-walk", "kw-calm", "kw-quiet", "kw-quiet2")
    fired = ", ".join(f"`{r}` {len(info['fired'].get(r, []))}" for r in motive)
    L += ["", "## Забота и Покой после правил", "",
          f"Событий на текущем seed: «Забота» {len(care)} (было {cb['Забота']}), «Покой» {len(calm)} (было {cb['Покой']}). "
          f"Срабатывания правил мотивов на seed: {fired}. Правила нацелены на карточки новых источников (фонды, субботники, йога, "
          "библиотеки, ботанический сад); пока таких событий в seed нет, «Забота» остаётся без событий."]
    fx = HERE.parent / "tests" / "fixtures" / "motive_fragments.json"
    if fx.exists():
        cards = json.loads(fx.read_text(encoding="utf-8"))["cards"]
        ok = 0
        for c in cards:
            tags = set(retag_event({"title": c["title"], "description": c["text"], "category": "Нетривиальное", "tags": []})[0]["tags"])
            ok += set(c.get("want", [])) <= tags and not (set(c.get("want_not", [])) & tags)
        L += ["", f"На живых карточках `tests/fixtures/motive_fragments.json`: {ok} из {len(cards)} получают нужные теги и не получают лишних "
                  "(название песни «Тишина» и «потом будет тишина» тег `тишина` не ставят)."]
    L += ["", "## Правила и их срабатывания (для выборочной проверки куратором)", ""]
    for rule in RULES:
        evs = info["fired"].get(rule.id, [])
        L.append(f"### {rule.id}: {rule.what} → {', '.join(rule.tags)} ({len(evs)})")
        if not evs:
            L += ["", "Срабатываний нет.", ""]
            continue
        L.append("")
        for ev in evs:
            L.append(f"- {ev['title'][:90]} · {ev['category']} · `{ev['slug']}`")
        L.append("")
    L += ["## Деловые категории (сегмент «Дело»)", "",
          "События из категорий " + ", ".join(f"«{c}»" for c in BUSINESS_SOURCE) + " переносятся в бизнес-категории каталога по "
          "формату (конференция, завтрак, мастер-класс, клуб) и деловому признаку в тексте. Театр, вечеринки, джаз и спорт правила "
          "не трогают. Ошибочный перенос правится в `seed/events_2026-10-23.json` и исключением в `CATEGORY_RULES`.", ""]
    by_cat: dict[str, list[dict]] = {c: [] for c in BUSINESS_CATS}
    for ev in after:
        if ev.get("category") in by_cat:
            by_cat[ev["category"]].append(ev)
    L.append("| Категория | Событий | Правило |")
    L.append("|---|---|---|")
    for rule in CATEGORY_RULES:
        L.append(f"| {rule.target} | {len(by_cat[rule.target])} | `{rule.id}`: {rule.what} |")
    L.append("")
    for cat, evs in by_cat.items():
        L.append(f"### {cat} ({len(evs)})")
        L.append("")
        for ev in sorted(evs, key=lambda e: (e.get('dates') or [''])[0]):
            rule = category_rule_for(ev)
            L.append(f"- {ev['title'][:90]} · {(ev.get('dates') or ['—'])[0]} · `{ev['slug']}` · {('`' + rule.id + '`') if rule else 'без правила'}")
        L.append("")
    home = homepage_links(after)
    L += [f"## Проверить куратору: ссылка «К билетам» ведёт на главную источника ({len(home)})", "",
          "Это данные, а не код: у этих событий `url` — корень сайта, человек не попадает на страницу события или билетов. "
          "Нужна прямая ссылка от источника или пометка «билеты на сайте».", ""]
    for ev in home:
        L.append(f"- {ev['title'][:90]} · `{ev['slug']}` · {ev['url']}")
    L.append("")
    L += ["## Что проверить в первую очередь", "",
          "Правила со словом-подстрокой, где возможны ложные срабатывания: `kw-meaning` («смысл» встречается и в научных "
          "лекциях), `kw-quiet` и `kw-calm` (слово в описании не всегда значит спокойное событие), `kw-nostalgia` "
          "(«ретро» в описании группы или музея), `kw-family` (форматы «семейный сеанс» у событий без отметки audience_kids). "
          "Ошибочный тег убирается правкой `seed/events_2026-10-23.json` и исключением в `retag.py`.", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="не писать файлы; код 1, если seed не совпадает с результатом правил")
    ap.add_argument("--seed", type=Path, default=SEED)
    ap.add_argument("--report", type=Path, default=REPORT)
    args = ap.parse_args(argv)
    current = json.loads(args.seed.read_text(encoding="utf-8"))
    after, _ = retag(current)
    before = baseline(current)
    _, info = retag(before)
    info["moved"] = retag(current)[1]["moved"]
    text = json.dumps(after, ensure_ascii=False, indent=1) + "\n"
    if args.check:
        same = text == args.seed.read_text(encoding="utf-8")
        print("seed совпадает с результатом правил" if same else "seed отличается от результата правил: запусти retag")
        return 0 if same else 1
    args.seed.write_text(text, encoding="utf-8")
    args.report.write_text(render_report(before, after, info), encoding="utf-8")
    changed = sum(a["tags"] != c["tags"] or a["category"] != c["category"] for a, c in zip(after, current))
    moved = sum(len(v) for v in info["moved"].values())
    print(f"размечено событий (от исходной разметки): {info['tagged']}; перенесено в деловые категории сейчас: {moved}; "
          f"изменено сейчас в файле: {changed}; отчёт: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
