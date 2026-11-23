"""Pruebas del modo dedicado para Instagram y X (sin red)."""

from __future__ import annotations

import json
import unittest

from social_scan.networks import check_instagram, check_x, scan_networks
from social_scan.scanner import HTTPResponse, ScanResult


class FakeClient:
    def __init__(self, responses: dict[str, HTTPResponse]):
        self.responses = responses

    def get(self, url, method="GET", timeout=None, max_bytes=200_000):
        return self.responses.get(url, HTTPResponse(status=404, url=url))


def x_page(screen_name: str | None, followers: int = 42) -> str:
    page = {
        "props": {
            "pageProps": {
                "headerProps": {"screenName": screen_name} if screen_name else None,
                "timeline": {
                    "entries": (
                        [
                            {
                                "content": {
                                    "tweet": {
                                        "user": {
                                            "screen_name": screen_name,
                                            "name": "Usuario de prueba",
                                            "followers_count": followers,
                                        }
                                    }
                                }
                            }
                        ]
                        if screen_name
                        else []
                    )
                },
            }
        }
    }
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(page)
        + "</script></html>"
    )


class InstagramTests(unittest.TestCase):
    url = "https://www.instagram.com/jack/"

    def test_found_by_title(self):
        body = '<html><title>Instagram (&#064;jack) • Instagram photos and videos</title></html>'
        client = FakeClient({self.url: HTTPResponse(status=200, url=self.url, body=body)})
        state, finding = check_instagram("jack", client)
        self.assertEqual(state, "found")
        self.assertEqual(finding.url, self.url)
        self.assertIn("título", finding.evidence)

    def test_not_found(self):
        body = "<html><title>Sorry, this page isn't available | Instagram</title></html>"
        client = FakeClient({self.url: HTTPResponse(status=200, url=self.url, body=body)})
        state, finding = check_instagram("jack", client)
        self.assertEqual(state, "not_found")
        self.assertIsNone(finding)

    def test_generic_shell_is_blocked(self):
        body = "<html><title>Instagram</title></html>"
        client = FakeClient({self.url: HTTPResponse(status=200, url=self.url, body=body)})
        state, finding = check_instagram("jack", client)
        self.assertEqual(state, "blocked")
        self.assertEqual(finding.status, "blocked")

    def test_rate_limited(self):
        client = FakeClient({self.url: HTTPResponse(status=429, url=self.url, body="")})
        state, finding = check_instagram("jack", client)
        self.assertEqual(state, "blocked")
        self.assertEqual(finding.status, "blocked")


class XTests(unittest.TestCase):
    url = "https://syndication.twitter.com/srv/timeline-profile/screen-name/jack"

    def test_found_and_details(self):
        client = FakeClient({self.url: HTTPResponse(status=200, url=self.url, body=x_page("jack"))})
        state, finding = check_x("jack", client)
        self.assertEqual(state, "found")
        self.assertEqual(finding.url, "https://x.com/jack")
        self.assertIn("Usuario de prueba", finding.evidence)
        self.assertIn("42 seguidores", finding.evidence)

    def test_not_found(self):
        client = FakeClient({self.url: HTTPResponse(status=200, url=self.url, body=x_page(None))})
        state, finding = check_x("jack", client)
        self.assertEqual(state, "not_found")
        self.assertIsNone(finding)

    def test_unparsable_response_is_blocked(self):
        client = FakeClient({self.url: HTTPResponse(status=200, url=self.url, body="<html></html>")})
        state, finding = check_x("jack", client)
        self.assertEqual(state, "blocked")
        self.assertEqual(finding.status, "blocked")


class DedicatedModeTests(unittest.TestCase):
    def test_scan_networks_adds_findings(self):
        ig_url = "https://www.instagram.com/jack/"
        x_url = "https://syndication.twitter.com/srv/timeline-profile/screen-name/jack"
        client = FakeClient(
            {
                ig_url: HTTPResponse(
                    status=200,
                    url=ig_url,
                    body="<title>Instagram (@jack) • Instagram photos and videos</title>",
                ),
                x_url: HTTPResponse(status=200, url=x_url, body=x_page("jack")),
            }
        )
        result = scan_networks(["instagram", "x"], ["jack"], client, ScanResult(query="jack", usernames=["jack"]))
        self.assertEqual(result.stats.checked, 2)
        self.assertEqual(result.stats.found, 2)
        self.assertEqual({item.site for item in result.profiles}, {"Instagram", "X (Twitter)"})


if __name__ == "__main__":
    unittest.main()
