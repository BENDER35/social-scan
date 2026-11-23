"""Generación de informes en varios formatos."""

from __future__ import annotations

import csv
import html
import io
import json
from datetime import datetime, timezone

from .scanner import ScanResult


def render(result: ScanResult, fmt: str = "table") -> str:
    renderers = {
        "table": render_table,
        "json": render_json,
        "csv": render_csv,
        "html": render_html,
    }
    try:
        return renderers[fmt](result)
    except KeyError as exc:
        raise ValueError(f"Formato desconocido: {fmt}") from exc


def render_json(result: ScanResult) -> str:
    payload = result.to_dict()
    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_csv(result: ScanResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["sitio", "usuario", "url", "tipo", "estado", "http", "evidencia", "fuente"])
    for finding in result.findings:
        writer.writerow(
            [
                finding.site,
                finding.username,
                finding.url,
                finding.kind,
                finding.status,
                finding.http_status or "",
                finding.evidence,
                finding.source,
            ]
        )
    return output.getvalue()


def render_table(result: ScanResult) -> str:
    rows = [
        (
            finding.site[:28],
            finding.username[:22],
            finding.url[:58],
            finding.kind,
            finding.status.upper(),
        )
        for finding in result.findings
    ]
    if not rows:
        return "No se encontraron perfiles ni resultados de búsqueda."

    headers = ("SITIO", "USUARIO", "URL", "TIPO", "ESTADO")
    widths = [max(len(str(row[i])) for row in [headers, *rows]) for i in range(len(headers))]
    line = "  ".join("-" * width for width in widths)
    output = ["  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)), line]
    for row in rows:
        output.append("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
    output.append(line)
    output.append(
        f"{result.stats.found} encontrados · {result.stats.blocked} bloqueados · "
        f"{result.stats.errors} errores · {result.stats.not_found} no encontrados"
    )
    return "\n".join(output)


def render_html(result: ScanResult) -> str:
    def esc(value) -> str:
        return html.escape(str(value))

    rows = []
    for finding in result.findings:
        badge = "ok" if finding.status == "found" else "warn"
        rows.append(
            "<tr>"
            f"<td>{esc(finding.site)}</td>"
            f"<td>{esc(finding.username)}</td>"
            f'<td><a href="{esc(finding.url)}" target="_blank" rel="noopener">{esc(finding.url)}</a></td>'
            f"<td>{esc(finding.kind)}</td>"
            f'<td class="{badge}">{esc(finding.status)}</td>'
            f"<td>{esc(finding.evidence)}</td>"
            "</tr>"
        )

    stats = result.stats
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>social-scan — {esc(result.query)}</title>
<style>
 body {{ font: 14px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 1100px; color: #1c2330; }}
 h1 {{ font-size: 1.5rem; }}
 .stats {{ color: #5b6472; margin-bottom: 1.2rem; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border-bottom: 1px solid #e1e5eb; padding: .5rem .6rem; text-align: left; vertical-align: top; }}
 th {{ background: #f5f7fa; }}
 a {{ color: #1557b0; word-break: break-all; }}
 .ok {{ color: #0a7a35; font-weight: 600; }}
 .warn {{ color: #a15c00; font-weight: 600; }}
</style>
</head>
<body>
<h1>social-scan · {esc(result.query)}</h1>
<p class="stats">Nicks probados: {esc(", ".join(result.usernames))} ·
{stats.found} encontrados · {stats.blocked} bloqueados · {stats.errors} errores ·
{stats.not_found} no encontrados · {stats.checked} comprobaciones</p>
<table>
<thead><tr><th>Sitio</th><th>Usuario</th><th>URL</th><th>Tipo</th><th>Estado</th><th>Evidencia</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="6">Sin resultados</td></tr>'}</tbody>
</table>
<p>Generado por social-scan.</p>
</body>
</html>
"""
