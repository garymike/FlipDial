import json
import logging

from flipdial.logging import JsonFormatter, RedactFilter, redact


def test_redact_email_and_phone():
    out = redact("saved jane@studio.example +1 312 555 0100")
    assert "jane@studio.example" not in out
    assert "555" not in out
    assert "[email]" in out and "[phone]" in out


def test_json_log_is_redacted(capsys):
    logger = logging.getLogger("flipdial.test")
    handler = logging.StreamHandler()
    handler.addFilter(RedactFilter())
    handler.setFormatter(JsonFormatter())
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.warning("sync failed for %s", "jane@studio.example", extra={"uid": "abc123"})
    line = capsys.readouterr().err.strip()
    entry = json.loads(line)
    assert entry["uid"] == "abc123"
    assert "jane@studio.example" not in line


def test_ids_are_not_mistaken_for_phone_numbers():
    from flipdial.logging import redact

    assert redact("card 20261124T004812-0866bbd0a5 done") == "card 20261124T004812-0866bbd0a5 done"
    assert redact("call (312) 555-0142 now") == "call [phone] now"
    assert redact("+1 312 555 0142") == "[phone]"


def test_id_fields_kept_intact(capsys):
    import logging

    from flipdial.logging import configure_logging

    configure_logging("INFO", "json")
    logging.getLogger("flipdial.t").info("x", extra={"card_id": "20261124T004812-0866000123"})
    assert "20261124T004812-0866000123" in capsys.readouterr().out
