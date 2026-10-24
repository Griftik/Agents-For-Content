from urllib.parse import parse_qs, urlparse

from leisure.core.links import gcal_url, ics_text, outlook_url, plan_text, share_text, tg_share_url


def _q(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_gcal_and_outlook(by_slug):
    ev = by_slug["ges2-pocket-ongon-oct24"]  # 13:00–15:00
    q = _q(gcal_url(ev, "2026-10-24"))
    assert q["dates"] == "20261024T130000/20261024T150000" and q["ctz"] == "Europe/Moscow"
    assert q["location"].startswith("Ателье Дома культуры «ГЭС-2», Болотная наб., 15, м. Кропоткинская / Полянка, Москва")
    assert ev["url"] in q["details"] and q["text"] == ev["title"]
    o = _q(outlook_url(ev, "2026-10-24"))
    assert o["startdt"] == "2026-10-24T13:00:00" and o["enddt"] == "2026-10-24T15:00:00" and o["allday"] == "false"


def test_all_day_links():
    ev = {"title": "Фестиваль", "dates": ["2026-10-24"], "time_text": "", "venue": "Парк", "address": "", "metro": ""}
    assert _q(gcal_url(ev))["dates"] == "20261024/20261025"
    assert _q(outlook_url(ev))["allday"] == "true"
    assert _q(gcal_url(ev))["location"] == "Парк"


def test_share_text_and_tg(by_slug):
    ev = by_slug["ges2-pocket-ongon-oct24"]
    text = share_text(ev, "2026-10-24")
    lines = text.split("\n")
    assert lines[0] == ev["title"] and lines[1] == "24 окт, 13:00–15:00"
    assert any(l.startswith("Цена: ") for l in lines) and lines[-1] == ev["why_fit_hint"]
    url = tg_share_url(ev, "2026-10-24", url="https://example.org/e/ongon")
    q = _q(url)
    assert url.startswith("https://t.me/share/url?") and q["url"] == "https://example.org/e/ongon" and q["text"].split("\n")[:2] == lines[:2]
    assert len(url) <= 1800


def test_ics(by_slug):
    ev = by_slug["ges2-pocket-ongon-oct24"]
    ics = ics_text(ev, "2026-10-24")
    assert "BEGIN:VCALENDAR" in ics and "DTSTART;TZID=Europe/Moscow:20261024T130000" in ics
    assert "DTEND;TZID=Europe/Moscow:20261024T150000" in ics and "SUMMARY:" in ics and ics.endswith("END:VCALENDAR\r\n")
    assert "\\," in ics  # запятые в адресе экранированы


def test_plan_text(by_slug, weekend):
    a, b = by_slug["ges2-pocket-ongon-oct24"], by_slug["winzavod-new-season-oct2026"]
    text = plan_text({weekend[1]: [b, a]}, weekend, horizon=[])
    assert text.startswith("План на 23–25 октября\n\nСуббота, 24 окт\n")
    lines = text.split("\n")
    assert lines[3].startswith("• 12:00–20:00 — ") and lines[4].startswith("• 13:00–15:00 — ")  # по времени


def test_ics_lines_folded():
    ev = {"title": "Очень длинное название события " * 6, "dates": ["2026-10-24"], "time_text": "19:00",
          "venue": "Площадка", "address": "Длинный адрес, дом 1, строение 2", "metro": "Метро", "description": "Описание " * 40}
    ics = ics_text(ev, "2026-10-24")
    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n"))
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:Очень длинное название события " in unfolded and "END:VCALENDAR" in unfolded


def test_tg_share_url_fits_limit_for_all_seed_events(seed_events):
    """Д15: URL кнопки «Другу» не длиннее 1 800 символов ни для одного события seed и любого его дня."""
    from urllib.parse import unquote_plus

    worst = 0
    for ev in seed_events:
        for day in (ev["dates"] or [None]):
            url = tg_share_url(ev, day, url=f"https://leisure.example.org/e/{ev['slug']}", why=ev.get("why_fit_hint"))
            worst = max(worst, len(url))
            assert len(url) <= 1800, ev["slug"]
            q = _q(url)
            assert q["text"].split("\n")[0].startswith(ev["title"][:20]) and q["url"].endswith(ev["slug"])
    assert worst > 0
    assert unquote_plus("%D0%B0") == "а"


def test_tg_share_url_truncates_huge_title_and_drops_optional():
    ev = {"title": "Очень длинное название " * 80, "dates": ["2026-10-24"], "time_text": "19:00", "venue": "Зал",
          "address": "ул. Длинная, 1", "price_text": "1 000 ₽", "description": "Описание " * 100}
    url = tg_share_url(ev, "2026-10-24", url="https://x.org/e/a")
    assert len(url) <= 1800 and _q(url)["text"].split("\n")[0].endswith("…")


def test_tg_share_url_keeps_optional_when_short():
    ev = {"title": "Концерт", "dates": ["2026-10-24"], "time_text": "19:00", "venue": "Зал", "address": "ул. А, 1",
          "price_text": "500 ₽", "description": "Коротко о главном"}
    lines = _q(tg_share_url(ev, "2026-10-24", url="https://x.org/e/a"))["text"].split("\n")
    assert lines[0] == "Концерт" and lines[1] == "24 окт, 19:00" and "Цена: 500 ₽" in lines and lines[-1] == "Коротко о главном"


def test_is_local_url():
    from leisure.core.links import is_local_url
    assert is_local_url("http://localhost:8000") and is_local_url("http://127.0.0.1/x") and is_local_url("http://[::1]:8000")
    assert not is_local_url("https://leisure.example.org") and not is_local_url("")


def test_calendar_urls_fit_button_limit_for_all_seed_events(seed_events):
    """Кнопки «Google Календарь» и «Outlook» тоже не длиннее 1 800 символов; ссылка на источник в описании остаётся."""
    for ev in seed_events:
        day = (ev["dates"] or [None])[0]
        g, o = gcal_url(ev, day), outlook_url(ev, day)
        assert len(g) <= 1800 and len(o) <= 1800, ev["slug"]
        if ev.get("url"):
            assert ev["url"] in _q(g)["details"] and ev["url"] in _q(o)["body"]
    long_ev = {**seed_events[0], "description": "Очень длинное описание. " * 200}
    assert len(gcal_url(long_ev)) <= 1800 and len(ics_text(long_ev)) > 4000    # .ics описание не режет
