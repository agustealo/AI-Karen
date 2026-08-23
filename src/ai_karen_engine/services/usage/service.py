"""Service helpers for usage counters and rate limits."""

from datetime import datetime, timedelta
from typing import Optional

from ai_karen_engine.database.client import get_db_session_context
from ai_karen_engine.database.models import UsageCounter


class UsageService:
    """Utility methods for usage tracking."""

    @staticmethod
    def increment(metric: str, tenant_id: Optional[str] = None, user_id: Optional[str] = None, amount: int = 1) -> None:
        """Increment a usage counter for the current window."""
        try:
            now = datetime.utcnow()
            window_start = now.replace(minute=0, second=0, microsecond=0)
            window_end = window_start + timedelta(hours=1)
            with get_db_session_context() as session:
                record = (
                    session.query(UsageCounter)
                    .filter_by(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        metric=metric,
                        window_start=window_start,
                        window_end=window_end,
                    )
                    .first()
                )
                if record:
                    current_value = int(record.value or 0)
                    setattr(record, "value", current_value + amount)
                else:
                    session.add(
                        UsageCounter(
                            tenant_id=tenant_id,
                            user_id=user_id,
                            metric=metric,
                            value=amount,
                            window_start=window_start,
                            window_end=window_end,
                        )
                    )
                session.commit()
        except Exception:
            pass
