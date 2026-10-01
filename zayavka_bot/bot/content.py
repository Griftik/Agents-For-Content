"""Загрузка и проверка YAML из content/. Перечитывается командой /reload без рестарта.

Если новый YAML невалиден, остаётся старый — бот не падает из-за опечатки в тексте.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REQUIRED_TEXTS = [
    "welcome", "start_button", "resume", "resume_button", "restart_button", "already_done",
    "menu_buttons", "progress", "back_button", "skip_button", "teaser_intro", "ask_contact",
    "contact_button", "consent_line", "contact_later_button", "ask_company",
    "company_skip_button", "report_pending", "report_sent_intro", "report_next_button",
    "hot_offer", "hot_button", "hot_booking_url_text", "hot_reminder_24h", "hot_reminder_72h",
    "warm_intro", "warm_button", "initiator_intro", "specialist_docs", "specialist_channel",
    "specialist_channel_button", "specialist_training_ask", "yes_button", "no_button",
    "text_forwarded", "notify_on", "notify_off", "notify_toggled", "delete_confirm",
    "delete_done", "error_generic", "admin_card", "admin_buttons", "segment_labels",
    "segment_icons", "consent_off", "consent_on", "consent_policy_button", "consent_needed",
    "digest_channel_button", "menu_open_button", "app_next_button", "app_close_button",
    "app_docs_sent", "app_report_in_chat", "app_contact_wait", "app_company_placeholder",
    "app_subscription_active", "app_policy_links",
]
SEGMENTS = {"hot", "warm", "warm_initiator", "specialist"}


class ContentError(ValueError):
    pass


@dataclass
class Question:
    code: str
    text: str
    options: list[tuple[str, str]]  # (code, text)
    skippable: bool = False
    branch: dict[str, str] = field(default_factory=dict)

    def label(self, a_code: str | None) -> str | None:
        for c, t in self.options:
            if c == a_code:
                return t
        return None


@dataclass
class Content:
    questions: list[Question]
    specialist_need: Question
    texts: dict[str, Any]
    insights: dict[str, Any]
    scoring: dict[str, Any]
    mapping: dict[str, Any]
    subscription: dict[str, Any] = field(default_factory=dict)
    company_text: str = ""
    company_skip: str = ""

    # --- вопросы ----------------------------------------------------------
    @property
    def order(self) -> list[str]:
        return [q.code for q in self.questions]

    def question(self, code: str) -> Question | None:
        if code == self.specialist_need.code:
            return self.specialist_need
        for q in self.questions:
            if q.code == code:
                return q
        return None

    def label(self, q_code: str, a_code: str | None) -> str | None:
        q = self.question(q_code)
        return q.label(a_code) if q else None

    def t(self, key: str, **kw: Any) -> str:
        """Текст из texts.yaml с подстановкой. Не хватает переменной — оставляем как есть."""
        val = self.texts[key]
        if not isinstance(val, str):
            raise KeyError(key)
        val = val.rstrip("\n")
        return val.format_map(_Default(kw)) if kw else val


class _Default(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class _Loader(yaml.SafeLoader):
    """SafeLoader без чисел с подчёркиванием: YAML 1.1 читает код 15_50 как 1550."""


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag not in ("tag:yaml.org,2002:int", "tag:yaml.org,2002:float")]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^[-+]?(0|[1-9][0-9]*)$"), list("-+0123456789")
)
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float", re.compile(r"^[-+]?([0-9]+\.[0-9]*|\.[0-9]+)$"), list("-+.0123456789")
)


def _read(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=_Loader)  # noqa: S506 — это SafeLoader


def _q(raw: dict) -> Question:
    return Question(
        code=str(raw["code"]),
        text=str(raw["text"]),
        # YAML читает коды вида 15_50 как int — приводим к строке
        options=[(str(o["code"]), str(o["text"])) for o in raw["options"]],
        skippable=bool(raw.get("skippable", False)),
        branch={str(k): str(v) for k, v in (raw.get("branch") or {}).items()},
    )


def load_content(content_dir: Path) -> Content:
    qraw = _read(content_dir / "questions.yaml")
    c = Content(
        questions=[_q(q) for q in qraw["questions"]],
        specialist_need=_q(qraw["specialist_need"]),
        texts=_read(content_dir / "texts.yaml"),
        insights=_read(content_dir / "insights.yaml"),
        scoring=_normalize_scoring(_read(content_dir / "scoring.yaml")),
        mapping=_read(content_dir / "mapping.yaml"),
        subscription=_read(content_dir / "subscription.yaml") if (content_dir / "subscription.yaml").exists() else {},
        company_text=str((qraw.get("company") or {}).get("text", "")),
        company_skip=str((qraw.get("company") or {}).get("skip_button", "")),
    )
    validate(c)
    return c


def _normalize_scoring(raw: dict) -> dict:
    raw["points"] = {
        str(q): {str(a): int(p) for a, p in (opts or {}).items()}
        for q, opts in (raw.get("points") or {}).items()
    }
    return raw


def _codes_in(cond: dict | None) -> list[tuple[str, str]]:
    out = []
    for q, v in (cond or {}).items():
        vals = v if isinstance(v, list) else [v]
        out += [(str(q), str(x)) for x in vals]
    return out


def validate(c: Content) -> None:
    """Все коды в скоринге, маппинге и тизерах должны существовать в questions.yaml."""
    errors: list[str] = []

    def check(where: str, pairs: list[tuple[str, str]]) -> None:
        for q, a in pairs:
            qq = c.question(q)
            if qq is None:
                errors.append(f"{where}: нет вопроса {q}")
            elif qq.label(a) is None:
                errors.append(f"{where}: у вопроса {q} нет варианта {a}")

    if len(c.questions) != 11:
        errors.append(f"questions.yaml: ожидается 11 вопросов, найдено {len(c.questions)}")
    codes = [q.code for q in c.questions]
    if len(set(codes)) != len(codes):
        errors.append("questions.yaml: коды вопросов повторяются")
    for q in c.questions + [c.specialist_need]:
        if not q.options:
            errors.append(f"questions.yaml: у вопроса {q.code} нет вариантов")
        for a, target in q.branch.items():
            if q.label(a) is None:
                errors.append(f"questions.yaml: ветка {q.code}.{a} — нет такого варианта")
            if c.question(target) is None:
                errors.append(f"questions.yaml: ветка ведёт в неизвестный вопрос {target}")
        for code, _ in q.options:
            if len(f"a:{q.code}:{code}".encode()) > 64:
                errors.append(f"questions.yaml: код {q.code}:{code} слишком длинный для кнопки")

    for k in REQUIRED_TEXTS:
        if k not in c.texts:
            errors.append(f"texts.yaml: нет ключа {k}")

    for block in ("first", "second"):
        for i, rule in enumerate(c.insights.get(block) or []):
            check(f"insights.yaml {block}[{i}]", _codes_in(rule.get("when")))
            if not rule.get("text"):
                errors.append(f"insights.yaml {block}[{i}]: нет text")
    d = c.insights.get("default") or {}
    if not d.get("first") or not d.get("second"):
        errors.append("insights.yaml: нужен default.first и default.second")

    for q, opts in c.scoring.get("points", {}).items():
        check("scoring.yaml points", [(q, a) for a in opts])
    for i, rule in enumerate(c.scoring.get("segments") or []):
        if rule.get("segment") not in SEGMENTS:
            errors.append(f"scoring.yaml segments[{i}]: неизвестный сегмент {rule.get('segment')}")
        check(f"scoring.yaml segments[{i}]", _codes_in(rule.get("when")) + _codes_in(rule.get("when_not")))
        ms = rule.get("min_score")
        if ms is not None and ms != "hot_threshold" and not isinstance(ms, int):
            errors.append(f"scoring.yaml segments[{i}]: min_score должен быть числом или hot_threshold")
    if not isinstance(c.scoring.get("hot_threshold"), int):
        errors.append("scoring.yaml: hot_threshold должен быть числом")

    for i, rule in enumerate(c.mapping.get("rules") or []):
        if rule.get("type") not in (c.mapping.get("labels") or {}):
            errors.append(f"mapping.yaml rules[{i}]: тип {rule.get('type')} без подписи в labels")
        for cond in rule.get("any") or []:
            check(f"mapping.yaml rules[{i}]", _codes_in(cond))

    _validate_subscription(c, errors)

    if errors:
        raise ContentError("\n".join(errors))


SUBSCRIPTION_TEXTS = ["menu_button", "pitch", "buy_button", "active", "renew_button", "paid",
                      "expiring", "expired", "price_changed", "unavailable", "offer_line"]


def _validate_subscription(c: Content, errors: list[str]) -> None:
    sc = c.subscription
    if not sc:
        return
    for k in ("price_rub", "price_stars", "days", "remind_before_days"):
        if not isinstance(sc.get(k, 0), int) or sc.get(k, 0) < 0:
            errors.append(f"subscription.yaml: {k} должен быть целым числом ≥ 0")
    if int(sc.get("days") or 0) < 1:
        errors.append("subscription.yaml: days должен быть ≥ 1")
    texts = sc.get("texts") or {}
    for k in SUBSCRIPTION_TEXTS:
        if k not in texts:
            errors.append(f"subscription.yaml: нет texts.{k}")
    if len(str(sc.get("title") or "")) > 32:
        errors.append("subscription.yaml: title длиннее 32 символов (лимит счёта Telegram)")


# --- глобальный держатель -------------------------------------------------
_content: Content | None = None


def get_content() -> Content:
    if _content is None:
        from bot.config import get_settings

        reload_content(get_settings().content_dir)
    assert _content is not None
    return _content


def reload_content(content_dir: Path) -> Content:
    """Загрузить заново. При ошибке бросает ContentError, старый контент остаётся."""
    global _content
    new = load_content(content_dir)
    _content = new
    return new
