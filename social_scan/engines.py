"""Búsqueda por texto (frase, nick o fragmento) en APIs públicas.

A diferencia del escáner de perfiles, estos motores no necesitan que el
término sea exactamente un nick: permiten buscar nombres completos o trozos
de palabra dentro del buscador interno de cada plataforma.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Callable

from .scanner import HTTPClient, ScanResult


def _json_get(client: HTTPClient, url: str, timeout: float | None = None):
    response = client.get(url, "GET", timeout)
    if response.status != 200 or not response.body:
        return None, response
    try:
        return json.loads(response.body), response
    except json.JSONDecodeError:
        return None, response


def run_engines(
    query: str,
    client: HTTPClient,
    result: ScanResult,
    progress: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """Añade a ``result`` los hallazgos de los motores de búsqueda públicos."""
    term = urllib.parse.quote(query.strip())
    engines: list[tuple[str, str, Callable]] = [
        (
            "GitHub (búsqueda)",
            f"https://api.github.com/search/users?q={term}&per_page=10",
            lambda data: [
                (item.get("login", ""), item.get("html_url", ""), " usuario de GitHub")
                for item in data.get("items", [])
                if item.get("login")
            ],
        ),
        (
            "GitLab (búsqueda)",
            f"https://gitlab.com/api/v4/users?username={term}&per_page=10",
            lambda data: [
                (item.get("username", ""), item.get("web_url", ""), " usuario de GitLab")
                for item in data
                if isinstance(item, dict) and item.get("username")
            ],
        ),
        (
            "Codeberg (búsqueda)",
            f"https://codeberg.org/api/v1/users/search?q={term}&limit=10",
            lambda data: [
                (item.get("login", ""), item.get("html_url", ""), " usuario de Codeberg")
                for item in data
                if isinstance(item, dict) and item.get("login")
            ],
        ),
        (
            "Stack Overflow (búsqueda)",
            f"https://api.stackexchange.com/2.3/users?inname={term}&site=stackoverflow&pagesize=10",
            lambda data: [
                (item.get("display_name", ""), item.get("link", ""), " usuario de Stack Overflow")
                for item in data.get("items", [])
                if item.get("link")
            ],
        ),
        (
            "Hacker News (búsqueda)",
            f"https://hn.algolia.com/api/v1/search?query={term}&tags=author&hitsPerPage=10",
            lambda data: [
                (
                    hit.get("author", ""),
                    "https://news.ycombinator.com/user?id=" + urllib.parse.quote(str(hit.get("author", ""))),
                    " autor en Hacker News",
                )
                for hit in data.get("hits", [])
                if hit.get("author")
            ],
        ),
        (
            "Reddit (búsqueda)",
            f"https://www.reddit.com/search.json?q={term}&type=user&limit=10",
            lambda data: [
                (
                    item.get("data", {}).get("name", ""),
                    "https://www.reddit.com/user/" + str(item.get("data", {}).get("name", "")),
                    " usuario de Reddit",
                )
                for item in data.get("data", {}).get("children", [])
                if item.get("data", {}).get("name")
            ],
        ),
        (
            "Mastodon (búsqueda)",
            f"https://mastodon.social/api/v2/search?q={term}&type=accounts&limit=10",
            lambda data: [
                (item.get("acct", ""), item.get("url", ""), " cuenta de Mastodon")
                for item in data.get("accounts", [])
                if item.get("acct") and item.get("url")
            ],
        ),
    ]

    for index, (name, url, extract) in enumerate(engines, start=1):
        data, response = _json_get(client, url)
        if progress:
            progress(index, len(engines))
        if data is None:
            result.stats.errors += 1
            continue

        found_any = False
        for label, link, description in extract(data):
            if not link:
                continue
            from .scanner import Finding

            result.findings.append(
                Finding(
                    site=name,
                    url=link,
                    username=str(label),
                    kind="buscador",
                    http_status=response.status,
                    evidence="API pública" + description,
                    source="engine",
                )
            )
            result.stats.checked += 1
            found_any = True

        if found_any:
            result.stats.found += 1  # se cuenta el motor, no cada resultado

    return result
