#!/usr/bin/env python3
"""Read-only observation of a paused, same-timeline physical standby.

This is not admission. External custody, source fencing, receipt authenticity
and finality remain required. No promotion or database mutation is performed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_FIELDS = {
    "schema_version", "evidence_type", "system_identifier", "database_name",
    "database_oid", "server_major", "timeline_hex", "required_lsn",
    "observed_flush_lsn", "captured_at",
}
_SQL = """
SELECT json_build_object(
    'system_identifier', (pg_control_system()).system_identifier::text,
    'database_name', current_database(),
    'database_oid', (SELECT oid::text FROM pg_database WHERE datname = current_database()),
    'server_major', current_setting('server_version_num')::int / 10000,
    'in_recovery', pg_is_in_recovery(),
    'read_only', current_setting('transaction_read_only') = 'on',
    'pause_state', CASE WHEN pg_is_in_recovery() THEN pg_get_wal_replay_pause_state() END,
    'checkpoint_timeline', (pg_control_checkpoint()).timeline_id,
    'replay_lsn', pg_last_wal_replay_lsn()::text,
    'receiver_timeline', (SELECT received_tli FROM pg_stat_wal_receiver WHERE status = 'streaming'),
    'receive_lsn', pg_last_wal_receive_lsn()::text
)
"""


class RecoveryHold(ValueError):
    """Fixed diagnostic safe for operator output."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryHold("duplicate receipt field")
        result[key] = value
    return result


def lsn(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{1,8}/[0-9A-Fa-f]{1,8}", value):
        raise RecoveryHold("invalid WAL position")
    high, low = value.split("/")
    return (int(high, 16) << 32) + int(low, 16)


def positive_decimal(value, limit):
    return (
        isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value)
        and int(value) <= limit
    )


def load_receipt(path, expected_digest):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_digest):
        raise RecoveryHold("trusted cutoff digest required")
    with Path(path).open("rb") as source:
        raw = source.read(16385)
    if len(raw) > 16384 or not hmac.compare_digest(
        hashlib.sha256(raw).hexdigest(), expected_digest.lower()
    ):
        raise RecoveryHold("cutoff receipt digest mismatch")
    receipt = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(receipt, dict) or set(receipt) != _FIELDS:
        raise RecoveryHold("incomplete or unknown cutoff receipt")
    if (
        type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
        or receipt["evidence_type"] != "postgres_physical_wal_cutoff"
        or not positive_decimal(receipt["system_identifier"], (1 << 64) - 1)
        or not positive_decimal(receipt["database_oid"], (1 << 32) - 1)
        or not isinstance(receipt["database_name"], str)
        or not receipt["database_name"] or "\x00" in receipt["database_name"]
        or type(receipt["server_major"]) is not int or not 10 <= receipt["server_major"] <= 99
        or not isinstance(receipt["timeline_hex"], str)
        or not re.fullmatch(r"[0-9A-Fa-f]{8}", receipt["timeline_hex"])
        or int(receipt["timeline_hex"], 16) == 0
        or not isinstance(receipt["captured_at"], str)
        or not receipt["captured_at"].endswith("Z")
    ):
        raise RecoveryHold("invalid cutoff receipt")
    datetime.fromisoformat(receipt["captured_at"])
    required = lsn(receipt["required_lsn"])
    if not required or lsn(receipt["observed_flush_lsn"]) < required:
        raise RecoveryHold("unflushed cutoff receipt")
    return receipt


def observe():
    helper = Path(__file__).resolve().with_name("postgres-recovery-client.sh")
    result = subprocess.run(
        [
            "bash", "-c",
            'set -euo pipefail; source "$1"; '
            'select_postgres_recovery_client "$RECOVERY_DATABASE_URL" psql; '
            'exec psql -X -qAt --set=ON_ERROR_STOP=1 --dbname="$RECOVERY_DATABASE_URL" --command="$2"',
            "bash", str(helper), _SQL,
        ],
        # The compatibility probe may itself use an stdin-forwarding wrapper.
        # Never share a SQL input stream with that probe.
        stdin=subprocess.DEVNULL, text=True, capture_output=True, check=False, timeout=30,
    )
    if result.returncode:
        raise RecoveryHold("standby observation unavailable")
    try:
        return json.loads(result.stdout, object_pairs_hook=unique_object)
    except (ValueError, TypeError):
        raise RecoveryHold("standby observation is not valid JSON") from None


def verify(receipt, observation):
    if not isinstance(observation, dict):
        raise RecoveryHold("invalid standby observation")
    if (
        observation.get("in_recovery") is not True
        or observation.get("read_only") is not True
        or observation.get("pause_state") != "paused"
    ):
        raise RecoveryHold("target is not a paused read-only physical standby")
    for key in ("system_identifier", "database_name", "database_oid", "server_major"):
        if observation.get(key) != receipt[key]:
            raise RecoveryHold("source and target identity mismatch")
    timeline = int(receipt["timeline_hex"], 16)
    if (
        observation.get("checkpoint_timeline") != timeline
        or observation.get("receiver_timeline") != timeline
    ):
        raise RecoveryHold("same-timeline streaming evidence unavailable")
    required = lsn(receipt["required_lsn"])
    if lsn(observation.get("replay_lsn")) < required or lsn(observation.get("receive_lsn")) < required:
        raise RecoveryHold("required WAL cutoff not replayed")


def main():
    try:
        receipt = load_receipt(os.environ["RECOVERY_CUTOFF_FILE"], os.environ["RECOVERY_CUTOFF_SHA256"])
        if not os.environ.get("RECOVERY_DATABASE_URL"):
            raise RecoveryHold("recovery database URL required")
        observation = observe()
        verify(receipt, observation)
    except RecoveryHold as error:
        print(f"recovery hold: {error}", file=sys.stderr)
        return 2
    except (KeyError, OSError, ValueError, TypeError, subprocess.SubprocessError):
        # Do not disclose arbitrary receipt text or connection diagnostics.
        print("recovery hold: missing or invalid recovery evidence", file=sys.stderr)
        return 2
    print(json.dumps({
        "evidence_type": "paused_standby_replay_observation",
        "cutoff_sha256": os.environ["RECOVERY_CUTOFF_SHA256"].lower(),
        "required_lsn": receipt["required_lsn"],
        "replay_lsn": observation["replay_lsn"],
        "timeline_hex": receipt["timeline_hex"],
        "admission_verified": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
