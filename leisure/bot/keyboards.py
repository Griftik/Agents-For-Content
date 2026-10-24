"""Клавиатуры бота. Только данные (списки кнопок) — удобно тестировать без aiogram. Схема — web/FLOW-ONBOARDING.md."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from leisure.core.catalog import ALL_CATS, COMPANY_OPTIONS, SLOTS, VALUE_CLUSTERS, VALUE_SHORT, VALUES, cat_label

from .callbacks import REASON_CODES

Button = dict
TOP_N = 5
BUDGETS = [(0, "Не важно"), (1000, "до 1 000 ₽"), (2500, "до 2 500 ₽"), (5000, "до 5 000 ₽")]
MARK = "● "
REASON_CAPTION = "Почему мимо? Можно не отвечать"
REASON_LABEL = {"не моё": "Не моё", "дорого": "Дорого", "далеко": "Далеко", "уже был": "Уже был",
                "не в это время": "Не то время", "не та компания": "Не та компания"}
BACK = "← Назад"
LEVEL_MARK = {3: "✓✓ ", 2: "✓ ", 1: "", 0: "— "}
BRUSHES = [(0, "Не показывать"), (1, "Иногда"), (2, "Интересно"), (3, "В первую очередь")]


def _rows(buttons: list[Button], per_row: int) -> list[list[Button]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def back_button(target: str = "ob:go:hi") -> Button:
    return {"text": BACK, "callback_data": target}


def value_label(v: str) -> str:
    return VALUE_SHORT.get(v, v)


# ─── Э1. Ценности ───
def values_pick_keyboard(selected: Iterable[str], back: str = "ob:go:hi") -> list[list[Button]]:
    """19 ценностей группами по два в ряд (группа начинается с нового ряда); «Дальше» — только при пяти."""
    sel = set(selected)
    rows: list[list[Button]] = []
    for names in VALUE_CLUSTERS.values():
        btns = [{"text": ("✓ " if v in sel else "") + value_label(v), "callback_data": f"ob:v:{VALUES.index(v)}"} for v in names]
        rows += _rows(btns, 2)
    if len(sel) == TOP_N:
        rows.append([{"text": "Дальше →", "callback_data": "ob:go:i"}])
    rows.append([back_button(back)])
    return rows


# ─── Э2. Интересы ───
STEP_BUDGETS = [(1000, "до 1 000 ₽"), (2500, "до 2 500 ₽"), (0, "Не важно")]      # значения из BUDGETS


def step_budget_row(current: int = 0) -> list[Button]:
    """Бюджет одной строкой на «Шаге 2»: одно нажатие, выбранное отмечено ●, экран не закрывается."""
    cur = int(current or 0)
    return [{"text": (MARK if cur == amount else "") + label, "callback_data": f"ob:sb:{amount}"} for amount, label in STEP_BUDGETS]


def interests_main_keyboard(shown: list[str], interests: Mapping[str, int], n_all: int, save_text: str = "Показать подборку →",
                            back: str = "ob:go:v", budget: int = 0) -> list[list[Button]]:
    """Предложенные направления (по два в ряд), строка бюджета, «Все направления (N)», главное действие и «← Назад»."""
    btns = [{"text": LEVEL_MARK[int(interests.get(c, 2))] + cat_label(c), "callback_data": f"ob:ct:{ALL_CATS.index(c)}"} for c in shown]
    return _rows(btns, 2) + [step_budget_row(budget), [{"text": f"Все направления ({n_all})", "callback_data": "ob:go:ia"}],
                             [{"text": save_text, "callback_data": "ob:show"}], [back_button(back)]]


def interests_all_keyboard(interests: Mapping[str, int], brush: int, save_text: str = "Показать подборку →") -> list[list[Button]]:
    """Кисть уровня (два ряда по два) и 19 направлений; уровень кисти зашит в callback_data каждого направления."""
    brushes = [{"text": ("● " if lvl == brush else "") + label, "callback_data": f"ob:br:{lvl}"} for lvl, label in BRUSHES]
    cats = [{"text": LEVEL_MARK[int(interests.get(c, 2))] + cat_label(c), "callback_data": f"ob:cs:{i}:{brush}"}
            for i, c in enumerate(ALL_CATS)]
    return (_rows(brushes, 2) + _rows(cats, 2) + [[{"text": save_text, "callback_data": "ob:show"}],
                                                   [{"text": "← К восьми", "callback_data": "ob:go:i"}]])


# ─── Э4. Уточнить под себя ───
def budget_label(amount: int) -> str:
    """Значение бюджета в тексте и в меню: «не важен» | «до 2 500 ₽» (подпись кнопки нуля — «Не важно», см. BUDGETS)."""
    amount = int(amount or 0)
    return f"до {amount:,} ₽".replace(",", " ") if amount > 0 else "не важен"


def setup_menu_keyboard(params: Mapping, has_note: bool = False, dirty: bool = False) -> list[list[Button]]:
    times = ", ".join(params.get("times") or ["день", "вечер"])
    rows = [
        [{"text": f"Бюджет · {budget_label(params.get('budget', 0))}", "callback_data": "ob:go:sb"}],
        [{"text": "Эстетика · " + ("важна" if params.get("aesthetics") else "не принципиальна"), "callback_data": "ob:go:sa"}],
        [{"text": f"Время · {times}", "callback_data": "ob:go:st"}],
        [{"text": "С детьми · " + ("да" if params.get("company") == "с детьми" or params.get("kids") else "нет"),
          "callback_data": "ob:go:sc"}],
    ]
    if dirty:
        rows.append([{"text": "Пересобрать подборку", "callback_data": "ob:redo"}])
    rows.append([{"text": "Готово", "callback_data": "ob:done"}])
    return rows


def budget_keyboard(current: int = 0) -> list[list[Button]]:
    btns = [{"text": (MARK if int(current or 0) == amount else "") + label, "callback_data": f"ob:b:{amount}"} for amount, label in BUDGETS]
    return _rows(btns, 2) + [[back_button("ob:go:s")]]


def aesthetics_keyboard(current: bool | None = None) -> list[list[Button]]:
    return [[{"text": (MARK if current is True else "") + "Да, важна", "callback_data": "ob:a:1"},
             {"text": (MARK if current is False else "") + "Не принципиально", "callback_data": "ob:a:0"}],
            [back_button("ob:go:s")]]


def times_keyboard(selected: Iterable[str]) -> list[list[Button]]:
    sel = set(selected)
    rows = _rows([{"text": ("✓ " if t in sel else "") + t.capitalize(), "callback_data": f"ob:t:{i}"} for i, t in enumerate(SLOTS)], 2)
    return rows + [[{"text": "Готово", "callback_data": "ob:go:s"}], [back_button("ob:go:s")]]


def kids_keyboard(with_kids: bool) -> list[list[Button]]:
    kids, any_ = COMPANY_OPTIONS.index("с детьми"), COMPANY_OPTIONS.index("любая")
    return [[{"text": (MARK if with_kids else "") + "Да, с детьми", "callback_data": f"ob:c:{kids}"},
             {"text": (MARK if not with_kids else "") + "Нет", "callback_data": f"ob:c:{any_}"}],
            [back_button("ob:go:s")]]


def note_keyboard() -> list[list[Button]]:
    return [[back_button("ob:go:s")]]


def consent_keyboard(policy_url: str | None) -> list[list[Button]]:
    """policy_url=None — без URL-кнопки (WEB_BASE_URL=localhost): ссылка на политику тогда идёт текстом сообщения."""
    rows = [[{"text": "Принять и начать", "callback_data": "ob:consent"}]]
    return ([[{"text": "Политика обработки данных", "url": policy_url}]] + rows) if policy_url else rows


def profile_keyboard() -> list[list[Button]]:
    return [[{"text": "Ценности", "callback_data": "ob:go:v"}, {"text": "Интересы", "callback_data": "ob:go:i"}],
            [{"text": "Бюджет, эстетика, время", "callback_data": "ob:go:s"}]]


# ─── причины «Мимо» ───
def reasons_keyboard(event_id: str, more: bool = False) -> list[list[Button]]:
    """Подпись «Почему мимо? Можно не отвечать», затем причины: Не моё · Дорого · Далеко · Уже был и «Ещё…» (остальные две)."""
    caption = [{"text": REASON_CAPTION, "callback_data": "ob:noop"}]  # подпись, не кнопка действия

    def b(reason: str) -> Button:
        return {"text": REASON_LABEL[reason], "callback_data": f"r:{REASON_CODES[reason]}:{event_id}"}

    if more:
        return [caption, [b("не в это время"), b("не та компания")]]
    return [caption, [b("не моё"), b("дорого"), b("далеко"), b("уже был")], [{"text": "Ещё…", "callback_data": f"r:m:{event_id}"}]]


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
