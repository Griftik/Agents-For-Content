"""Клавиатуры бота. Только данные (списки кнопок) — удобно тестировать без aiogram."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from leisure.core.catalog import ALL_CATS, COMPANY_OPTIONS, REASONS, SLOTS, VALUES

from .callbacks import REASON_CODES

Button = dict
TOP_N = 5
BUDGETS = [(0, "Без ограничения"), (1000, "до 1 000 ₽"), (2500, "до 2 500 ₽"), (5000, "до 5 000 ₽")]
MARK = "● "
REASON_CAPTION = "Почему мимо? Можно не отвечать"


def _rows(buttons: list[Button], per_row: int) -> list[list[Button]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def values_pick_keyboard(selected: Iterable[str]) -> list[list[Button]]:
    sel = set(selected)
    btns = [{"text": ("✓ " if v in sel else "") + v, "callback_data": f"ob:v:{i}"} for i, v in enumerate(VALUES)]
    rows = _rows(btns, 2)
    if len(sel) == TOP_N:
        rows.append([{"text": "Дальше →", "callback_data": "ob:vnext"}])
    else:
        rows.append([{"text": f"Выбрано {len(sel)} из {TOP_N}", "callback_data": "ob:noop"}])
    return rows


def weight_keyboard(value_idx: int) -> list[list[Button]]:
    return [[{"text": "Важно", "callback_data": f"ob:w:{value_idx}:1"},
             {"text": "Не очень", "callback_data": f"ob:w:{value_idx}:0"}]]


def interests_keyboard(interests: Mapping[str, int]) -> list[list[Button]]:
    labels = {0: "—", 1: "иногда", 2: "интересно", 3: "в первую очередь"}
    btns = [{"text": f"{c} · {labels[int(interests.get(c, 2))]}", "callback_data": f"ob:i:{i}"} for i, c in enumerate(ALL_CATS)]
    return _rows(btns, 1) + [[{"text": "Готово →", "callback_data": "ob:inext"}]]


def company_keyboard() -> list[list[Button]]:
    return _rows([{"text": c, "callback_data": f"ob:c:{i}"} for i, c in enumerate(COMPANY_OPTIONS)], 2)


def times_keyboard(selected: Iterable[str]) -> list[list[Button]]:
    sel = set(selected)
    rows = _rows([{"text": ("✓ " if t in sel else "") + t, "callback_data": f"ob:t:{i}"} for i, t in enumerate(SLOTS)], 2)
    rows.append([{"text": "Дальше →", "callback_data": "ob:tnext"}])
    return rows


def budget_keyboard() -> list[list[Button]]:
    return _rows([{"text": label, "callback_data": f"ob:b:{amount}"} for amount, label in BUDGETS], 2)


def aesthetics_keyboard() -> list[list[Button]]:
    return [[{"text": "Да, важна", "callback_data": "ob:a:1"}, {"text": "Не принципиально", "callback_data": "ob:a:0"}]]


def notes_keyboard() -> list[list[Button]]:
    return [[{"text": "Пропустить", "callback_data": "ob:skipnotes"}]]


def consent_keyboard(policy_url: str | None) -> list[list[Button]]:
    """policy_url=None — без URL-кнопки (WEB_BASE_URL=localhost): ссылка на политику тогда идёт текстом сообщения."""
    rows = [[{"text": "Согласен, поехали", "callback_data": "ob:consent"}]]
    return ([[{"text": "Политика обработки данных", "url": policy_url}]] + rows) if policy_url else rows


def reasons_keyboard(event_id: str) -> list[list[Button]]:
    btns = [{"text": r, "callback_data": f"r:{REASON_CODES[r]}:{event_id}"} for r in REASONS]
    caption = [{"text": REASON_CAPTION, "callback_data": "ob:noop"}]  # подпись, не кнопка действия
    return [caption] + _rows(btns, 2) + [[{"text": "Без причины", "callback_data": f"r:0:{event_id}"}]]


def mark_keyboard(rows: list[list[Button]], active_text: str | None) -> list[list[Button]]:
    """Снимает старую отметку ● и ставит её на кнопку с текстом active_text (Иду / Может быть / Мимо)."""
    out = []
    for row in rows:
        new_row = []
        for b in row:
            text = b["text"][len(MARK):] if b["text"].startswith(MARK) else b["text"]
            if active_text and text == active_text:
                text = MARK + text
            new_row.append({**b, "text": text})
        out.append(new_row)
    return out


def weights_from_choice(top: list[str], important: Iterable[str]) -> dict[str, int]:
    """Веса 0–5 из онбординга: пять главных = 5, «важно» = 3, «не очень» = 1."""
    imp = set(important)
    return {v: 5 if v in top else 3 if v in imp else 1 for v in VALUES}
