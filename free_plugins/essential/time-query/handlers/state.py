import json
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional


class TimeQueryStateStore:
    """
    Thread-safe local JSON-backed store for time_query state.

    Scope:
    - stopwatch state
    - alarm state
    - saved clocks

    Notes:
    - durable only to local filesystem
    - single-host safe
    - not multi-instance distributed-safe
    - uses atomic file replacement to reduce corruption risk
    """

    _instance = None
    _instance_lock = threading.Lock()

    DEFAULT_STOPWATCH_STATE: Dict[str, Any] = {}
    DEFAULT_ALARM_STATE: List[Dict[str, Any]] = []
    DEFAULT_CLOCK_STATE: List[str] = ["UTC", "America/New_York"]

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super(TimeQueryStateStore, cls).__new__(cls)
                cls._instance._init_store()
        return cls._instance

    def _init_store(self) -> None:
        self._io_lock = threading.RLock()
        self.storage_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "storage")
        )
        os.makedirs(self.storage_dir, exist_ok=True)

        self.stopwatch_state = self._load(
            "stopwatch",
            self.DEFAULT_STOPWATCH_STATE.copy(),
            expected_type=dict,
        )
        self.alarm_state = self._load(
            "alarm",
            list(self.DEFAULT_ALARM_STATE),
            expected_type=list,
        )
        self.clock_state = self._load(
            "clocks",
            list(self.DEFAULT_CLOCK_STATE),
            expected_type=list,
        )

    def _get_path(self, key: str) -> str:
        return os.path.join(self.storage_dir, f"{key}_state.json")

    def _load(self, key: str, default: Any, expected_type: Optional[type] = None) -> Any:
        path = self._get_path(key)
        with self._io_lock:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except FileNotFoundError:
                return default
            except json.JSONDecodeError:
                return default
            except OSError:
                return default

        if expected_type and not isinstance(data, expected_type):
            return default

        return data

    def _atomic_write_json(self, path: str, data: Any) -> None:
        directory = os.path.dirname(path)
        fd, temp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=2, sort_keys=False)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _save(self, key: str, data: Any) -> None:
        path = self._get_path(key)
        with self._io_lock:
            self._atomic_write_json(path, data)

    # ------------------------------------------------------------------
    # Stopwatch state
    # ------------------------------------------------------------------

    def get_stopwatch(self) -> Dict[str, Any]:
        with self._io_lock:
            return dict(self.stopwatch_state)

    def save_stopwatch(self, data: Dict[str, Any]) -> None:
        normalized = data if isinstance(data, dict) else {}
        with self._io_lock:
            self.stopwatch_state = normalized
            self._save("stopwatch", normalized)

    def get_stopwatch_entry(self, stopwatch_id: str) -> Optional[Dict[str, Any]]:
        with self._io_lock:
            entry = self.stopwatch_state.get(stopwatch_id)
            return dict(entry) if isinstance(entry, dict) else None

    def set_stopwatch_entry(self, stopwatch_id: str, entry: Dict[str, Any]) -> None:
        if not isinstance(entry, dict):
            return
        with self._io_lock:
            self.stopwatch_state[stopwatch_id] = entry
            self._save("stopwatch", self.stopwatch_state)

    def delete_stopwatch_entry(self, stopwatch_id: str) -> bool:
        with self._io_lock:
            removed = self.stopwatch_state.pop(stopwatch_id, None)
            self._save("stopwatch", self.stopwatch_state)
            return removed is not None

    # ------------------------------------------------------------------
    # Alarm state
    # ------------------------------------------------------------------

    def get_alarms(self) -> List[Dict[str, Any]]:
        with self._io_lock:
            return [dict(item) for item in self.alarm_state if isinstance(item, dict)]

    def save_alarms(self, data: List[Dict[str, Any]]) -> None:
        normalized = [dict(item) for item in data if isinstance(item, dict)]
        with self._io_lock:
            self.alarm_state = normalized
            self._save("alarm", normalized)

    def get_alarm_by_id(self, alarm_id: str) -> Optional[Dict[str, Any]]:
        with self._io_lock:
            for alarm in self.alarm_state:
                if isinstance(alarm, dict) and alarm.get("alarm_id") == alarm_id:
                    return dict(alarm)
        return None

    def upsert_alarm(self, alarm: Dict[str, Any]) -> None:
        if not isinstance(alarm, dict):
            return

        alarm_id = alarm.get("alarm_id")
        if not alarm_id:
            return

        with self._io_lock:
            updated = False
            for index, existing in enumerate(self.alarm_state):
                if isinstance(existing, dict) and existing.get("alarm_id") == alarm_id:
                    self.alarm_state[index] = dict(alarm)
                    updated = True
                    break

            if not updated:
                self.alarm_state.append(dict(alarm))

            self._save("alarm", self.alarm_state)

    def delete_alarm(self, alarm_id: str) -> Optional[Dict[str, Any]]:
        with self._io_lock:
            for index, existing in enumerate(self.alarm_state):
                if isinstance(existing, dict) and existing.get("alarm_id") == alarm_id:
                    removed = self.alarm_state.pop(index)
                    self._save("alarm", self.alarm_state)
                    return dict(removed)
        return None

    # ------------------------------------------------------------------
    # Clock state
    # ------------------------------------------------------------------

    def get_clocks(self) -> List[str]:
        with self._io_lock:
            return [item for item in self.clock_state if isinstance(item, str)]

    def save_clocks(self, data: List[str]) -> None:
        normalized = [item for item in data if isinstance(item, str) and item.strip()]
        with self._io_lock:
            self.clock_state = normalized
            self._save("clocks", normalized)

    def add_clock(self, timezone_name: str) -> None:
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            return
        with self._io_lock:
            if timezone_name not in self.clock_state:
                self.clock_state.append(timezone_name)
                self._save("clocks", self.clock_state)

    def remove_clock(self, timezone_name: str) -> bool:
        with self._io_lock:
            if timezone_name in self.clock_state:
                self.clock_state.remove(timezone_name)
                self._save("clocks", self.clock_state)
                return True
        return False

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_storage_metadata(self) -> Dict[str, Any]:
        return {
            "storage_type": "local_json_files",
            "durable": True,
            "distributed_safe": False,
            "storage_dir": self.storage_dir,
        }