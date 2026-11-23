""""Comprobación HTTP y lógica de detección de perfiles."""

from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence
from urllib.parse import urlparse

from .catalog import Site

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 social-scan/1.0"
)

# Textos genéricos de "perfil inexistente". Se aplican a todas las respuestas
# con contenido para evitar falsos positivos en soft-404 (HTTP 200 + mensaje).
GLOBAL_ABSENT = (
    "page not found",
    "404 not found",
    "user not found",
    "profile not found",
    "account not found",
    "no such user",
    "this account doesn't exist",
    "this account doesn’t exist",
    "this user doesn't exist",
    "the page you requested was not found",
    "we couldn't find",
    "we could not find",
    "isn't available",
    "is not available",
    "no profile found",
    "nothing here",
)

# Páginas de verificación anti-bot: no son perfiles, pero tampoco
# demuestran que el usuario no exista. Se marcan como "bloqueados".
CHALLENGE_MARKERS = (
    "client challenge",
    "just a moment...",
    "checking your browser before accessing",
    "cf-browser-verification",
    "enable javascript and cookies to continue",
    "request unsuccessful. incapsula",
    "verify you are human",
    "security verification",
    "making sure you're not a bot",
    "making sure you&#39;re not a bot",
    "challenge_nonce",
    "gokuprops",
    "diamwall",
    "are you a robot",
    "browser check",
)

MAX_BODY = 200_000


@dataclass
class HTTPResponse:
    status: int
    url: str
    body: str = ""
    error: str | None = None


class HTTPClient:
    """Cliente HTTP pequeño y sin dependencias, apto para uso concurrente."""

    def __init__(self, timeout: float = 10.0, user_agent: str = USER_AGENT, verify_ssl: bool = True):
        self.timeout = timeout
        self.user_agent = user_agent
        self.context = ssl.create_default_context()
        if not verify_ssl:
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.context))

    def get(
        self,
        url: str,
        method: str = "GET",
        timeout: float | None = None,
        max_bytes: int = MAX_BODY,
    ) -> HTTPResponse:
        request = urllib.request.Request(
            url,
            method=method,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read(max_bytes)
                return HTTPResponse(
                    status=int(response.status),
                    url=response.geturl(),
                    body=raw.decode("utf-8", errors="ignore"),
                )
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(max_bytes)
                body = raw.decode("utf-8", errors="ignore")
            except Exception:  # pragma: no cover - cuerpo no disponible
                body = ""
            return HTTPResponse(status=int(exc.code), url=exc.geturl() or url, body=body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return HTTPResponse(status=0, url=url, error=str(reason)[:160])


@dataclass
class Finding:
    site: str
    url: str
    username: str
    kind: str = "perfil"  # perfil | buscador
    status: str = "found"  # found | blocked | error
    http_status: int | None = None
    evidence: str = ""
    tags: tuple[str, ...] = ()
    source: str = ""
    unclaimed: str = ""  # usuario inexistente conocido, usado para calibrar

    def as_dict(self) -> dict:
        return {
            "site": self.site,
            "url": self.url,
            "username": self.username,
            "type": self.kind,
            "status": self.status,
            "http_status": self.http_status,
            "evidence": self.evidence,
            "tags": list(self.tags),
            "source": self.source,
        }


@dataclass
class ScanStats:
    checked: int = 0
    found: int = 0
    not_found: int = 0
    blocked: int = 0
    errors: int = 0
    skipped: int = 0


@dataclass
class ScanResult:
    query: str
    findings: list[Finding] = field(default_factory=list)
    stats: ScanStats = field(default_factory=ScanStats)
    usernames: list[str] = field(default_factory=list)

    @property
    def profiles(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.status == "found"]

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "usernames_tried": self.usernames,
            "stats": {
                "checked": self.stats.checked,
                "found": self.stats.found,
                "not_found": self.stats.not_found,
                "blocked": self.stats.blocked,
                "errors": self.stats.errors,
                "skipped": self.stats.skipped,
            },
            "results": [finding.as_dict() for finding in self.findings],
        }


def _same_host(a: str, b: str) -> bool:
    def clean(url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host

    host_a, host_b = clean(a), clean(b)
    return bool(host_a and host_b and host_a == host_b)


def evaluate(site: Site, username: str, response: HTTPResponse, *, from_probe: bool = False) -> str:
    """Devuelve ``found``, ``not_found``, ``blocked`` o ``error``."""
    if response.error:
        return "error"
    status = response.status
    if status in site.error_codes or status in (401, 402, 404, 410, 451):
        return "not_found"
    if status in (202, 403, 429):
        return "blocked"
    if status == 0 or status >= 500:
        return "error"
    if status >= 400:
        return "not_found"

    body = response.body.lower()
    if any(marker in body for marker in CHALLENGE_MARKERS):
        return "blocked"

    absent = list(site.absent) + list(GLOBAL_ABSENT)
    if any(marker.lower() in body for marker in absent):
        return "not_found"

    if site.present and site.check_type == "message":
        if not any(marker.lower() in body for marker in site.present):
            return "not_found"

    if not from_probe and site.check_type == "response_url" and not _same_host(response.url, site.target_url(username) or ""):
        return "not_found"

    return "found"


def check_site(site: Site, username: str, client: HTTPClient, timeout: float | None = None) -> tuple[str, Finding | None]:
    """Comprueba un sitio. Devuelve ``(estado, hallazgo_si_aplica)``."""
    if site.regex:
        try:
            if not re.search(site.regex, username):
                return "skipped", None
        except re.error:
            pass

    profile_url = site.profile_url(username)
    if not profile_url:
        return "skipped", None

    state = "error"
    response: HTTPResponse | None = None
    from_probe = False

    if site.probe:
        probe_response = client.get(site.target_url(username) or "", site.method, timeout, site.max_body)
        probe_state = evaluate(site, username, probe_response, from_probe=True)
        if probe_state in ("found", "not_found"):
            state, response, from_probe = probe_state, probe_response, True
        else:
            response = probe_response  # bloqueo/error en la sonda: se reintenta con el perfil

    if not from_probe:
        response = client.get(profile_url, site.method, timeout, site.max_body)
        state = evaluate(site, username, response, from_probe=False)

    if state not in ("found", "blocked", "error"):
        return state, None

    evidence = ""
    if state == "found":
        evidence = "sonda HTTP" if from_probe else "respuesta HTTP " + str(response.status)
    elif state == "blocked":
        evidence = f"HTTP {response.status} (límite o acceso restringido)"
    else:
        evidence = f"sin respuesta: {response.error or response.status}"

    finding = Finding(
        site=site.name,
        url=profile_url,
        username=username,
        status=state,
        http_status=response.status or None,
        evidence=evidence,
        tags=site.tags,
        source=site.source,
        unclaimed=site.unclaimed,
    )
    return state, finding


def scan_sites(
    sites: Sequence[Site],
    usernames: Sequence[str],
    client: HTTPClient,
    workers: int = 24,
    timeout: float | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """Escanea todos los sitios para todos los nicks candidatos, en paralelo."""
    result = ScanResult(query=", ".join(usernames), usernames=list(usernames))
    tasks = [(site, username) for username in usernames for site in sites]
    total = len(tasks)
    done = 0

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(check_site, site, username, client, timeout): (site, username) for site, username in tasks}
        for future in as_completed(futures):
            done += 1
            if progress and (done % 50 == 0 or done == total):
                progress(done, total)
            try:
                state, finding = future.result()
            except Exception as exc:  # pragma: no cover - robustez ante sitios extraños
                result.stats.errors += 1
                continue

            result.stats.checked += 1
            if state == "found":
                result.stats.found += 1
            elif state == "not_found":
                result.stats.not_found += 1
            elif state == "blocked":
                result.stats.blocked += 1
            elif state == "error":
                result.stats.errors += 1
            else:
                result.stats.skipped += 1
                continue

            if finding:
                result.findings.append(finding)

    _discard_unreliable_sites(result, sites, client, timeout)
    result.findings.sort(key=lambda item: (item.status != "found", item.site.lower()))
    return result


def _discard_unreliable_sites(
    result: ScanResult,
    sites: Sequence[Site],
    client: HTTPClient,
    timeout: float | None,
) -> None:
    """Calibración: si el sitio también "encuentra" un usuario inexistente
    conocido, su detección no es fiable y el hallazgo se descarta."""
    site_by_name = {site.name: site for site in sites}
    candidates = [
        finding
        for finding in result.findings
        if finding.status == "found"
        and finding.unclaimed
        and finding.unclaimed.lower() != finding.username.lower()
        and finding.site in site_by_name
    ]
    if not candidates:
        return

    def verify(finding: Finding):
        site = site_by_name[finding.site]
        try:
            state, _ = check_site(site, finding.unclaimed, client, timeout)
            return finding, state
        except Exception:  # pragma: no cover
            return finding, "error"

    with ThreadPoolExecutor(max_workers=max(1, min(24, len(candidates)))) as pool:
        for future in as_completed([pool.submit(verify, finding) for finding in candidates]):
            finding, state = future.result()
            if state == "found":
                finding.status = "unreliable"
                finding.evidence = "descartado: el sitio responde igual para un usuario inexistente conocido"
                result.stats.found -= 1
                result.stats.skipped += 1
