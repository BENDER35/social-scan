"""Interfaz de línea de comandos de social-scan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .catalog import candidate_usernames, filter_sites, load_sites
from .engines import run_engines
from .networks import CHECKERS, scan_networks
from .report import render
from .scanner import HTTPClient, HTTPResponse, ScanResult, evaluate, scan_sites


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="social-scan",
        description=(
            "Busca perfiles públicos de redes sociales a partir de una frase, "
            "un nick o parte de una palabra, usando un catálogo de miles de sitios "
            "y varias APIs públicas de búsqueda."
        ),
        epilog=(
            "Ejemplos:\n"
            "  social-scan octocat\n"
            "  social-scan jack --networks x,instagram\n"
            "  social-scan 'Juan Pérez' --variants --format html -o juan.html\n"
            "  social-scan pepito --include 'GitHub|Instagram' --timeout 5\n"
            "  social-scan --list-sites | head\n"
            "  social-scan --self-test\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="*", help="frase, nick o fragmento a buscar")
    parser.add_argument("--version", action="version", version=f"social-scan {__version__}")
    parser.add_argument("--list-sites", action="store_true", help="lista los sitios del catálogo y sale")
    parser.add_argument("--self-test", action="store_true", help="comprueba el funcionamiento y sale")
    parser.add_argument("--sites", metavar="PATH", help="catálogo JSON alternativo")
    parser.add_argument("--timeout", type=float, default=10.0, metavar="SEG", help="timeout por petición (default: 10)")
    parser.add_argument("--workers", type=int, default=24, metavar="N", help="peticiones concurrentes (default: 24)")
    parser.add_argument("--variants", action="store_true", help="prueba varias formas del término (más peticiones)")
    parser.add_argument("--no-engines", action="store_true", help="desactiva las APIs de búsqueda por texto")
    parser.add_argument(
        "--networks",
        metavar="LISTA",
        help="modo dedicado: solo Instagram y/o X (p. ej. --networks instagram,x)",
    )
    parser.add_argument("--include", metavar="REGEX", help="sólo sitios cuyo nombre coincida (regex)")
    parser.add_argument("--exclude", metavar="REGEX", help="excluye sitios cuyo nombre coincida (regex)")
    parser.add_argument("--tags", metavar="LISTA", help="sólo sitios con alguna de estas etiquetas (comas)")
    parser.add_argument("--limit", type=int, metavar="N", help="comprueba sólo los primeros N sitios")
    parser.add_argument(
        "--format", choices=("table", "json", "csv", "html"), default="table", help="formato de salida (default: table)"
    )
    parser.add_argument("-o", "--output", metavar="FILE", help="escribe la salida en un fichero")
    parser.add_argument("--no-verify-ssl", action="store_true", help="no verifica certificados (no recomendado)")
    parser.add_argument("--quiet", action="store_true", help="no muestra el progreso")
    return parser


def _progress(done: int, total: int) -> None:
    print(f"\r[+] Comprobando: {done}/{total}", end="", file=sys.stderr, flush=True)


def self_test() -> int:
    """Prueba rápida: lógica interna + comprobación real contra GitHub."""
    checks: list[tuple[str, bool, str]] = []

    sites = load_sites()
    github_site = next((site for site in sites if site.name == "GitHub"), sites[0])
    checks.append(("catálogo cargado", len(sites) > 100, f"{len(sites)} sitios"))

    variants = candidate_usernames("Juan Pérez")
    checks.append(("variantes de frase", "juanperez" in variants or "juanpérez" in variants, str(variants)))

    fake = HTTPResponse(status=404, url="https://example.com/{}")
    checks.append(("detección 404", evaluate(github_site, "nadie", fake) == "not_found", ""))

    ok_body = HTTPResponse(status=200, url="https://github.com/octocat", body="<html>-octocat-</html>")
    missing_body = HTTPResponse(
        status=200, url="https://github.com/nobody", body="<html>Page not found</html>"
    )
    checks.append(("detección perfil", evaluate(github_site, "octocat", ok_body) == "found", ""))
    checks.append(("detección soft-404", evaluate(github_site, "nadie", missing_body) == "not_found", ""))

    client = HTTPClient(timeout=10)
    github = next((site for site in sites if site.name == "GitHub"), None)
    if github:
        live_ok = client.get("https://github.com/octocat")
        live_bad = client.get("https://github.com/this-user-does-not-exist-9f8e7d6c5b")
        tests = [
            ("GitHub en vivo: perfil conocido", evaluate(github, "octocat", live_ok) == "found", f"HTTP {live_ok.status}"),
            ("GitHub en vivo: perfil inexistente", evaluate(github, "x", live_bad) == "not_found", f"HTTP {live_bad.status}"),
        ]
        checks.extend(tests)
    else:
        checks.append(("sitio GitHub en catálogo", False, "no encontrado"))

    print("=== social-scan: autocomprobación ===")
    failed = 0
    for name, passed, detail in checks:
        print(f"[{'OK' if passed else 'FALLO'}] {name}" + (f" ({detail})" if detail else ""))
        failed += 0 if passed else 1
    print(f"\n{len(checks) - failed}/{len(checks)} comprobaciones correctas")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    try:
        sites = load_sites(args.sites)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.list_sites:
        for site in sites:
            print(site.name)
        return 0

    if not args.query:
        parser.print_help()
        return 2

    networks: list[str] = []
    if args.networks:
        networks = [name.strip().lower() for name in args.networks.split(",") if name.strip()]
        invalid = [name for name in networks if name not in CHECKERS]
        if invalid:
            print(
                f"Error: redes desconocidas {', '.join(invalid)}. Opciones: {', '.join(CHECKERS)}",
                file=sys.stderr,
            )
            return 2

    query = " ".join(args.query).strip()
    usernames = candidate_usernames(query, all_variants=args.variants)
    if not usernames:
        print("Error: la búsqueda está vacía.", file=sys.stderr)
        return 2

    client = HTTPClient(timeout=args.timeout, verify_ssl=not args.no_verify_ssl)
    result = ScanResult(query=query, usernames=usernames)
    progress = None if args.quiet else _progress

    if networks:
        if not args.quiet:
            print(
                f"[*] Modo dedicado: buscando {query!r} en {', '.join(networks)} "
                f"({len(usernames)} variante(s))…",
                file=sys.stderr,
            )
        scan_networks(networks, usernames, client, result, args.timeout)
    else:
        sites = filter_sites(sites, args.include, args.exclude, args.tags.split(",") if args.tags else ())
        if args.limit:
            sites = sites[: args.limit]
        if not sites:
            print("Error: el filtro no dejó ningún sitio.", file=sys.stderr)
            return 2

        if not args.quiet:
            print(
                f"[*] Buscando {query!r} en {len(sites):,} sitios "
                f"({len(usernames)} variante(s), {args.workers} hilos)…",
                file=sys.stderr,
            )

        scan_result = scan_sites(sites, usernames, client, args.workers, args.timeout, progress)
        result.findings.extend(scan_result.findings)
        result.stats.checked += scan_result.stats.checked
        result.stats.found += scan_result.stats.found
        result.stats.not_found += scan_result.stats.not_found
        result.stats.blocked += scan_result.stats.blocked
        result.stats.errors += scan_result.stats.errors
        result.stats.skipped += scan_result.stats.skipped

        if not args.no_engines:
            if not args.quiet:
                print("\n[*] Consultando motores de búsqueda públicos…", file=sys.stderr)
            run_engines(query, client, result, progress)
            if progress:
                print(file=sys.stderr)

    result.findings.sort(key=lambda item: (item.status != "found", item.site.lower()))
    output = render(result, args.format)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if not args.quiet:
            print(f"[+] Informe guardado en {args.output}", file=sys.stderr)
        if args.format == "table":
            print(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
