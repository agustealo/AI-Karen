from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    ModelOrchestratorService,
)


class _FakeHfApi:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def list_models(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.calls.append(dict(kwargs))
        return [
            SimpleNamespace(
                id="test-owner/remote-model",
                last_modified=datetime(2026, 9, 24, tzinfo=timezone.utc),
                likes=17,
                downloads=321,
                library_name="transformers",
                tags=["text-generation"],
                description="Remote model card",
            )
        ]


@pytest.mark.asyncio
async def test_remote_listing_maps_library_name_to_public_storage_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ModelOrchestratorService(
        {
            "models_root": str(tmp_path / "models"),
            "registry_path": str(tmp_path / "models" / "registry.json"),
        }
    )
    api = _FakeHfApi()
    monkeypatch.setattr(service, "_get_hf_api", lambda: api)

    summaries = await service.list_models(
        owner="test-owner",
        limit=10,
        search="remote",
        sort="downloads",
        direction=-1,
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.model_id == "test-owner/remote-model"
    assert summary.storage_key == "transformers"
    assert summary.downloads == 321
    assert summary.likes == 17
    assert summary.tags == ["text-generation"]
    assert api.calls == [
        {
            "author": "test-owner",
            "search": "remote",
            "sort": "downloads",
            "direction": -1,
            "limit": 10,
        }
    ]
