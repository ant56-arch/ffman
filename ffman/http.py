"""Minimal read-only HTTP helpers. ffman only ever issues GET requests."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "ffman/0.1 (+read-only lineup advisor)"


class FetchError(RuntimeError):
    pass


def get_json(url: str, params: dict | None = None, cookies: dict | None = None, timeout: int = 30,
             headers: dict | None = None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if cookies:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise FetchError(f"GET {url} failed: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise FetchError(f"GET {url} failed: {exc}") from exc


# Projection sites serve their normal pages to browsers; some turn away unknown clients.
BROWSER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get_text(url: str, timeout: int = 20, headers: dict | None = None) -> str:
    """GET a web page as text (for the projection sites in consensus.py)."""
    headers = {"User-Agent": BROWSER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9", **(headers or {})}
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"GET {url} failed: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise FetchError(f"GET {url} failed: {exc}") from exc


def cache_dir() -> Path:
    path = Path(os.environ.get("FFMAN_CACHE_DIR", Path.home() / ".cache" / "ffman"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_json_cached(name: str, url: str, max_age_hours: float = 24, **kwargs):
    """Fetch JSON, reusing a copy on disk younger than max_age_hours."""
    path = cache_dir() / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return json.loads(path.read_text())
    data = get_json(url, **kwargs)
    path.write_text(json.dumps(data))
    return data
