"""Carga y filtrado del catálogo de sitios, y generación de variantes."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_CATALOG = Path(__file__).resolve().parent / "data" / "sites.json"

# Separadores que se probarán al transformar una frase en un posible nick.
_SEPARATORS = ("", ".", "_", "-")


@dataclass(frozen=True)
class Site:
    """Un sitio del catálogo, ya normalizado."""

    name: str
    url: str | None
    probe: str | None = None
    method: str = "GET"
    check_type: str = "status_code"
    absent: tuple[str, ...] = ()
    present: tuple[str, ...] = ()
    error_codes: tuple[int, ...] = (404, 410)
    regex: str | None = None
    tags: tuple[str, ...] = ()
    source: str = ""
    example: str = ""
    unclaimed: str = ""
    priority: int = 9
    max_body: int = 200_000

    @classmethod
    def from_dict(cls, raw: dict) -> "Site":
        return cls(
            name=str(raw.get("name", "")),
            url=raw.get("url"),
            probe=raw.get("probe"),
            method=str(raw.get("method", "GET")).upper(),
            check_type=str(raw.get("checkType", "")),
            absent=tuple(str(x) for x in raw.get("absent", ())),
            present=tuple(str(x) for x in raw.get("present", ())),
            error_codes=tuple(int(x) for x in raw.get("errorCode", (404, 410))),
            regex=raw.get("regex"),
            tags=tuple(str(x) for x in raw.get("tags", ())),
            source=str(raw.get("source", "")),
            example=str(raw.get("example", "")),
            unclaimed=str(raw.get("unclaimed", "")),
            priority=int(raw.get("priority", 9)),
            max_body=int(raw.get("maxBody", 200_000)),
        )

    @property
    def template(self) -> str | None:
        return self.probe or self.url

    def target_url(self, username: str) -> str | None:
        template = self.template
        if not template:
            return None
        from urllib.parse import quote

        return template.replace("{}", quote(username, safe=""))

    def profile_url(self, username: str) -> str | None:
        if not self.url:
            return None
        from urllib.parse import quote

        return self.url.replace("{}", quote(username, safe=""))


def load_sites(path: str | Path | None = None) -> list[Site]:
    """Carga el catálogo. ``path`` permite usar un catálogo propio."""
    catalog_path = Path(path) if path else DEFAULT_CATALOG
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"No se encontró el catálogo en {catalog_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Catálogo JSON inválido en {catalog_path}: {exc}") from exc

    from urllib.parse import urlparse

    raw_sites = data.get("sites", data) if isinstance(data, dict) else data
    sites = [Site.from_dict(raw) for raw in raw_sites if isinstance(raw, dict)]
    sites = [site for site in sites if site.name and site.template]
    # Los sitios curados y de Sherlock tienen prioridad sobre los de Maigret.
    sites.sort(key=lambda site: (site.priority, site.name.lower()))

    # Varios sitios del catálogo apuntan exactamente a la misma URL: se
    # comprueba una sola vez para no duplicar peticiones ni resultados.
    deduplicated: list[Site] = []
    seen: set[tuple[str, str]] = set()
    for site in sites:
        target = site.url or site.template or ""
        parsed = urlparse(target.replace("{}", "__social_scan_placeholder__"))
        key = ((parsed.hostname or "").lower(), parsed.path.rstrip("/"))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(site)
    return deduplicated


def filter_sites(
    sites: Iterable[Site],
    include: str | None = None,
    exclude: str | None = None,
    tags: Iterable[str] = (),
) -> list[Site]:
    """Filtra por nombre (regex, insensible a mayúsculas) y por etiquetas."""
    include_re = re.compile(include, re.IGNORECASE) if include else None
    exclude_re = re.compile(exclude, re.IGNORECASE) if exclude else None
    wanted_tags = {tag.lower() for tag in tags}
    result = []
    for site in sites:
        if include_re and not include_re.search(site.name):
            continue
        if exclude_re and exclude_re.search(site.name):
            continue
        if wanted_tags and not wanted_tags.intersection({tag.lower() for tag in site.tags}):
            continue
        result.append(site)
    return result


def candidate_usernames(query: str, all_variants: bool = False) -> list[str]:
    """Convierte una frase, nick o fragmento en candidatos de nick.

    Ejemplo: ``"Juan Pérez"`` -> ``juanperez``, ``juan.perez``,
    ``juan_perez`` y ``juan-perez``. Con ``all_variants=False`` (por defecto)
    se devuelve únicamente el candidato más probable para no multiplicar
    las peticiones por sitio.
    """
    original = " ".join(query.split())
    if not original:
        return []

    pieces = [piece for piece in re.split(r"[\s._\-]+", original) if piece]
    cleaned = "".join(pieces)
    if not pieces:
        return []

    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip("._-")
        if value and value not in seen and len(value) <= 40:
            seen.add(value)
            variants.append(value)

    def ascii_fold(value: str) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(char)
        )

    # El candidato principal siempre va en minúsculas y sin separadores:
    # es el formato más habitual para nicks derivados de una frase.
    add(ascii_fold(cleaned).lower())
    add(cleaned.lower())
    for separator in _SEPARATORS:
        add(ascii_fold(separator.join(pieces)).lower())
        add(separator.join(pieces).lower())
    if not all_variants:
        return variants[:1]

    add(cleaned)  # se conserva la grafía original
    add(pieces[0].lower())
    if len(pieces) > 1:
        add("".join(piece[0] for piece in pieces).lower())
    return variants[:8]
