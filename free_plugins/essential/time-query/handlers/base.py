import datetime
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
import zoneinfo


@dataclass
class StopwatchState:
    stopwatch_id: str
    created_at: datetime.datetime
    started_at: Optional[datetime.datetime] = None
    elapsed_ms: int = 0
    running: bool = False
    paused: bool = False
    last_updated_at: Optional[datetime.datetime] = None
    label: Optional[str] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "stopwatch_id": self.stopwatch_id,
            "label": self.label,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "elapsed_ms": self.elapsed_ms,
            "running": self.running,
            "paused": self.paused,
            "last_updated_at": self.last_updated_at.isoformat() if self.last_updated_at else None,
        }


@dataclass
class AlarmState:
    alarm_id: str
    title: str
    alarm_datetime: datetime.datetime
    timezone_name: str
    enabled: bool = True
    recurrence: Optional[str] = None
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "alarm_id": self.alarm_id,
            "title": self.title,
            "alarm_datetime": self.alarm_datetime.isoformat(),
            "timezone": self.timezone_name,
            "enabled": self.enabled,
            "recurrence": self.recurrence,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class SavedClockState:
    clock_id: str
    label: str
    timezone_name: str
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def snapshot(self) -> Dict[str, Any]:
        return {
            "clock_id": self.clock_id,
            "label": self.label,
            "timezone": self.timezone_name,
            "created_at": self.created_at.isoformat(),
        }


class TimeProviderError(Exception):
    """Raised when an external time provider fails."""


class TimeProviderBase:
    provider_name = "base"

    def fetch_current_time(self, *, timezone_name: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def validate_against_system_clock(
        self,
        *,
        system_now_utc: datetime.datetime,
        timezone_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        response = self.fetch_current_time(timezone_name=timezone_name)
        provider_ts = response.get("timestamp_utc")
        if not provider_ts:
            raise TimeProviderError("Provider did not return timestamp_utc")

        parsed = datetime.datetime.fromisoformat(provider_ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        else:
            parsed = parsed.astimezone(datetime.timezone.utc)

        offset_ms = int((parsed - system_now_utc).total_seconds() * 1000)

        return {
            "provider": self.provider_name,
            "checked": True,
            "available": True,
            "offset_ms": offset_ms,
            "provider_timestamp_utc": parsed.isoformat(),
            "provider_response": response,
        }


class SystemClockProvider(TimeProviderBase):
    provider_name = "system_clock"

    def fetch_current_time(self, *, timezone_name: Optional[str] = None) -> Dict[str, Any]:
        if timezone_name:
            tz = zoneinfo.ZoneInfo(timezone_name)
            local_now = datetime.datetime.now(tz)
        else:
            local_now = datetime.datetime.now().astimezone()

        utc_now = datetime.datetime.now(datetime.timezone.utc)

        return {
            "provider": self.provider_name,
            "provider_status": "ok",
            "timestamp": local_now.isoformat(),
            "timestamp_utc": utc_now.isoformat(),
            "timezone": local_now.tzname() or "unknown",
            "date": local_now.date().isoformat(),
            "time": local_now.time().replace(microsecond=0).isoformat(),
            "unix_timestamp": int(local_now.timestamp()),
            "utc_offset": TimeHandlerBase.format_utc_offset(local_now),
        }


class WorldTimeApiProvider(TimeProviderBase):
    provider_name = "worldtimeapi"
    base_url = "https://worldtimeapi.org/api/timezone"

    def fetch_current_time(self, *, timezone_name: Optional[str] = None) -> Dict[str, Any]:
        if not timezone_name:
            raise TimeProviderError("worldtimeapi requires timezone_name")

        url = f"{self.base_url}/{timezone_name}"
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise TimeProviderError(f"worldtimeapi request failed: {exc}") from exc

        local_dt_raw = payload.get("datetime")
        utc_dt_raw = payload.get("utc_datetime")
        if not local_dt_raw or not utc_dt_raw:
            raise TimeProviderError("worldtimeapi returned incomplete datetime fields")

        local_dt = datetime.datetime.fromisoformat(local_dt_raw)
        utc_dt = datetime.datetime.fromisoformat(utc_dt_raw)

        return {
            "provider": self.provider_name,
            "provider_status": "ok",
            "timestamp": local_dt.isoformat(),
            "timestamp_utc": utc_dt.isoformat(),
            "timezone": payload.get("timezone", timezone_name),
            "date": local_dt.date().isoformat(),
            "time": local_dt.time().replace(microsecond=0).isoformat(),
            "unix_timestamp": int(local_dt.timestamp()),
            "utc_offset": payload.get("utc_offset") or TimeHandlerBase.format_utc_offset(local_dt),
            "raw": payload,
        }


class TimeApiIoProvider(TimeProviderBase):
    provider_name = "timeapi_io"
    base_url = "https://timeapi.io/api/Time/current/zone"

    def fetch_current_time(self, *, timezone_name: Optional[str] = None) -> Dict[str, Any]:
        if not timezone_name:
            raise TimeProviderError("timeapi.io requires timezone_name")

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(self.base_url, params={"timeZone": timezone_name})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise TimeProviderError(f"timeapi.io request failed: {exc}") from exc

        date_value = payload.get("date")
        time_value = payload.get("time")
        tz_value = payload.get("timeZone", timezone_name)

        if not date_value or not time_value:
            raise TimeProviderError("timeapi.io returned incomplete date/time fields")

        combined = f"{date_value}T{time_value}"
        local_dt = datetime.datetime.fromisoformat(combined)

        try:
            tz = zoneinfo.ZoneInfo(tz_value)
            local_dt = local_dt.replace(tzinfo=tz)
        except zoneinfo.ZoneInfoNotFoundError as exc:
            raise TimeProviderError(f"Invalid timezone returned by timeapi.io: {tz_value}") from exc

        utc_dt = local_dt.astimezone(datetime.timezone.utc)

        return {
            "provider": self.provider_name,
            "provider_status": "ok",
            "timestamp": local_dt.isoformat(),
            "timestamp_utc": utc_dt.isoformat(),
            "timezone": tz_value,
            "date": local_dt.date().isoformat(),
            "time": local_dt.time().replace(microsecond=0).isoformat(),
            "unix_timestamp": int(local_dt.timestamp()),
            "utc_offset": TimeHandlerBase.format_utc_offset(local_dt),
            "raw": payload,
        }


class TimeStateStore:
    """
    Shared in-process store for stateful time features.

    Honest about being in-memory and non-durable.
    """

    _lock = threading.RLock()
    _stopwatches: Dict[str, StopwatchState] = {}
    _alarms: Dict[str, AlarmState] = {}
    _saved_clocks: Dict[str, SavedClockState] = {}

    @classmethod
    def lock(cls) -> threading.RLock:
        return cls._lock

    @classmethod
    def stopwatches(cls) -> Dict[str, StopwatchState]:
        return cls._stopwatches

    @classmethod
    def alarms(cls) -> Dict[str, AlarmState]:
        return cls._alarms

    @classmethod
    def saved_clocks(cls) -> Dict[str, SavedClockState]:
        return cls._saved_clocks


class TimeHandlerBase:
    """
    Shared base for all time_query handlers.
    """

    DEFAULT_PROVIDER = "system_clock"

    SUPPORTED_PROVIDERS = {
        "auto",
        "system_clock",
        "worldtimeapi",
        "timeapi_io",
    }

    LOCATION_TIMEZONE_ALIASES = {
        # Africa
        "zambia": "Africa/Lusaka",
        "lusaka": "Africa/Lusaka",
        "nigeria": "Africa/Lagos",
        "lagos": "Africa/Lagos",
        "ghana": "Africa/Accra",
        "accra": "Africa/Accra",
        "kenya": "Africa/Nairobi",
        "nairobi": "Africa/Nairobi",
        "ethiopia": "Africa/Addis_Ababa",
        "addis ababa": "Africa/Addis_Ababa",
        "uganda": "Africa/Kampala",
        "kampala": "Africa/Kampala",
        "tanzania": "Africa/Dar_es_Salaam",
        "dar es salaam": "Africa/Dar_es_Salaam",
        "south africa": "Africa/Johannesburg",
        "johannesburg": "Africa/Johannesburg",
        "cape town": "Africa/Johannesburg",
        "egypt": "Africa/Cairo",
        "cairo": "Africa/Cairo",
        "morocco": "Africa/Casablanca",
        "casablanca": "Africa/Casablanca",
        "algeria": "Africa/Algiers",
        "algiers": "Africa/Algiers",

        # Europe
        "uk": "Europe/London",
        "united kingdom": "Europe/London",
        "britain": "Europe/London",
        "england": "Europe/London",
        "london": "Europe/London",
        "france": "Europe/Paris",
        "paris": "Europe/Paris",
        "germany": "Europe/Berlin",
        "berlin": "Europe/Berlin",
        "italy": "Europe/Rome",
        "rome": "Europe/Rome",
        "spain": "Europe/Madrid",
        "madrid": "Europe/Madrid",
        "portugal": "Europe/Lisbon",
        "lisbon": "Europe/Lisbon",
        "netherlands": "Europe/Amsterdam",
        "amsterdam": "Europe/Amsterdam",
        "switzerland": "Europe/Zurich",
        "zurich": "Europe/Zurich",
        "sweden": "Europe/Stockholm",
        "stockholm": "Europe/Stockholm",
        "norway": "Europe/Oslo",
        "oslo": "Europe/Oslo",
        "denmark": "Europe/Copenhagen",
        "copenhagen": "Europe/Copenhagen",
        "greece": "Europe/Athens",
        "athens": "Europe/Athens",
        "poland": "Europe/Warsaw",
        "warsaw": "Europe/Warsaw",
        "ukraine": "Europe/Kyiv",
        "kyiv": "Europe/Kyiv",
        "ireland": "Europe/Dublin",
        "dublin": "Europe/Dublin",
        "belgium": "Europe/Brussels",
        "brussels": "Europe/Brussels",

        # North America
        "new york": "America/New_York",
        "ny": "America/New_York",
        "nyc": "America/New_York",
        "detroit": "America/Detroit",
        "michigan": "America/Detroit",
        "chicago": "America/Chicago",
        "houston": "America/Chicago",
        "dallas": "America/Chicago",
        "denver": "America/Denver",
        "phoenix": "America/Phoenix",
        "los angeles": "America/Los_Angeles",
        "la": "America/Los_Angeles",
        "san francisco": "America/Los_Angeles",
        "seattle": "America/Los_Angeles",
        "washington dc": "America/New_York",
        "dc": "America/New_York",
        "atlanta": "America/New_York",
        "miami": "America/New_York",
        "boston": "America/New_York",
        "toronto": "America/Toronto",
        "montreal": "America/Toronto",
        "vancouver": "America/Vancouver",
        "mexico city": "America/Mexico_City",
        "jamaica": "America/Jamaica",
        "kingston": "America/Jamaica",

        # South America
        "sao paulo": "America/Sao_Paulo",
        "rio de janeiro": "America/Sao_Paulo",
        "argentina": "America/Argentina/Buenos_Aires",
        "buenos aires": "America/Argentina/Buenos_Aires",
        "colombia": "America/Bogota",
        "bogota": "America/Bogota",
        "chile": "America/Santiago",
        "santiago": "America/Santiago",
        "peru": "America/Lima",
        "lima": "America/Lima",

        # Asia
        "japan": "Asia/Tokyo",
        "tokyo": "Asia/Tokyo",
        "china": "Asia/Shanghai",
        "shanghai": "Asia/Shanghai",
        "beijing": "Asia/Shanghai",
        "india": "Asia/Kolkata",
        "kolkata": "Asia/Kolkata",
        "delhi": "Asia/Kolkata",
        "mumbai": "Asia/Kolkata",
        "pakistan": "Asia/Karachi",
        "karachi": "Asia/Karachi",
        "bangladesh": "Asia/Dhaka",
        "dhaka": "Asia/Dhaka",
        "thailand": "Asia/Bangkok",
        "bangkok": "Asia/Bangkok",
        "singapore": "Asia/Singapore",
        "malaysia": "Asia/Kuala_Lumpur",
        "kuala lumpur": "Asia/Kuala_Lumpur",
        "philippines": "Asia/Manila",
        "manila": "Asia/Manila",
        "indonesia": "Asia/Jakarta",
        "jakarta": "Asia/Jakarta",
        "south korea": "Asia/Seoul",
        "seoul": "Asia/Seoul",
        "vietnam": "Asia/Ho_Chi_Minh",
        "ho chi minh": "Asia/Ho_Chi_Minh",
        "uae": "Asia/Dubai",
        "dubai": "Asia/Dubai",
        "saudi arabia": "Asia/Riyadh",
        "riyadh": "Asia/Riyadh",
        "israel": "Asia/Jerusalem",
        "jerusalem": "Asia/Jerusalem",
        "turkey": "Europe/Istanbul",
        "istanbul": "Europe/Istanbul",

        # Oceania
        "sydney": "Australia/Sydney",
        "melbourne": "Australia/Melbourne",
        "brisbane": "Australia/Brisbane",
        "perth": "Australia/Perth",
        "new zealand": "Pacific/Auckland",
        "auckland": "Pacific/Auckland",

        # Common timezone phrasing
        "eastern time": "America/New_York",
        "eastern": "America/New_York",
        "central time": "America/Chicago",
        "central": "America/Chicago",
        "mountain time": "America/Denver",
        "mountain": "America/Denver",
        "pacific time": "America/Los_Angeles",
        "pacific": "America/Los_Angeles",
        "gmt": "Europe/London",
        "bst": "Europe/London",
        "cet": "Europe/Paris",
        "eet": "Europe/Athens",
    }

    AMBIGUOUS_LOCATION_DEFAULTS = {
        "usa": "America/New_York",
        "us": "America/New_York",
        "united states": "America/New_York",
        "canada": "America/Toronto",
        "mexico": "America/Mexico_City",
        "brazil": "America/Sao_Paulo",
        "australia": "Australia/Sydney",
    }

    @classmethod
    def get_system_now(cls, timezone_name: Optional[str] = None) -> datetime.datetime:
        if timezone_name:
            tz = zoneinfo.ZoneInfo(timezone_name)
            return datetime.datetime.now(tz)
        return datetime.datetime.now().astimezone()

    @classmethod
    def get_system_now_utc(cls) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    @classmethod
    def normalize_string(cls, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None

    @classmethod
    def normalize_dict(cls, value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def normalize_string_list(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            single = cls.normalize_string(value)
            return [single] if single else []
        if isinstance(value, (list, tuple, set)):
            output: List[str] = []
            for item in value:
                normalized = cls.normalize_string(item)
                if normalized:
                    output.append(normalized)
            return output
        return []

    @classmethod
    def normalize_list_of_dicts(cls, value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @classmethod
    def parse_datetime(cls, raw_value: str) -> Optional[datetime.datetime]:
        try:
            return datetime.datetime.fromisoformat(raw_value)
        except ValueError:
            return None

    @classmethod
    def format_utc_offset(cls, value: datetime.datetime) -> str:
        offset = value.utcoffset()
        if offset is None:
            return "+00:00"

        total_seconds = int(offset.total_seconds())
        sign = "+" if total_seconds >= 0 else "-"
        total_seconds = abs(total_seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        return f"{sign}{hours:02d}:{minutes:02d}"

    @classmethod
    def provider_for_name(cls, provider_name: str) -> TimeProviderBase:
        normalized = provider_name.lower().strip()

        if normalized == "system_clock":
            return SystemClockProvider()
        if normalized == "worldtimeapi":
            return WorldTimeApiProvider()
        if normalized == "timeapi_io":
            return TimeApiIoProvider()

        raise TimeProviderError(f"Unsupported provider: {provider_name}")

    @classmethod
    def resolve_provider_name(cls, raw_provider: Any) -> str:
        normalized = cls.normalize_string(raw_provider)
        if not normalized:
            return cls.DEFAULT_PROVIDER

        normalized = normalized.lower()
        if normalized in cls.SUPPORTED_PROVIDERS:
            return normalized

        return cls.DEFAULT_PROVIDER

    @classmethod
    def provider_chain_for_request(cls, provider_name: str) -> List[str]:
        if provider_name == "auto":
            return ["worldtimeapi", "timeapi_io", "system_clock"]
        return [provider_name]

    @classmethod
    def display_label_for_timezone(cls, raw_value: str, timezone_name: str) -> str:
        raw = cls.normalize_string(raw_value)
        if raw:
            return raw.title()
        return timezone_name.split("/")[-1].replace("_", " ")

    @classmethod
    def extract_context_hints(cls, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "user_id": context.get("user_id"),
            "conversation_id": context.get("conversation_id"),
            "tenant_id": context.get("tenant_id"),
        }

    @classmethod
    def error_payload(
        cls,
        *,
        mode: str,
        error: str,
        context: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "error",
            "mode": mode,
            "error": error,
            "source": "system_clock",
            "provider": "system_clock",
            "provider_status": "error",
            "metadata": {
                "context_hints": cls.extract_context_hints(context),
                **(metadata or {}),
            },
        }

    @classmethod
    def build_base_time_payload(
        cls,
        *,
        mode: str,
        now_local: datetime.datetime,
        now_utc: Optional[datetime.datetime] = None,
        output_format: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        provider: str = "system_clock",
        provider_status: str = "ok",
        external_sync: Optional[Dict[str, Any]] = None,
        source_detail: Optional[Dict[str, Any]] = None,
        resolution_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        utc_now = now_utc or now_local.astimezone(datetime.timezone.utc)
        payload = {
            "status": "success",
            "mode": mode,
            "source": "system_clock",
            "provider": provider,
            "provider_status": provider_status,
            "external_sync": external_sync or {
                "checked": False,
                "available": False,
                "provider": None,
                "offset_ms": None,
            },
            "source_detail": source_detail or {
                "clock": "local_os_clock",
                "timezone_source": "system",
                "external_sync_checked": False,
                "storage": "stateless",
            },
            "timestamp": now_local.isoformat(),
            "timestamp_unix": int(now_local.timestamp()),
            "timestamp_utc": utc_now.isoformat(),
            "iso": now_local.isoformat(),
            "formatted": now_local.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now_local.strftime("%Y-%m-%d"),
            "time": now_local.strftime("%H:%M:%S"),
            "weekday": now_local.strftime("%A"),
            "month": now_local.strftime("%B"),
            "year": now_local.year,
            "timezone": now_local.tzname() or "unknown",
            "utc_offset": cls.format_utc_offset(now_local),
            "metadata": {
                "request_format": output_format,
                "context_hints": cls.extract_context_hints(context or {}),
            },
        }

        if resolution_meta:
            payload["resolution_meta"] = resolution_meta

        return payload

    @classmethod
    def resolve_timezone(cls, query: str) -> Dict[str, Any]:
        clean_query = cls.normalize_string(query)
        if not clean_query:
            return {"success": False, "error": "Empty timezone query"}

        lower = clean_query.lower()

        if lower in cls.LOCATION_TIMEZONE_ALIASES:
            tz_str = cls.LOCATION_TIMEZONE_ALIASES[lower]
            return {
                "success": True,
                "timezone": tz_str,
                "query": clean_query,
                "label": cls.display_label_for_timezone(clean_query, tz_str),
                "is_ambiguous_default": False,
                "resolution_type": "alias",
            }

        if lower in cls.AMBIGUOUS_LOCATION_DEFAULTS:
            tz_str = cls.AMBIGUOUS_LOCATION_DEFAULTS[lower]
            return {
                "success": True,
                "timezone": tz_str,
                "query": clean_query,
                "label": cls.display_label_for_timezone(clean_query, tz_str),
                "is_ambiguous_default": True,
                "resolution_type": "country_default",
            }

        try:
            zoneinfo.ZoneInfo(clean_query)
            return {
                "success": True,
                "timezone": clean_query,
                "query": clean_query,
                "label": cls.display_label_for_timezone(clean_query, clean_query),
                "is_ambiguous_default": False,
                "resolution_type": "direct_timezone",
            }
        except zoneinfo.ZoneInfoNotFoundError:
            pass

        direct_candidate = clean_query.replace(" ", "_")
        try:
            zoneinfo.ZoneInfo(direct_candidate)
            return {
                "success": True,
                "timezone": direct_candidate,
                "query": clean_query,
                "label": cls.display_label_for_timezone(clean_query, direct_candidate),
                "is_ambiguous_default": False,
                "resolution_type": "direct_timezone",
            }
        except zoneinfo.ZoneInfoNotFoundError:
            pass

        if "/" in clean_query:
            parts = [part.strip().replace(" ", "_") for part in clean_query.split("/")]
            title_query = "/".join(
                part.capitalize() if part.islower() else part for part in parts
            )
            try:
                zoneinfo.ZoneInfo(title_query)
                return {
                    "success": True,
                    "timezone": title_query,
                    "query": clean_query,
                    "label": cls.display_label_for_timezone(clean_query, title_query),
                    "is_ambiguous_default": False,
                    "resolution_type": "normalized_timezone",
                }
            except zoneinfo.ZoneInfoNotFoundError:
                pass

        return {
            "success": False,
            "error": f"Unknown timezone or location '{clean_query}'",
        }

    @classmethod
    def build_clock_entry(
        cls,
        *,
        label: str,
        timezone_name: str,
        clock_id: Optional[str] = None,
        resolution_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        local_now = cls.get_system_now(timezone_name)
        return {
            "clock_id": clock_id,
            "label": label,
            "timezone": timezone_name,
            "date": local_now.date().isoformat(),
            "time": local_now.time().replace(microsecond=0).isoformat(),
            "weekday": local_now.strftime("%A"),
            "utc_offset": cls.format_utc_offset(local_now),
            "timestamp": local_now.isoformat(),
            "resolution_meta": resolution_meta,
        }

    @classmethod
    def generate_alarm_id(cls) -> str:
        return str(uuid.uuid4())