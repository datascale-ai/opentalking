import os
from datetime import timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
GITHUB_REPO_OWNER = "datascale-ai"
GITHUB_REPO_NAME = "opentalking"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
GITHUB_STARGAZERS_API_URL = f"{GITHUB_API_URL}/stargazers"
GITHUB_FORKS_API_URL = f"{GITHUB_API_URL}/forks"
GITHUB_TOKEN_ENV = "HOMEPAGE_GITHUB_TOKEN"
ANALYTICS_DB_PATH = Path(os.getenv("HOMEPAGE_ANALYTICS_DB", ROOT / ".analytics" / "homepage_analytics.sqlite3"))
ANALYTICS_HASH_SALT = os.getenv("HOMEPAGE_ANALYTICS_SALT", "opentalking-homepage")
MAX_FIELD_LENGTH = 500
BEIJING_TZ = timezone(timedelta(hours=8))
TREND_DAYS = 14
