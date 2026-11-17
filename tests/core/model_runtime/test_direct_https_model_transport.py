"""Hermetic tests for the direct HTTPS transport within the existing model worker."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
from pathlib import Path

import pytest

from ai_karen_engine.core.model_runtime.management import direct_https_model_transport as transport


MODEL = "kyutai/pocket-tts"
REVISION = "db04f0e653473e5c7333c69686ac92b7460b0c1d"
PREFIX = "languages/english_18m_refl_2026-10"
PATTERNS = [
    f"{PREFIX}/model.safetensors",
    f"{PREFIX}/tokenizer.model",
    f"{PREFIX}/embeddings/*.safetensors",
]


class Response(io.BytesIO):
    def __init__(self, data: bytes, content_type: str = "application/octet-stream"):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}


def test_direct_https_requires_full_revision_and_explicit_patterns(tmp_path: Path) -> None:
    for model, revision, patterns in (
        (MODEL, "main", PATTERNS),
        ("../example", REVISION, PATTERNS),
        (MODEL, REVISION, None),
    ):
        with pytest.raises(transport.DirectHttpsDownloadError):
            transport.download_direct_https(
                model_id=model, revision=revision, directory=tmp_path,
                include_patterns=patterns, exclude_patterns=None, token=None,
            )


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "hello/../secret", "../x", "foo\\bar", "a//b", "", "x/./y"],
)
def test_direct_https_rejects_traversal(path: str) -> None:
    with pytest.raises(transport.DirectHttpsDownloadError):
        transport._safe_path(path)


def test_direct_https_denies_unsafe_initial_and_redirect_sources() -> None:
    assert transport._approved_url("https://huggingface.co/x/y", initial=True)
    assert not transport._approved_url("http://huggingface.co/x/y", initial=True)
    assert not transport._approved_url("https://evil.example/resolve/file", initial=False)
    assert not transport._approved_url("https://localhost/private", initial=False)
    assert not transport._approved_url("https://127.0.0.1/private", initial=False)
    assert not transport._approved_url("https://cdn-lfs.huggingface.co/x", initial=True)
    assert transport._approved_url("https://cdn-lfs.huggingface.co/x", initial=False)


def test_direct_https_redirect_drops_source_credentials() -> None:
    initial = urllib.request.Request(
        "https://huggingface.co/kyutai/pocket-tts/resolve/abc/file",
        headers={"Authorization": "Bearer secret", "Cookie": "confidential=1"},
    )
    redirected = transport._PrivateRedirectHandler().redirect_request(
        initial, None, 302, "Found", {},
        "https://cdn-lfs.huggingface.co/signed",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Cookie") is None
    assert "secret" not in str(redirected.headers)


def test_direct_https_discovers_pinned_files_and_checks_integrity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    assets = {
        f"{PREFIX}/model.safetensors": b"real model safetensors bytes",
        f"{PREFIX}/tokenizer.model": b"sentencepiece bytes",
        f"{PREFIX}/embeddings/alba.safetensors": b"real precomputed voice state",
    }
    seen: list[tuple[str, str | None]] = []

    def open_file(url: str, token: str | None, *, initial: bool):
        assert initial
        seen.append((url, token))
        if "/api/models/" in url:
            rows = [
                {
                    "path": name, "type": "file", "size": len(data),
                    "lfs": {"oid": hashlib.sha256(data).hexdigest()},
                }
                for name, data in assets.items()
                if name.startswith(url.split("/tree/", 1)[-1].split("/", 1)[-1].split("?")[0])
            ]
            return Response(json.dumps(rows).encode(), "application/json")
        for name, data in assets.items():
            if url.endswith("/" + name):
                return Response(data)
        raise AssertionError("Unexpected external request")

    monkeypatch.setattr(transport, "_open", open_file)
    transport.download_direct_https(
        model_id=MODEL, revision=REVISION, directory=tmp_path,
        include_patterns=PATTERNS, exclude_patterns=None, token="hf_test_secret",
    )
    assert {str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*") if path.is_file()} == set(assets)
    for path, data in assets.items():
        assert (tmp_path / path).read_bytes() == data
    assert len([url for url, _ in seen if "/resolve/" in url]) == 3
    assert all(value == "hf_test_secret" for _, value in seen)


def test_direct_https_refuses_checksum_mismatch_and_does_not_publish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = f"{PREFIX}/model.safetensors"
    payload = b"modified"
    monkeypatch.setattr(transport, "_discover", lambda *a, **kw: [
        {"path": path, "size": len(payload), "sha256": "0" * 64}
    ])
    monkeypatch.setattr(transport, "_open", lambda *a, **kw: Response(payload))
    with pytest.raises(transport.DirectHttpsDownloadError, match="checksum mismatch"):
        transport.download_direct_https(
            model_id=MODEL, revision=REVISION, directory=tmp_path,
            include_patterns=[path], exclude_patterns=None, token=None,
        )
    assert not (tmp_path / path).exists()
    assert not list(tmp_path.rglob("*.partial"))


def test_direct_https_requires_all_curated_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    path = f"{PREFIX}/tokenizer.model"
    def only_tokenizer(url: str, token: str | None, *, initial: bool):
        return Response(json.dumps([
            {"path": path, "type": "file", "size": 10}
        ]).encode(), "application/json")
    monkeypatch.setattr(transport, "_open", only_tokenizer)
    with pytest.raises(transport.DirectHttpsDownloadError, match="Required"):
        transport._discover(MODEL, REVISION, PATTERNS, [], None)
