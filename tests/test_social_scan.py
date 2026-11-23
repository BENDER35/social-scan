"""Pruebas unitarias (sin red) del catálogo, la detección y los informes."""

from __future__ import annotations

import csv
import io
import json
import unittest

from social_scan.catalog import candidate_usernames, filter_sites, load_sites
from social_scan.report import render
from social_scan.scanner import (
    Finding,
    HTTPResponse,
    ScanResult,
    check_site,
    evaluate,
    scan_sites,
)


class FakeClient:
    def __init__(self, responses: dict[str, HTTPResponse]):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url, method="GET", timeout=None, max_bytes=200_000):
        self.calls.append(url)
        return self.responses.get(url, HTTPResponse(status=404, url=url))


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sites = load_sites()

    def test_catalog_has_many_sites(self):
        self.assertGreater(len(self.sites), 1000)

    def test_catalog_is_deduplicated(self):
        urls = [site.url or site.template for site in self.sites]
        self.assertEqual(len(urls), len(set(urls)))

    def test_core_sites_present(self):
        names = {site.name for site in self.sites}
        self.assertTrue({"GitHub", "Instagram", "Bluesky", "Pinterest"} <= names)

    def test_filter_by_name(self):
        found = filter_sites(self.sites, include="^GitHub")
        self.assertTrue(any(site.name == "GitHub" for site in found))
        self.assertFalse(any(site.name == "Instagram" for site in found))

    def test_variants_from_phrase(self):
        variants = candidate_usernames("Juan Pérez")
        self.assertEqual(variants[0], "juanperez")
        self.assertEqual(len(variants), 1)
        all_variants = candidate_usernames("Juan Pérez", all_variants=True)
        self.assertIn("juan.perez", all_variants)
        self.assertIn("juan_perez", all_variants)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.github = next(site for site in load_sites() if site.name == "GitHub")

    def test_http_404_is_not_found(self):
        response = HTTPResponse(status=404, url="https://github.com/nadie")
        self.assertEqual(evaluate(self.github, "nadie", response), "not_found")

    def test_http_200_with_profile_is_found(self):
        response = HTTPResponse(status=200, url="https://github.com/octocat", body="<html>octocat</html>")
        self.assertEqual(evaluate(self.github, "octocat", response), "found")

    def test_soft_404_is_not_found(self):
        response = HTTPResponse(status=200, url="https://github.com/nadie", body="<h1>Page not found</h1>")
        self.assertEqual(evaluate(self.github, "nadie", response), "not_found")

    def test_anti_bot_page_is_blocked(self):
        response = HTTPResponse(status=200, url="https://github.com/octocat", body="<title>Just a moment...</title>")
        self.assertEqual(evaluate(self.github, "octocat", response), "blocked")

    def test_rate_limit_is_blocked(self):
        response = HTTPResponse(status=429, url="https://github.com/octocat")
        self.assertEqual(evaluate(self.github, "octocat", response), "blocked")

    def test_regex_restriction(self):
        numeric = next(site for site in load_sites() if site.name == "Stack Overflow")
        client = FakeClient({})
        state, finding = check_site(numeric, "octocat", client)
        self.assertEqual(state, "skipped")
        self.assertIsNone(finding)
        self.assertEqual(client.calls, [])

    def test_probe_is_used_and_profile_url_reported(self):
        site = next(s for s in load_sites() if s.name == "Bluesky")
        probe_url = site.target_url("octocat")
        client = FakeClient({probe_url: HTTPResponse(status=200, url=probe_url, body='{"did":"did:plc:1"}')})
        state, finding = check_site(site, "octocat", client)
        self.assertEqual(state, "found")
        self.assertEqual(finding.url, "https://bsky.app/profile/octocat.bsky.social")
        self.assertIn("sonda", finding.evidence)

    def test_scan_sites_aggregates(self):
        sites = [s for s in load_sites() if s.name in ("GitHub", "GitLab")]
        client = FakeClient(
            {
                "https://github.com/octocat": HTTPResponse(status=200, url="https://github.com/octocat", body="octocat"),
                "https://gitlab.com/octocat": HTTPResponse(status=404, url="https://gitlab.com/octocat"),
            }
        )
        result = scan_sites(sites, ["octocat"], client, workers=2)
        self.assertEqual(result.stats.found, 1)
        self.assertEqual(result.stats.not_found, 1)
        self.assertEqual(len(result.profiles), 1)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.result = ScanResult(query="octocat", usernames=["octocat"])
        self.result.stats.found = 1
        self.result.findings.append(
            Finding(site="GitHub", url="https://github.com/octocat", username="octocat")
        )

    def test_json_report(self):
        data = json.loads(render(self.result, "json"))
        self.assertEqual(data["query"], "octocat")
        self.assertEqual(data["results"][0]["site"], "GitHub")
        self.assertIn("generated_at", data)

    def test_csv_report(self):
        rows = list(csv.reader(io.StringIO(render(self.result, "csv"))))
        self.assertEqual(rows[0][0], "sitio")
        self.assertEqual(rows[1][2], "https://github.com/octocat")

    def test_html_report(self):
        output = render(self.result, "html")
        self.assertIn("<!doctype html>", output)
        self.assertIn("https://github.com/octocat", output)

    def test_table_report(self):
        self.assertIn("GitHub", render(self.result, "table"))


if __name__ == "__main__":
    unittest.main()
