"""Проверка ключа API: fail closed без ключа, режим разработки только по явному флагу."""
import pytest
from fastapi import HTTPException

from leisure import settings
from leisure.api.deps import require_api_key
from leisure.core.links import ics_text
from leisure.normalize.schema import EventIn


def test_api_key_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "")
    monkeypatch.setattr(settings, "DEV_OPEN_API", False)
    with pytest.raises(HTTPException) as e:
        require_api_key(None)
    assert e.value.status_code == 503
    monkeypatch.setattr(settings, "DEV_OPEN_API", True)
    require_api_key(None)  # режим разработки — пропускает


def test_api_key_checked(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret")
    with pytest.raises(HTTPException) as e:
        require_api_key("wrong")
    assert e.value.status_code == 401
    with pytest.raises(HTTPException):
        require_api_key(None)
    require_api_key("secret")


def test_ics_url_sanitized():
    ev = {"title": "X", "dates": ["2026-10-24"], "time_text": "19:00", "url": "https://a.example/e\r\nATTENDEE:evil"}
    ics = ics_text(ev, "2026-10-24")
    unfolded = ics.replace("\r\n ", "")
    assert not any(line.startswith("ATTENDEE") for line in unfolded.split("\r\n"))  # инъекции свойства нет
    assert "URL:https://a.example/eATTENDEE:evil" in unfolded
    assert "URL:" not in ics_text({**ev, "url": "javascript:alert(1)"}, "2026-10-24")


def test_schema_url_validation():
    base = {"slug": "ok-event", "title": "Событие для теста", "category": "Джаз", "dates": ["2026-10-24"]}
    assert EventIn.model_validate({**base, "url": " https://x.example/a "}).url == "https://x.example/a"
    with pytest.raises(Exception):
        EventIn.model_validate({**base, "url": "ftp://x"})
    with pytest.raises(Exception):
        EventIn.model_validate({**base, "url": "https://x.example/a b"})
    assert EventIn.model_validate({**base, "sources": ["https://ok.example", "nope", "https://bad.example/a\nb"]}).sources == ["https://ok.example"]
