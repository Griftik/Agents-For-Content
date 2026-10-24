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
    assert url.startswith("https://t.me/share/url?") and q["url"] == "https://example.org/e/ongon" and q["text"] == text


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
