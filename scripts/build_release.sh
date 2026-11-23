#!/usr/bin/env bash
# Construye los artefactos de release: ZIP portable y paquete DEB.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c 'from social_scan import __version__; print(__version__)')"
DIST="$ROOT/dist"
MODE="${1:-all}"

rm -rf "$DIST"
mkdir -p "$DIST"

build_zip() {
    local stage="$DIST/stage-zip/social-scan-$VERSION"
    mkdir -p "$stage"
    cp -r social_scan bin README.md LICENSE "$stage/"
    find "$stage" -type d -name '__pycache__' -prune -exec rm -rf {} +
    (cd "$DIST/stage-zip" && zip -q -r "../social-scan-$VERSION.zip" "social-scan-$VERSION")
    echo "ZIP: $DIST/social-scan-$VERSION.zip"
}

build_deb() {
    local stage="$DIST/stage-deb"
    mkdir -p "$stage/DEBIAN" "$stage/usr/bin" "$stage/usr/lib/social-scan"
    cp -r social_scan "$stage/usr/lib/social-scan/"
    find "$stage/usr/lib/social-scan" -type d -name '__pycache__' -prune -exec rm -rf {} +
    cp bin/social-scan "$stage/usr/bin/social-scan"

    cat > "$stage/DEBIAN/control" <<EOF
Package: social-scan
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9)
Maintainer: BENDER35 <grandrodri3@gmail.com>
Homepage: https://github.com/BENDER35/social-scan
Description: Buscador de perfiles publicos en redes sociales
 Busca perfiles publicos a partir de una frase, un nick o parte de una
 palabra en unos 2900 sitios y varias APIs publicas. Sin dependencias
 externas y con informes en tabla, JSON, CSV y HTML.
EOF

    dpkg-deb --build --root-owner-group "$stage" "$DIST/social-scan_${VERSION}_all.deb" >/dev/null
    echo "DEB: $DIST/social-scan_${VERSION}_all.deb"
}

case "$MODE" in
    all) build_zip; build_deb ;;
    zip) build_zip ;;
    deb) build_deb ;;
    *) echo "Uso: $0 [all|zip|deb]" >&2; exit 2 ;;
esac

ls -lh "$DIST"/*.zip "$DIST"/*.deb 2>/dev/null || true
