import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "homepage_server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("homepage_server_under_test", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GitHubTrendTests(unittest.TestCase):
    def test_fetch_github_json_uses_homepage_github_token(self):
        server = load_server_module()
        captured = {}

        class FakeResponse:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.headers.get("Authorization")
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.dict(os.environ, {"HOMEPAGE_GITHUB_TOKEN": "token-for-test"}, clear=False):
            with patch.object(server, "urlopen", fake_urlopen):
                server.fetch_github_json("https://api.github.com/repos/datascale-ai/opentalking")

        self.assertEqual(captured["authorization"], "Bearer token-for-test")
        self.assertEqual(captured["timeout"], 10)

    def test_star_trend_marks_token_unavailable_when_stargazers_rejects_token(self):
        server = load_server_module()
        beijing_now = server.datetime(2026, 7, 7, 12, 0, tzinfo=server.BEIJING_TZ)

        def fake_fetch(url, accept="application/vnd.github+json"):
            if url == server.GITHUB_API_URL:
                return {"stargazers_count": 2029, "forks_count": 400}, {}
            if "stargazers" in url:
                raise HTTPError(url, 403, "Resource not accessible by personal access token", {}, None)
            if "forks" in url:
                return [], {}
            raise AssertionError(url)

        with patch.object(server, "fetch_github_json", fake_fetch):
            trends = server.build_github_trends(beijing_now)

        self.assertFalse(trends["stars_available"])
        self.assertIn("TOKEN", trends["stars_message"])
        self.assertEqual(trends["star_total"], 2029)
        self.assertTrue(trends["forks_available"])


if __name__ == "__main__":
    unittest.main()
