"""Google Sheets: одна строка на лида, повторный синк обновляет её, а не добавляет новую."""
from bot.services.cards import SHEET_COLUMNS
from bot.services.crm import SheetsBackend


class FakeWS:
    def __init__(self):
        self.rows = [list(SHEET_COLUMNS)]

    def col_values(self, n):
        return [r[n - 1] for r in self.rows]

    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))

    def update(self, values, cell, value_input_option=None):
        self.rows[int(cell[1:]) - 1] = list(values[0])


def row(uid, segment):
    r = [""] * len(SHEET_COLUMNS)
    r[SHEET_COLUMNS.index("user_id")] = str(uid)
    r[SHEET_COLUMNS.index("segment")] = segment
    return r


def test_upsert_by_user_id():
    b = SheetsBackend("sa.json", "sheet", "leads")
    b._ws = FakeWS()
    b.upsert_sync(row(1, "warm"))
    b.upsert_sync(row(2, "hot"))
    b.upsert_sync(row(1, "hot"))  # обновление, не новая строка
    rows = b._ws.rows
    assert len(rows) == 3
    assert rows[1][SHEET_COLUMNS.index("segment")] == "hot"
