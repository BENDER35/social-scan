# social-scan

Buscador de **perfiles públicos** en redes sociales y otras plataformas a partir de una frase, un nick o parte de una palabra.

Incluye un catálogo unificado de **~2.900 sitios** (entradas propias + [Sherlock Project](https://github.com/sherlock-project/sherlock) + [Maigret](https://github.com/soxoj/maigret)) y varias APIs públicas de búsqueda para términos que no son un nick exacto.

> Solo consulta páginas y APIs públicas. No elude contraseñas, no accede a cuentas privadas y no recoge datos personales ocultos. Úsalo de forma responsable y respetando la legalidad y los términos de cada servicio.

## Características

- Búsqueda masiva concurrente en ~2.900 plataformas.
- Motores de búsqueda por texto (GitHub, GitLab, Codeberg, Stack Overflow, Hacker News, Reddit, Mastodon) para frases y fragmentos.
- Normalización de frases: `Juan Pérez` → `juanperez`, `juan.perez`, `juan_perez`, `juan-perez`.
- Detección de *soft-404* (HTTP 200 con mensaje de "no encontrado"), páginas anti-bot y perfiles inexistentes conocidos (calibración automática).
- Salida en tabla, JSON, CSV o HTML.
- Sin dependencias externas: solo Python 3.9+ y la biblioteca estándar.
- Mirror automático GitHub → GitLab mediante URLs de push múltiples y GitHub Actions.

## Instalación

```bash
# Desde el código fuente
git clone https://github.com/BENDER35/social-scan.git
cd social-scan
python3 -m pip install -e .        # opcional, crea el comando social-scan
# o directamente:
./bin/social-scan octocat
```

Paquetes de la release:

```bash
# ZIP portable
unzip social-scan-1.0.0.zip
cd social-scan-1.0.0 && ./bin/social-scan --self-test

# DEB (Debian/Ubuntu)
sudo dpkg -i social-scan_1.0.0_all.deb
social-scan --self-test
```

## Uso

```bash
# Búsqueda básica
social-scan octocat

# Frase con todas las variantes del nick e informe HTML
social-scan "Juan Pérez" --variants --format html -o juan.html

# Solo algunos sitios, salida JSON
social-scan pepito --include 'GitHub|Instagram|TikTok' --format json

# Excluir sitios y limitar el número de comprobaciones
social-scan pepito --exclude 'forum|wiki' --limit 200

# Ver catálogo y comprobar que todo funciona
social-scan --list-sites
social-scan --self-test
```

## Modo dedicado: Instagram y X

```bash
social-scan jack --networks instagram,x
social-scan "juan perez" --networks instagram,x --variants --format html -o ig-x.html
```

Este modo sustituye el catálogo y los motores generales por dos comprobaciones específicas:

- **Instagram**: lee el `<title>` del perfil; una cuenta real declara `(@usuario)`.
- **X**: consulta el endpoint público `syndication.twitter.com` y comprueba `headerProps.screenName`; si existe, añade nombre y seguidores a la evidencia.

Las frases se convierten en variantes de nick (`juanperez`, `juan.perez`, …) con `--variants`. Ninguna de las dos plataformas ofrece una API pública de búsqueda por nombre sin autenticación, así que **no se puede buscar texto libre dentro de sus mensajes**; solo la existencia de perfiles. Si la plataforma limita la petición, el resultado aparece como `BLOCKED` en lugar de dar un falso negativo.

### Opciones principales

| Opción | Descripción |
| --- | --- |
| `--variants` | Prueba hasta 8 formas distintas del término (más peticiones). |
| `--no-engines` | Desactiva las APIs de búsqueda por texto. |
| `--include` / `--exclude` | Filtros regex sobre el nombre del sitio. |
| `--tags` | Solo sitios con alguna de esas etiquetas (separadas por comas). |
| `--limit N` | Comprueba solo los primeros N sitios. |
| `--timeout SEG` | Timeout por petición (por defecto 10). |
| `--workers N` | Peticiones concurrentes (por defecto 24). |
| `--format` | `table`, `json`, `csv` o `html`. |
| `-o, --output` | Guarda el informe en un fichero. |
| `--self-test` | Prueba la lógica interna y una comprobación real contra GitHub. |

El código de salida es `0` si la búsqueda terminó correctamente, `2` si hay un error de uso y `1` si falla `--self-test`.

## Precisión

La detección es heurística: combina código HTTP, textos de "perfil no encontrado", marcadores anti-bot y la comparación con un usuario inexistente conocido de cada sitio. Aun así, algunos sitios responden igual para cualquier usuario, por lo que **pueden aparecer falsos positivos**. Contrasta siempre los resultados abriendo el enlace.

## Desarrollo

```bash
python3 -m unittest discover -s tests -v   # pruebas unitarias
python3 -m social_scan --self-test          # prueba en vivo
make zip                                    # paquete ZIP
make deb                                    # paquete DEB
make release                                # ambos paquetes
```

Para regenerar el catálogo con las últimas versiones de Sherlock y Maigret:

```bash
python3 tools/build_catalog.py --fetch
```

## Mirror GitHub → GitLab

- Remoto `origin` (GitHub) tiene dos URLs de push: GitHub y GitLab. Un `git push origin main` actualiza ambos.
- `.github/workflows/mirror.yml` hace lo mismo en CI. Para activarlo, añade estos secretos/variables en GitHub:
  - `secrets.GITLAB_SSH_KEY`: clave SSH privada (sin passphrase) con permisos de escritura en GitLab.
  - `vars.GITLAB_MIRROR_URL` (opcional): URL SSH del proyecto GitLab; por defecto `git@gitlab.com:BENDER_5000/social-scan.git`.
  - La clave pública correspondiente debe añadirse como *deploy key* con permiso de escritura en GitLab.

## Estado del mirror

- GitHub: https://github.com/BENDER35/social-scan
- GitLab: https://gitlab.com/BENDER_5000/social-scan

Ambos repositorios se sincronizan automáticamente con `git push origin main` (dos URLs de push) y, si se configuran los secretos indicados, también desde GitHub Actions.

## Licencia

MIT. Los catálogos de Sherlock Project y Maigret se incluyen como datos y mantienen sus propias licencias; consulta sus repositorios originales.
