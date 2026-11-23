"""Comprobaciones dedicadas para Instagram y X (Twitter).

Estas dos plataformas sirven páginas SPA que responden HTTP 200 tanto para
perfiles existentes como para inexistentes, así que el detector genérico del
catálogo no es suficiente. Aquí se usan señales específicas:

* Instagram: el ``<title>`` de un perfil real contiene ``(@usuario)``.
* X: el endpoint público de syndication devuelve ``headerProps.screenName``
  y los datos del usuario cuando la cuenta existe.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import Callable

from .scanner import CHALLENGE_MARKERS, Finding, HTTPClient, ScanResult

NETWORK_NAMES = ("instagram", "x")

_X_PROFILE_URL = "https://x.com/{}"
_IG_PROFILE_URL = "https://www.instagram.com/{}/"
_X_SYNDICATION = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{}"


def _has_challenge(body: str) -> bool:
    lowered = body.lower()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


def _is_blocked_status(status: int) -> bool:
    return status in (202, 403, 429) or status >= 500


def check_instagram(username: str, client: HTTPClient, timeout: float | None = None) -> tuple[str, Finding | None]:
    """Comprueba un perfil de Instagram usando el título de la página."""
    url = _IG_PROFILE_URL.format(urllib.parse.quote(username, safe=""))
    response = client.get(url, "GET", timeout, 400_000)

    if response.error or response.status == 0:
        state, evidence = "error", f"sin respuesta: {response.error}"
    elif _is_blocked_status(response.status) or _has_challenge(response.body):
        state, evidence = "blocked", "Instagram limitó la petición (HTTP %s)" % response.status
    else:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", response.body, re.IGNORECASE | re.DOTALL)
        title = html.unescape(title_match.group(1)) if title_match else ""
        clean_title = " ".join(title.split()).strip().lower()
        declared = re.search(r"\(@([^)]+)\)", title, re.IGNORECASE)
        if declared and declared.group(1).strip().lower() == username.lower():
            state, evidence = "found", "título de perfil: " + " ".join(title.split())[:120]
        elif any(marker in clean_title for marker in ("page not found", "not found", "isn't available", "is not available")):
            state, evidence = "not_found", "Instagram indica que la página no existe"
        elif clean_title in ("instagram", ""):
            # Instagram sirve un caparazón genérico cuando limita o no
            # renderiza el perfil: no es prueba de que el usuario no exista.
            state, evidence = "blocked", "Instagram devolvió la página genérica (sin datos de perfil)"
        else:
            state, evidence = "not_found", "la página no declara este usuario"

    if state not in ("found", "blocked", "error"):
        return state, None
    return state, Finding(
        site="Instagram",
        url=url,
        username=username,
        kind="perfil",
        status=state,
        http_status=response.status or None,
        evidence=evidence,
        tags=("social", "photo"),
        source="dedicado",
    )


def check_x(username: str, client: HTTPClient, timeout: float | None = None) -> tuple[str, Finding | None]:
    """Comprueba una cuenta de X mediante el timeline público de syndication."""
    profile_url = _X_PROFILE_URL.format(urllib.parse.quote(username, safe=""))
    api_url = _X_SYNDICATION.format(urllib.parse.quote(username, safe=""))
    response = client.get(api_url, "GET", timeout, 2_000_000)

    if response.error or response.status == 0:
        state, evidence = "error", f"sin respuesta: {response.error}"
    elif _is_blocked_status(response.status) or _has_challenge(response.body):
        state, evidence = "blocked", "X limitó la petición (HTTP %s)" % response.status
    else:
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            response.body,
            re.DOTALL,
        )
        if not match:
            state, evidence = "blocked", "respuesta de X sin datos interpretables"
        else:
            try:
                page = json.loads(match.group(1))["props"]["pageProps"]
            except (json.JSONDecodeError, KeyError, TypeError):
                state, evidence = "blocked", "respuesta de X sin datos interpretables"
            else:
                header = page.get("headerProps") or {}
                screen_name = str(header.get("screenName") or "")
                if screen_name.lower() != username.lower():
                    state, evidence = "not_found", "la cuenta no existe o no es pública"
                else:
                    detail = _x_user_details(page, username)
                    state, evidence = "found", "datos públicos de la cuenta vía syndication" + detail

    if state not in ("found", "blocked", "error"):
        return state, None
    return state, Finding(
        site="X (Twitter)",
        url=profile_url,
        username=username,
        kind="perfil",
        status=state,
        http_status=response.status or None,
        evidence=evidence,
        tags=("social", "microblog"),
        source="dedicado",
    )


def _x_user_details(page: dict, username: str) -> str:
    """Extrae nombre y seguidores del primer tweet del timeline, si hay."""
    for entry in page.get("timeline", {}).get("entries", []):
        user = (entry.get("content") or {}).get("tweet", {}).get("user") or {}
        if str(user.get("screen_name", "")).lower() != username.lower():
            continue
        name = str(user.get("name") or "").strip()
        followers = user.get("followers_count")
        parts = []
        if name:
            parts.append(name)
        if isinstance(followers, int):
            parts.append(f"{followers:,} seguidores".replace(",", "."))
        return ": " + " · ".join(parts) if parts else ""
    return ""


CHECKERS: dict[str, Callable[[str, HTTPClient, float | None], tuple[str, Finding | None]]] = {
    "instagram": check_instagram,
    "x": check_x,
}


def scan_networks(
    networks: list[str],
    usernames: list[str],
    client: HTTPClient,
    result: ScanResult,
    timeout: float | None = None,
) -> ScanResult:
    """Añade al resultado las comprobaciones dedicadas de cada red."""
    for network in networks:
        checker = CHECKERS[network]
        for username in usernames:
            state, finding = checker(username, client, timeout)
            result.stats.checked += 1
            if state == "found":
                result.stats.found += 1
            elif state == "blocked":
                result.stats.blocked += 1
            elif state == "error":
                result.stats.errors += 1
            elif state == "not_found":
                result.stats.not_found += 1
            else:
                result.stats.skipped += 1
            if finding:
                result.findings.append(finding)
    return result
