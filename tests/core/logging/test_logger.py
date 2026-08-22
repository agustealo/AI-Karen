import json
import logging
from ai_karen_engine.core.logging import get_logger, RuntimeEvents, set_log_context, RuntimeLogContext
from ai_karen_engine.core.logging.formatters import RuntimeJSONFormatter

import sys

def test_logger_event(capsys):
    logger = get_logger("test.logger")
    logger.setLevel(logging.INFO)
    # Setup handler to capture output
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RuntimeJSONFormatter())
    logger.addHandler(handler)
    logger.propagate = False # Avoid double output

    set_log_context(RuntimeLogContext(correlation_id="CORR-1"))
    
    logger.event("test.event", foo="bar")
    
    captured = capsys.readouterr()
    log_record = json.loads(captured.out.strip())
    
    assert log_record["message"] == "test.event"
    assert log_record["correlation_id"] == "CORR-1"
    assert log_record["foo"] == "bar"

def test_exception_redaction(capsys):
    logger = get_logger("test.exception")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RuntimeJSONFormatter(redact_secrets=True))
    logger.addHandler(handler)
    logger.propagate = False

    try:
        raise ValueError("Secret key: abc-1234567890abcdef")
    except ValueError:
        logger.exception("Failed task")
    
    captured = capsys.readouterr()
    log_record = json.loads(captured.out.strip())
    
    assert "abc-123" not in log_record["error_message"]
    assert "[REDACTED]" in log_record["error_message"]
