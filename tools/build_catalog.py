#!/usr/bin/env python3
"""Genera ``social_scan/data/sites.json`` a partir de tres fuentes.

Fuentes (en orden de prioridad, la primera gana en caso de nombre duplicado):

1. ``vendor/curated.json`` — sitios esenciales revisados a mano.
2. ``vendor/sherlock_data.json`` — catálogo de Sherlock Project.
3. ``vendor/maigret_data.json`` — catálogo de Maigret.

Los ficheros crudos se pueden actualizar con:

    python3 tools/build_catalog.py --fetch

Uso normal:

    python3 tools/build_catalog.py

El resultado es un catálogo normalizado, sin dependencias externas, con un
formato sencillo y estable que el escáner consume directamente.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
OUTPUT = ROOT / "social_scan" / "data" / "sites.json"

SOURCES = {
    "sherlock": (
        VENDOR / "sherlock_data.json",
        "https://raw.githubusercontent.com/sherlock-project/sherlock/master/"
        "sherlock_project/resources/data.json",
    ),
    "maigret": (
        VENDOR / "maigret_data.json",
        "https://raw.githubusercontent.com/soxoj/maigret/main/"
        "maigret/resources/data.json",
    ),
}

SKIP_NAMES = {"$schema"}
SKIP_TAG_RE = re.compile(r"(?i)^(?:nsfw|adult|porn|xxx|cam|escort|dating)$")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "social-scan-catalog-builder/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_url(template: Any) -> str | None:
    if not isinstance(template, str) or not template.strip():
        return None
    template = template.strip()
    template = template.replace("{username}", "{}")
    if "{}" not in template or not template.startswith(("http://", "https://")):
        return None
    return template


def normalize_entry(name: str, raw: dict[str, Any], source: str) -> dict[str, Any] | None:
    if name in SKIP_NAMES or not isinstance(raw, dict):
        return None
    if raw.get("disabled") or raw.get("isNSFW"):
        return None

    url = normalize_url(raw.get("url"))
    probe = normalize_url(raw.get("urlProbe"))
    if not url and not probe:
        return None  # sitios que sólo existen como motor de búsqueda

    tags = [str(tag) for tag in raw.get("tags", []) if isinstance(tag, str)]
    if any(SKIP_TAG_RE.match(tag) for tag in tags):
        return None

    method = str(raw.get("request_method") or raw.get("requestMethod") or "GET").upper()
    if raw.get("requestHeadOnly"):
        method = "HEAD"
    if method not in {"GET", "HEAD"}:
        method = "GET"

    absent = str_list(raw.get("errorMsg")) + str_list(raw.get("absenceStrs"))
    present = str_list(raw.get("presenseStrs")) + str_list(raw.get("presenceStrs"))
    check_type = raw.get("checkType") or raw.get("errorType") or ""

    entry: dict[str, Any] = {
        "name": name.strip(),
        "source": source,
        "priority": {"curated": 0, "sherlock": 1, "maigret": 2}.get(source, 9),
        "method": method,
        "checkType": str(check_type),
    }
    if url:
        entry["url"] = url
    if probe:
        entry["probe"] = probe
    if absent:
        entry["absent"] = list(dict.fromkeys(absent))
    if present:
        entry["present"] = list(dict.fromkeys(present))
    raw_error_code = raw.get("errorCode")
    if isinstance(raw_error_code, (list, tuple, int)):
        codes = [int(raw_error_code)] if isinstance(raw_error_code, int) else [int(c) for c in raw_error_code]
        if codes:
            entry["errorCode"] = codes
    regex = raw.get("regexCheck")
    if isinstance(regex, str) and regex.strip():
        entry["regex"] = regex.strip()
    if tags:
        entry["tags"] = sorted(set(tags))[:12]
    if raw.get("ignore403") or raw.get("ignore_403"):
        entry["ignore403"] = True
    if raw.get("maxBody"):
        entry["maxBody"] = int(raw["maxBody"])
    if raw.get("username_claimed"):
        entry["example"] = str(raw["username_claimed"])
    unclaimed = raw.get("usernameUnclaimed") or raw.get("username_unclaimed")
    if unclaimed:
        entry["unclaimed"] = str(unclaimed)
    return entry


def load_source(path: Path, source: str) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if source == "maigret":
        data = data.get("sites", data)
    result: dict[str, dict[str, Any]] = {}
    for name, raw in data.items():
        entry = normalize_entry(name, raw, source)
        if entry:
            result[entry["name"].lower()] = entry
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="descarga los catálogos antes de generar")
    args = parser.parse_args()

    if args.fetch:
        for source, (path, url) in SOURCES.items():
            print(f"Descargando catálogo {source}…")
            path.write_bytes(fetch(url))
            print(f"  -> {path.name} ({path.stat().st_size:,} bytes)")

    combined: dict[str, dict[str, Any]] = {}
    paths = [(VENDOR / "curated.json", "curated")]
    paths += [(path, source) for source, (path, _) in SOURCES.items()]
    for path, source in paths:
        if not path.exists():
            raise SystemExit(f"Falta el fichero {path}. Usa --fetch o créalo manualmente.")
        entries = load_source(path, source)
        print(f"{source}: {len(entries):,} sitios utilizables")
        for key, entry in entries.items():
            combined.setdefault(key, entry)

    sites = sorted(combined.values(), key=lambda item: item["name"].lower())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {"version": 1, "generated_by": "tools/build_catalog.py", "sites": sites},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Catálogo unificado: {len(sites):,} sitios -> {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
