import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from server.config import (
    BEIJING_TZ,
    GITHUB_API_URL,
    GITHUB_FORKS_API_URL,
    GITHUB_STARGAZERS_API_URL,
    GITHUB_TOKEN_ENV,
    TREND_DAYS,
)


def parse_event_datetime(value):
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed



def get_github_token():
    return os.getenv(GITHUB_TOKEN_ENV, "").strip()


def fetch_github_json(url, accept="application/vnd.github+json"):
    headers = {
        "Accept": accept,
        "User-Agent": "opentalking-homepage",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    github_token = get_github_token()

    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    request = Request(url, headers=headers)

    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def get_last_github_page(link_header):
    if not link_header:
        return 1

    for item in link_header.split(","):
        if 'rel="last"' not in item:
            continue

        start = item.find("<")
        end = item.find(">")

        if start == -1 or end == -1:
            continue

        query = parse_qs(urlparse(item[start + 1:end]).query)

        try:
            return int(query.get("page", ["1"])[0])
        except ValueError:
            return 1

    return 1


def collect_recent_github_datetimes(
    url,
    time_key,
    since_datetime,
    accept="application/vnd.github+json",
    newest_first=False,
    require_token=False,
):
    recent_datetimes = []
    first_url = f"{url}{'&' if '?' in url else '?'}per_page=100"

    if require_token and not get_github_token():
        return recent_datetimes, False

    try:
        first_page, headers = fetch_github_json(first_url, accept)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return recent_datetimes, False

    pages_to_scan = []

    if newest_first:
        pages_to_scan = [first_page]
    else:
        last_page = get_last_github_page(headers.get("Link"))
        page_numbers = range(last_page, max(last_page - 5, 0), -1)

        for page_number in page_numbers:
            if page_number == 1:
                pages_to_scan.append(first_page)
                continue

            try:
                page, _ = fetch_github_json(f"{first_url}&page={page_number}", accept)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
                continue

            pages_to_scan.append(page)

    should_stop = False

    for page in pages_to_scan:
        if not isinstance(page, list):
            continue

        iterable_page = page if newest_first else reversed(page)

        for item in iterable_page:
            event_time = parse_event_datetime(item.get(time_key, ""))

            if event_time is None:
                continue

            if event_time < since_datetime:
                should_stop = True
                continue

            recent_datetimes.append(event_time)

        if should_stop:
            break

    return recent_datetimes, True


def build_cumulative_github_trend(beijing_now, current_total, event_datetimes):
    today = beijing_now.date()
    days = [today - timedelta(days=offset) for offset in reversed(range(TREND_DAYS))]
    points = []

    for day in days:
        next_day_start = datetime(day.year, day.month, day.day, tzinfo=BEIJING_TZ) + timedelta(days=1)
        next_day_start_utc = next_day_start.astimezone(timezone.utc)
        later_events = sum(1 for event_time in event_datetimes if event_time >= next_day_start_utc)

        points.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%m/%d"),
                "count": max(current_total - later_events, 0),
            }
        )

    return points


def build_github_trends(beijing_now):
    since_day = beijing_now.date() - timedelta(days=TREND_DAYS - 1)
    since_datetime = datetime(since_day.year, since_day.month, since_day.day, tzinfo=BEIJING_TZ).astimezone(timezone.utc)

    try:
        repo_data, _ = fetch_github_json(GITHUB_API_URL)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        repo_data = {}

    star_total = int(repo_data.get("stargazers_count") or 0)
    fork_total = int(repo_data.get("forks_count") or 0)
    star_datetimes, stars_available = collect_recent_github_datetimes(
        GITHUB_STARGAZERS_API_URL,
        "starred_at",
        since_datetime,
        accept="application/vnd.github.star+json",
        require_token=True,
    )
    fork_datetimes, forks_available = collect_recent_github_datetimes(
        f"{GITHUB_FORKS_API_URL}?sort=newest",
        "created_at",
        since_datetime,
        newest_first=True,
    )

    return {
        "stars": build_cumulative_github_trend(beijing_now, star_total, star_datetimes),
        "forks": build_cumulative_github_trend(beijing_now, fork_total, fork_datetimes),
        "star_total": star_total,
        "fork_total": fork_total,
        "stars_available": stars_available,
        "forks_available": forks_available,
        "stars_message": "" if stars_available else "TOKEN unavailable",
        "forks_message": "" if forks_available else "GitHub data unavailable",
    }

