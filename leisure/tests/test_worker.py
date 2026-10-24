from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from leisure.worker.schedules import due_weekend

MSK = ZoneInfo("Europe/Moscow")


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=MSK)


@pytest.mark.parametrize("now,day,hour,expected", [
    ("2026-10-22T19:05", 4, 19, "2026-10-23"),   # четверг 19:05 — пора
    ("2026-10-22T18:59", 4, 19, None),           # четверг до 19:00 — прошлый уикенд уже прошёл → ничего
    ("2026-10-23T10:00", 4, 19, "2026-10-23"),   # пятница: час пропущен — досылаем
    ("2026-10-25T23:30", 4, 19, "2026-10-23"),   # воскресенье вечером — ещё этот уикенд
    ("2026-10-26T09:00", 4, 19, None),           # понедельник — уикенд прошёл
    ("2026-10-24T09:30", 6, 9, "2026-10-23"),    # пользователь выбрал субботу 09:00
    ("2026-10-20T20:00", 2, 19, "2026-10-23"),   # вторник 19:00 → ближайший уикенд
])
def test_due_weekend(now, day, hour, expected):
    wk = due_weekend(dt(now), day, hour)
    assert (wk[0] if wk else None) == expected
