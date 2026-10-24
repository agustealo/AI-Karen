from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[2] / "free_plugins/essential/time-query/handlers/current_time_handler.py").read_text()

def test_explicit_timezone_precedes_authorized_runtime_timezone():
    explicit = SOURCE.index('params.get("timezone")', SOURCE.index("# Explicit requested timezone"))
    authorized = SOURCE.index('context.get("authorized_timezone")', explicit)
    assert explicit < authorized
    assert 'timezone_source = "authorized_context"' in SOURCE
