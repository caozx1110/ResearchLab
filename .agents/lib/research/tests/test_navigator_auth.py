from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from kb_browser_lib import browser_url
from serve_kb_browser import BrowserHTTPServer, create_handler


class _Coordinator:
    pass


class _TerminalManager:
    pass


@contextmanager
def _running_server(project_root: Path, token: str = "test-token"):
    server = BrowserHTTPServer(
        ("127.0.0.1", 0),
        create_handler(project_root=project_root),
        project_root=project_root,
        coordinator=_Coordinator(),
        terminal_manager=_TerminalManager(),
        auth_token=token,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", token
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    request = Request(url, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=2) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_data_requests_require_token(tmp_path: Path, method: str) -> None:
    with _running_server(tmp_path) as (base, token):
        status, body, _ = _request(f"{base}/api/unsupported", method=method)
        assert status == 401
        assert json.loads(body) == {"ok": False, "error": "unauthorized"}
        assert _request(f"{base}/api/unsupported?token=wrong", method=method)[0] == 401

        status, _, _ = _request(f"{base}/api/unsupported?token={token}", method=method)
        assert status == 404


def test_static_get_requires_token_and_healthz_is_exempt(tmp_path: Path) -> None:
    static_file = tmp_path / "index.html"
    static_file.write_text("ready", encoding="utf-8")

    with _running_server(tmp_path) as (base, token):
        assert _request(f"{base}/index.html")[0] == 401
        status, body, headers = _request(f"{base}/index.html?token={token}")
        assert status == 200
        assert body == b"ready"
        assert _request(f"{base}/api/healthz")[0] == 200
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        assert _request(f"{base}/index.html", headers={"Cookie": cookie})[0] == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"X-KB-Token": "test-token"},
        {"Authorization": "Bearer test-token"},
    ],
)
def test_auth_headers_are_accepted(tmp_path: Path, headers: dict[str, str]) -> None:
    (tmp_path / "index.html").write_text("ready", encoding="utf-8")

    with _running_server(tmp_path) as (base, _):
        assert _request(f"{base}/index.html", headers=headers)[0] == 200


def test_browser_url_includes_token_without_changing_health_urls(tmp_path: Path) -> None:
    url = browser_url("127.0.0.1", 8765, tmp_path, token="one-time-token")

    assert url.endswith("/kb/user/kb/index.html?token=one-time-token")


def test_access_log_redacts_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "index.html").write_text("ready", encoding="utf-8")

    with _running_server(tmp_path, token="secret-value") as (base, token):
        assert _request(f"{base}/index.html?token={token}")[0] == 200

    assert "secret-value" not in capsys.readouterr().err
