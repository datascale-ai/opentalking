import json
import os
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
GITHUB_REPO_OWNER = "datascale-ai"
GITHUB_REPO_NAME = "opentalking"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
GITHUB_STARGAZERS_API_URL = f"{GITHUB_API_URL}/stargazers"
GITHUB_FORKS_API_URL = f"{GITHUB_API_URL}/forks"
ANALYTICS_DB_PATH = Path(os.getenv("HOMEPAGE_ANALYTICS_DB", ROOT / ".analytics" / "homepage_analytics.sqlite3"))
ANALYTICS_HASH_SALT = os.getenv("HOMEPAGE_ANALYTICS_SALT", "opentalking-homepage")
MAX_FIELD_LENGTH = 500
BEIJING_TZ = timezone(timedelta(hours=8))
TREND_DAYS = 14

app = FastAPI(docs_url=None, redoc_url=None)

if not DIST_DIR.exists():
    raise RuntimeError(f"Homepage dist not found: {DIST_DIR}")

assets_dir = DIST_DIR / "assets"
images_dir = DIST_DIR / "images"

if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

if images_dir.exists():
    app.mount("/images", StaticFiles(directory=images_dir), name="images")


def clamp_text(value, max_length=MAX_FIELD_LENGTH):
    if value is None:
        return ""

    return str(value).strip()[:max_length]


def init_analytics_db():
    ANALYTICS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(ANALYTICS_DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_name TEXT NOT NULL,
                path TEXT NOT NULL,
                language TEXT,
                page TEXT,
                case_slug TEXT,
                video_id TEXT,
                referrer TEXT,
                referrer_host TEXT,
                user_agent TEXT,
                ip_hash TEXT,
                screen TEXT
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON analytics_events(created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_analytics_event_name ON analytics_events(event_name)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_analytics_path ON analytics_events(path)")


def get_client_ip(request: FastAPIRequest):
    forwarded_for = request.headers.get("x-forwarded-for", "")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.client.host if request.client else ""


def hash_ip(ip_address):
    if not ip_address:
        return ""

    return hashlib.sha256(f"{ANALYTICS_HASH_SALT}:{ip_address}".encode("utf-8")).hexdigest()[:16]


def normalize_referrer_host(referrer):
    if not referrer:
        return "Direct / Unknown"

    parsed = urlparse(referrer)

    return parsed.netloc or "Direct / Unknown"


def query_rows(query, params=()):
    init_analytics_db()

    with sqlite3.connect(ANALYTICS_DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def query_value(query, params=()):
    rows = query_rows(query, params)

    if not rows:
        return 0

    return next(iter(rows[0].values()))


@app.get("/health")
def health():
    return PlainTextResponse("ok")


@app.post("/analytics/event")
async def record_analytics_event(request: FastAPIRequest):
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}

    event_name = clamp_text(payload.get("eventName"), 80)

    if event_name not in {"page_view", "video_play"}:
        return JSONResponse({"ok": False}, status_code=202)

    if "referrer" in payload:
        referrer = clamp_text(payload.get("referrer"))
    else:
        referrer = clamp_text(request.headers.get("referer"))
    row = (
        datetime.now(timezone.utc).isoformat(),
        event_name,
        clamp_text(payload.get("path") or "/"),
        clamp_text(payload.get("language"), 12),
        clamp_text(payload.get("page"), 80),
        clamp_text(payload.get("caseSlug"), 120),
        clamp_text(payload.get("videoId"), 160),
        referrer,
        normalize_referrer_host(referrer),
        clamp_text(request.headers.get("user-agent"), 500),
        hash_ip(get_client_ip(request)),
        clamp_text(payload.get("screen"), 32),
    )

    init_analytics_db()

    with sqlite3.connect(ANALYTICS_DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO analytics_events (
                created_at,
                event_name,
                path,
                language,
                page,
                case_slug,
                video_id,
                referrer,
                referrer_host,
                user_agent,
                ip_hash,
                screen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


TRAFFIC_COPY = {
    "zh": {
        "html_lang": "zh-CN",
        "title": "OpenTalking 流量统计",
        "description": "轻量站内统计。IP 仅以 hash 形式保存，不记录明文地址。",
        "updated": "更新时间",
        "timezone": "北京时间",
        "language_switch": "EN",
        "language_href": "/en/traffic",
        "empty": "暂无数据。",
        "cards": {
            "today": "今日浏览",
            "seven_day": "14 天浏览",
            "total": "累计浏览",
            "video": "视频播放",
            "visitors": "累计访客",
        },
        "deltas": {
            "today": "较昨日",
            "seven_day": "较前 14 天",
            "total": "今日新增浏览",
            "video": "今日新增播放",
            "visitors": "今日新增访客",
            "increase": "增加",
            "decrease": "减少",
            "flat": "持平",
        },
        "delta_help": {
            "today": "今日浏览量减去昨日浏览量，用来观察当天页面浏览变化。",
            "seven_day": "最近 14 天浏览量减去前一个 14 天窗口浏览量。",
            "total": "累计浏览的今日增量，今天新增的页面浏览次数。",
            "video": "视频播放总量的今日增量，今天新增的视频播放次数。",
            "visitors": "累计访客的今日增量，今天首次出现的新访客数。",
        },
        "sections": {
            "top_pages": "热门页面",
            "top_referrers": "来源排行",
            "top_videos": "视频播放排行",
            "daily_views": "每日浏览",
        },
        "charts": {
            "views_title": "过去 14 天浏览量",
            "unique_title": "过去 14 天独立访客",
            "stars_title": "最近 14 天 Star 趋势",
            "forks_title": "最近 14 天 Fork 趋势",
            "views_total": "Views",
            "unique_total": "Unique Visitors",
            "stars_total": "Stars",
            "forks_total": "Forks",
            "view_table": "View as table",
            "download_csv": "Download CSV",
            "show_labels": "Show data labels",
            "date": "Date",
            "value": "Value",
        },
        "video_names": {
            "hero-companion-character": "首页主视觉：陪伴类角色",
            "case-ecommerce-livestream": "案例：电商带货",
            "case-ecommerce-livestream-front": "案例：电商直播正视",
            "case-ecommerce-livestream-angle": "案例：电商带货斜视",
            "case-huangshan-tour-guide": "案例：黄山文旅导览",
            "case-medical-guide-assistant-zh": "案例：医疗导诊助手中文",
            "case-medical-guide-assistant-en": "案例：医疗导诊助手英文",
            "case-news-anchor": "案例：新闻主播",
            "case-companion-character": "案例：陪伴类角色",
            "case-anime-talk-show": "案例：动漫脱口秀",
            "case-creative-performance": "案例：创意演唱 / 模仿秀",
            "case-mobile-recording": "案例：实时手机录制",
        },
        "columns": {
            "path": "路径",
            "views": "浏览",
            "uniques": "独立访客",
            "source": "来源",
            "video": "视频",
            "plays": "播放",
            "today_plays": "今日",
            "last_7_days": "近 7 天",
            "previous_7_days": "上个 7 天",
            "weekly_delta": "周变化",
            "day": "日期",
        },
        "direct_unknown_help": {
            "label": "Direct / Unknown 来源说明",
            "title": "Direct / Unknown的路由来源？",
            "items": [
                "用户直接输入网址、从书签或桌面快捷方式打开。",
                "微信、QQ、飞书、邮件、文档等应用可能不传递来源。",
                "浏览器隐私策略、插件或部分网站会隐藏 Referer。",
                "GitHub About 等外链可能使用 noreferrer，来源被清空。",
            ],
        },
    },
    "en": {
        "html_lang": "en",
        "title": "OpenTalking Traffic",
        "description": "Lightweight first-party analytics. IP addresses are stored as hashes only.",
        "updated": "Updated",
        "timezone": "Beijing Time",
        "language_switch": "中",
        "language_href": "/traffic",
        "empty": "No data yet.",
        "cards": {
            "today": "Today views",
            "seven_day": "14-day views",
            "total": "Total views",
            "video": "Video plays",
            "visitors": "Total visitors",
        },
        "deltas": {
            "today": "vs yesterday",
            "seven_day": "vs previous 14 days",
            "total": "new views today",
            "video": "new plays today",
            "visitors": "new visitors today",
            "increase": "up",
            "decrease": "down",
            "flat": "no change",
        },
        "delta_help": {
            "today": "Today’s page views minus yesterday’s page views.",
            "seven_day": "Page views from the latest 14-day window minus the previous 14-day window.",
            "total": "The daily increase in total views, which equals today’s new page views.",
            "video": "The daily increase in total video plays.",
            "visitors": "The daily increase in total visitors, counted as newly seen visitors today.",
        },
        "sections": {
            "top_pages": "Top Pages",
            "top_referrers": "Top Referrers",
            "top_videos": "Top Videos",
            "daily_views": "Daily Views",
        },
        "charts": {
            "views_title": "Total views in last 14 days",
            "unique_title": "Unique visitors in last 14 days",
            "stars_title": "Stars in last 14 days",
            "forks_title": "Forks in last 14 days",
            "views_total": "Views",
            "unique_total": "Unique Visitors",
            "stars_total": "Stars",
            "forks_total": "Forks",
            "view_table": "View as table",
            "download_csv": "Download CSV",
            "show_labels": "Show data labels",
            "date": "Date",
            "value": "Value",
        },
        "video_names": {
            "hero-companion-character": "Hero: Companion Character",
            "case-ecommerce-livestream": "Case: E-commerce Livestream",
            "case-ecommerce-livestream-front": "Case: E-commerce Front View",
            "case-ecommerce-livestream-angle": "Case: E-commerce Angled View",
            "case-huangshan-tour-guide": "Case: Huangshan Tourism Guide",
            "case-medical-guide-assistant-zh": "Case: Medical Guide Chinese",
            "case-medical-guide-assistant-en": "Case: Medical Guide English",
            "case-news-anchor": "Case: News Anchor",
            "case-companion-character": "Case: Companion Character",
            "case-anime-talk-show": "Case: Anime Talk Show",
            "case-creative-performance": "Case: Creative Performance",
            "case-mobile-recording": "Case: Mobile Recording",
        },
        "columns": {
            "path": "Path",
            "views": "Views",
            "uniques": "Unique Visitors",
            "source": "Source",
            "video": "Video",
            "plays": "Plays",
            "today_plays": "Today",
            "last_7_days": "Last 7 days",
            "previous_7_days": "Previous 7 days",
            "weekly_delta": "Weekly change",
            "day": "Day",
        },
        "direct_unknown_help": {
            "label": "Direct / Unknown source details",
            "title": "Why Direct / Unknown?",
            "items": [
                "Visitors typed the URL directly, used a bookmark, or opened a desktop shortcut.",
                "Apps such as WeChat, QQ, Feishu, email clients, or documents may strip the referrer.",
                "Browser privacy settings, extensions, or some websites may hide the Referer header.",
                "External links such as GitHub About can use noreferrer, so the source is not available.",
            ],
        },
    },
}


def format_number(value):
    return f"{value:,}"


def parse_event_datetime(value):
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed


def build_seven_day_traffic(beijing_now):
    today = beijing_now.date()
    days = [today - timedelta(days=offset) for offset in reversed(range(TREND_DAYS))]
    day_keys = {day.isoformat(): {"label": day.strftime("%m/%d"), "views": 0, "visitors": set()} for day in days}
    start_at = datetime(days[0].year, days[0].month, days[0].day, tzinfo=BEIJING_TZ).astimezone(timezone.utc).isoformat()
    events = query_rows(
        """
        SELECT created_at, ip_hash
        FROM analytics_events
        WHERE event_name = 'page_view' AND created_at >= ?
        """,
        (start_at,),
    )

    for event in events:
        created_at = parse_event_datetime(event.get("created_at", ""))

        if created_at is None:
            continue

        day_key = created_at.astimezone(BEIJING_TZ).date().isoformat()

        if day_key not in day_keys:
            continue

        day_keys[day_key]["views"] += 1

        ip_hash = event.get("ip_hash") or ""

        if ip_hash:
            day_keys[day_key]["visitors"].add(ip_hash)

    return [
        {
            "date": day,
            "label": value["label"],
            "views": value["views"],
            "uniques": len(value["visitors"]),
        }
        for day, value in day_keys.items()
    ]


def build_daily_views(beijing_now):
    return [
        {"day": point["date"], "count": point["views"]}
        for point in reversed(build_seven_day_traffic(beijing_now))
        if point["views"] > 0
    ]


def fetch_github_json(url, accept="application/vnd.github+json"):
    request = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "opentalking-homepage",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

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


def collect_recent_github_datetimes(url, time_key, since_datetime, accept="application/vnd.github+json", newest_first=False):
    recent_datetimes = []
    first_url = f"{url}{'&' if '?' in url else '?'}per_page=100"

    try:
        first_page, headers = fetch_github_json(first_url, accept)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return recent_datetimes

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

    return recent_datetimes


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
    star_datetimes = collect_recent_github_datetimes(
        GITHUB_STARGAZERS_API_URL,
        "starred_at",
        since_datetime,
        accept="application/vnd.github.star+json",
    )
    fork_datetimes = collect_recent_github_datetimes(
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
    }


def nice_chart_ceiling(value):
    if value <= 4:
        return 4

    if value <= 10:
        return 10

    magnitude = 10 ** (len(str(value)) - 1)

    return ((value + magnitude - 1) // magnitude) * magnitude


def beijing_day_start(day):
    return datetime(day.year, day.month, day.day, tzinfo=BEIJING_TZ).astimezone(timezone.utc).isoformat()


@app.get("/traffic")
def traffic_dashboard_zh():
    return render_traffic_dashboard("zh")


@app.get("/en/traffic")
def traffic_dashboard_en():
    return render_traffic_dashboard("en")


def render_traffic_dashboard(language):
    copy = TRAFFIC_COPY[language]
    now = datetime.now(timezone.utc)
    beijing_now = now.astimezone(BEIJING_TZ)
    today = beijing_now.date()
    yesterday = today - timedelta(days=1)
    previous_seven_day_start_date = today - timedelta(days=TREND_DAYS * 2 - 1)
    seven_day_start_date = beijing_now.date() - timedelta(days=TREND_DAYS - 1)
    video_seven_day_start_date = today - timedelta(days=6)
    previous_video_seven_day_start_date = today - timedelta(days=13)
    today_start = beijing_day_start(today)
    yesterday_start = beijing_day_start(yesterday)
    seven_day_start = beijing_day_start(seven_day_start_date)
    previous_seven_day_start = beijing_day_start(previous_seven_day_start_date)
    video_seven_day_start = beijing_day_start(video_seven_day_start_date)
    previous_video_seven_day_start = beijing_day_start(previous_video_seven_day_start_date)

    total_page_views = query_value("SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'page_view'")
    today_page_views = query_value(
        "SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'page_view' AND created_at >= ?",
        (today_start,),
    )
    yesterday_page_views = query_value(
        """
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE event_name = 'page_view' AND created_at >= ? AND created_at < ?
        """,
        (yesterday_start, today_start),
    )
    seven_day_page_views = query_value(
        "SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'page_view' AND created_at >= ?",
        (seven_day_start,),
    )
    previous_seven_day_page_views = query_value(
        """
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE event_name = 'page_view' AND created_at >= ? AND created_at < ?
        """,
        (previous_seven_day_start, seven_day_start),
    )
    video_plays = query_value("SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'video_play'")
    today_video_plays = query_value(
        "SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'video_play' AND created_at >= ?",
        (today_start,),
    )
    unique_visitors = query_value(
        "SELECT COUNT(DISTINCT ip_hash) AS count FROM analytics_events WHERE event_name = 'page_view' AND ip_hash != ''"
    )
    previous_unique_visitors = query_value(
        """
        SELECT COUNT(DISTINCT ip_hash) AS count
        FROM analytics_events
        WHERE event_name = 'page_view' AND ip_hash != '' AND created_at < ?
        """,
        (today_start,),
    )
    seven_day_unique_visitors = query_value(
        """
        SELECT COUNT(DISTINCT ip_hash) AS count
        FROM analytics_events
        WHERE event_name = 'page_view' AND ip_hash != '' AND created_at >= ?
        """,
        (seven_day_start,),
    )

    top_paths = query_rows(
        """
        SELECT
            path,
            COUNT(*) AS count,
            COUNT(DISTINCT CASE WHEN ip_hash != '' THEN ip_hash END) AS uniques
        FROM analytics_events
        WHERE event_name = 'page_view'
        GROUP BY path
        ORDER BY count DESC
        LIMIT 10
        """
    )
    top_referrers = query_rows(
        """
        SELECT
            referrer_host,
            COUNT(*) AS count,
            COUNT(DISTINCT CASE WHEN ip_hash != '' THEN ip_hash END) AS uniques
        FROM analytics_events
        WHERE event_name = 'page_view'
            AND referrer_host NOT IN ('opentalking.net', 'www.opentalking.net')
        GROUP BY referrer_host
        ORDER BY count DESC
        LIMIT 10
        """
    )
    top_videos = query_rows(
        """
        SELECT
            video_id,
            COUNT(*) AS count,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS today_plays,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS last_7_days,
            SUM(CASE WHEN created_at >= ? AND created_at < ? THEN 1 ELSE 0 END) AS previous_7_days
        FROM analytics_events
        WHERE event_name = 'video_play'
        GROUP BY video_id
        ORDER BY count DESC
        LIMIT 50
        """,
        (today_start, video_seven_day_start, previous_video_seven_day_start, video_seven_day_start),
    )
    top_videos = [
        {
            **row,
            "video_label": copy["video_names"].get(row.get("video_id"), row.get("video_id") or "-"),
            "weekly_delta": int(row.get("last_7_days") or 0) - int(row.get("previous_7_days") or 0),
        }
        for row in top_videos
    ]
    seven_day_traffic = build_seven_day_traffic(beijing_now)
    github_trends = build_github_trends(beijing_now)
    daily_views = build_daily_views(beijing_now)

    card_deltas = {
        "today": today_page_views - yesterday_page_views,
        "seven_day": seven_day_page_views - previous_seven_day_page_views,
        "total": today_page_views,
        "video": today_video_plays,
        "visitors": unique_visitors - previous_unique_visitors,
    }

    def render_delta(key, value):
        delta_label = copy["deltas"][key]

        if value > 0:
            state = "positive"
            sign = "+"
            trend_word = copy["deltas"]["increase"]
        elif value < 0:
            state = "negative"
            sign = "-"
            trend_word = copy["deltas"]["decrease"]
        else:
            state = "neutral"
            sign = ""
            trend_word = copy["deltas"]["flat"]

        title = f'{delta_label} {trend_word} {format_number(abs(value))}'

        return (
            f'<span class="delta delta-{state}" tabindex="0" role="button" '
            f'title="{escape(title)}" aria-label="{escape(title)}" '
            f'data-tooltip-title="{escape(title)}" '
            f'data-tooltip-body="{escape(copy["delta_help"][key])}">'
            f'{sign}{escape(format_number(abs(value)))}</span>'
        )

    def render_metric_card(key, value):
        return (
            f'<div class="card">'
            f'<div class="label">{escape(copy["cards"][key])}</div>'
            f'<div class="value-row">'
            f'<span class="value">{escape(format_number(value))}</span>'
            f'{render_delta(key, card_deltas[key])}'
            f'</div>'
            f'</div>'
        )

    def render_table(rows, columns):
        if not rows:
            return f'<p class="empty">{escape(copy["empty"])}</p>'

        head = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
        body_parts = []

        def render_cell(key, value):
            display_value = value or "-"

            if key == "referrer_host" and display_value == "Direct / Unknown":
                help_copy = copy["direct_unknown_help"]
                help_items = "".join(f"<li>{escape(item)}</li>" for item in help_copy["items"])

                return (
                    f'<td><span class="source-help-wrap">'
                    f'<span>{escape(display_value)}</span>'
                    f'<span class="source-help" tabindex="0" role="button" aria-label="{escape(help_copy["label"])}" '
                    f'data-tooltip-title="{escape(help_copy["title"])}" '
                    f'data-tooltip-items="{escape(json.dumps(help_copy["items"], ensure_ascii=False))}">i</span>'
                    f'</span></td>'
                )

            return f"<td>{escape(str(display_value))}</td>"

        for row in rows:
            cells = []

            for key, _ in columns:
                cells.append(render_cell(key, row.get(key, "")))

            body_parts.append("<tr>" + "".join(cells) + "</tr>")

        body = "".join(body_parts)

        return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    def render_video_rankings(rows):
        if not rows:
            return f'<p class="empty">{escape(copy["empty"])}</p>'

        columns = [
            ("video_label", copy["columns"]["video"]),
            ("count", copy["columns"]["plays"]),
            ("last_7_days", copy["columns"]["last_7_days"]),
            ("weekly_delta", copy["columns"]["weekly_delta"]),
        ]
        head = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
        table_rows = []

        for row in rows[:10]:
            cells = []

            for key, _ in columns:
                if key == "video_label":
                    cells.append(f'<td>{escape(row.get("video_label") or "-")}</td>')
                    continue

                value = int(row.get(key) or 0)

                if key == "weekly_delta":
                    if value > 0:
                        state = "positive"
                        sign = "+"
                    elif value < 0:
                        state = "negative"
                        sign = "-"
                    else:
                        state = "neutral"
                        sign = ""

                    cells.append(
                        f'<td class="video-rank-value">'
                        f'<span class="delta delta-{state} video-rank-delta">'
                        f'{sign}{escape(format_number(abs(value)))}'
                        f'</span></td>'
                    )
                else:
                    cells.append(f'<td class="video-rank-value">{escape(format_number(value))}</td>')

            table_rows.append(f'<tr>{"".join(cells)}</tr>')

        return (
            f'<div class="table-wrap"><table class="video-rank-table">'
            f'<thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(table_rows)}</tbody></table></div>'
        )

    def render_line_chart(title, total_label, points, metric_key, chart_id, total_value=None):
        values = [point[metric_key] for point in points]
        total = sum(values) if total_value is None else total_value
        width = 520
        height = 260
        left = 52
        right = 18
        top = 20
        bottom = 42
        chart_width = width - left - right
        chart_height = height - top - bottom
        y_max = nice_chart_ceiling(max(values) if values else 0)
        x_step = chart_width / max(len(points) - 1, 1)
        coords = []

        for index, point in enumerate(points):
            x = left + x_step * index
            y = top + chart_height - (point[metric_key] / y_max * chart_height if y_max else 0)
            coords.append((x, y, point))

        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in coords)
        horizontal_lines = []

        for index in range(5):
            y = top + chart_height / 4 * index
            tick_value = round(y_max - y_max / 4 * index)
            horizontal_lines.append(
                f'<line class="chart-grid-line" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" />'
                f'<text class="chart-y-label" x="{left - 12}" y="{y + 4:.1f}" text-anchor="end">{tick_value}</text>'
            )

        vertical_lines = [
            f'<line class="chart-grid-line" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + chart_height}" />'
            for x, _, _ in coords
        ]
        x_label_indexes = set(range(len(coords))) if len(coords) <= 10 else set(range(0, len(coords), 2))

        x_labels = [
            f'<text class="chart-x-label" x="{x:.1f}" y="{height - 12}" text-anchor="middle">{escape(point["label"])}</text>'
            for index, (x, _, point) in enumerate(coords)
            if index in x_label_indexes
        ]
        dots = [
            f'<g class="chart-point" tabindex="0" data-label="{escape(point["label"])}" '
            f'data-value="{point[metric_key]}" data-metric="{escape(total_label)}">'
            f'<circle class="chart-hit-area" cx="{x:.1f}" cy="{y:.1f}" r="12"></circle>'
            f'<circle class="chart-dot" cx="{x:.1f}" cy="{y:.1f}" r="4"></circle>'
            f'</g>'
            for x, y, point in coords
        ]
        value_labels = [
            f'<text class="chart-value-label" x="{x:.1f}" y="{y - 11:.1f}" text-anchor="middle">{point[metric_key]}</text>'
            for x, y, point in coords
        ]
        chart_data = json.dumps(
            {
                "title": title,
                "metric": total_label,
                "dateLabel": copy["charts"]["date"],
                "valueLabel": copy["charts"]["value"],
                "rows": [{"date": point["label"], "value": point[metric_key]} for point in points],
            },
            ensure_ascii=False,
        )

        return f"""
          <section class="chart-card" data-chart-id="{escape(chart_id)}" data-chart="{escape(chart_data)}">
            <div class="chart-head">
              <div>
                <h2>{escape(title)}</h2>
                <p class="chart-summary">{escape(format_number(total))} {escape(total_label)}</p>
              </div>
              <div class="chart-actions">
                <button class="chart-icon-button chart-menu-button" type="button" aria-label="Chart menu">...</button>
                <button class="chart-icon-button chart-settings-button" type="button" aria-label="Chart settings">⚙</button>
                <div class="chart-popover chart-menu-popover" hidden>
                  <button type="button" data-action="view-table">{escape(copy["charts"]["view_table"])}</button>
                  <button type="button" data-action="download-csv">{escape(copy["charts"]["download_csv"])}</button>
                </div>
                <div class="chart-popover chart-settings-popover" hidden>
                  <label><input type="checkbox" data-action="toggle-labels" /> {escape(copy["charts"]["show_labels"])}</label>
                </div>
                <div class="chart-popover chart-table-popover" hidden></div>
              </div>
            </div>
            <svg class="traffic-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
              <g>{''.join(horizontal_lines)}</g>
              <g>{''.join(vertical_lines)}</g>
              <polyline class="chart-line" points="{polyline}" />
              <g>{''.join(dots)}</g>
              <g class="chart-value-labels">{''.join(value_labels)}</g>
              <g>{''.join(x_labels)}</g>
            </svg>
          </section>
        """

    html = f"""
    <!doctype html>
    <html lang="{escape(copy["html_lang"])}">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{escape(copy["title"])}</title>
        <style>
          body {{
            margin: 0;
            background: #f8fafc;
            color: #0f172a;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }}
          main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 56px; }}
          .topbar {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 24px; }}
          .top-actions {{ display: grid; justify-items: end; gap: 8px; }}
          .lang-switch {{ display: inline-flex; align-items: center; justify-content: center; border: 1px solid #e2e8f0; border-radius: 999px; background: #fff; color: #334155; padding: 6px 10px; font-size: 12px; font-weight: 700; text-decoration: none; box-shadow: 0 10px 28px rgba(15,23,42,.06); transition: transform .18s ease, border-color .18s ease; }}
          .lang-switch:hover {{ border-color: #67e8f9; transform: translateY(-1px); }}
          h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
          .muted {{ color: #64748b; font-size: 13px; }}
          .cards {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }}
          .card, section {{ border: 1px solid #e2e8f0; background: rgba(255,255,255,.86); border-radius: 14px; box-shadow: 0 18px 50px rgba(15,23,42,.06); }}
          .card {{ padding: 16px; }}
          .label {{ color: #64748b; font-size: 12px; font-weight: 700; text-transform: uppercase; }}
          .value-row {{ display: flex; align-items: baseline; gap: 8px; margin-top: 8px; min-width: 0; }}
          .value {{ font-size: 26px; font-weight: 750; letter-spacing: 0; }}
          .delta {{ display: inline-flex; align-items: center; justify-content: center; border: 0; border-radius: 999px; padding: 2px 6px; font-size: 12px; font-weight: 800; line-height: 1.35; white-space: nowrap; cursor: help; transition: transform .16s ease, box-shadow .16s ease; }}
          .delta:hover, .delta:focus-visible {{ outline: none; transform: translateY(-1px); box-shadow: 0 8px 18px rgba(15,23,42,.08); }}
          .delta-positive {{ background: #dcfce7; color: #15803d; }}
          .delta-negative {{ background: #fee2e2; color: #dc2626; }}
          .delta-neutral {{ background: #f1f5f9; color: #64748b; }}
          .delta-help-card {{ position: fixed; z-index: 85; width: min(270px, calc(100vw - 40px)); border: 1px solid #dbe3ec; border-radius: 12px; background: rgba(255,255,255,.98); box-shadow: 0 18px 46px rgba(15,23,42,.16); padding: 11px 13px; color: #334155; font-size: 12px; line-height: 1.55; }}
          .delta-help-card[hidden] {{ display: none; }}
          .delta-help-card strong {{ display: block; color: #0f172a; font-size: 13px; margin-bottom: 5px; }}
          .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
          .chart-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }}
          section {{ padding: 18px; overflow: hidden; }}
          h2 {{ margin: 0 0 14px; font-size: 16px; }}
          .table-wrap {{ max-height: 330px; overflow: auto; }}
          table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
          th, td {{ padding: 10px 8px; border-bottom: 1px solid #eef2f7; text-align: left; vertical-align: top; }}
          th {{ position: sticky; top: 0; background: rgba(255,255,255,.96); color: #64748b; font-size: 12px; font-weight: 700; }}
          .video-rank-table {{ min-width: 520px; }}
          .video-rank-table th:first-child, .video-rank-table td:first-child {{ min-width: 220px; }}
          .video-rank-table th:not(:first-child), .video-rank-value {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
          .video-rank-table th:not(:first-child) {{ width: 86px; }}
          .video-rank-delta {{ cursor: default; min-width: 34px; }}
          .empty {{ margin: 0; color: #94a3b8; font-size: 13px; }}
          .source-help-wrap {{ display: inline-flex; align-items: center; gap: 6px; }}
          .source-help {{ display: inline-flex; height: 15px; width: 15px; align-items: center; justify-content: center; border-radius: 999px; background: #e0f2fe; color: #0284c7; cursor: help; font-size: 10px; font-weight: 800; line-height: 1; }}
          .source-help:hover, .source-help:focus-visible {{ background: #bae6fd; color: #0369a1; outline: none; }}
          .source-help-card {{ position: fixed; z-index: 80; width: min(320px, calc(100vw - 40px)); border: 1px solid #dbe3ec; border-radius: 12px; background: rgba(255,255,255,.98); box-shadow: 0 18px 46px rgba(15,23,42,.16); padding: 12px 14px; color: #334155; font-size: 12px; line-height: 1.55; }}
          .source-help-card[hidden] {{ display: none; }}
          .source-help-card strong {{ display: block; color: #0f172a; font-size: 13px; margin-bottom: 6px; }}
          .source-help-card ul {{ margin: 0; padding-left: 17px; }}
          .source-help-card li + li {{ margin-top: 4px; }}
          .chart-card {{ min-height: 336px; }}
          .chart-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 8px; }}
          .chart-head h2 {{ margin-bottom: 8px; font-size: 20px; line-height: 1.25; }}
          .chart-summary {{ margin: 0; color: #64748b; font-size: 14px; font-weight: 650; }}
          .chart-actions {{ position: relative; display: flex; gap: 6px; }}
          .chart-icon-button {{ display: inline-flex; height: 30px; min-width: 30px; align-items: center; justify-content: center; border: 1px solid transparent; border-radius: 8px; background: transparent; color: #64748b; cursor: pointer; font-size: 15px; font-weight: 800; line-height: 1; transition: background .16s ease, border-color .16s ease, color .16s ease; }}
          .chart-icon-button:hover, .chart-icon-button:focus-visible {{ border-color: #dbe3ec; background: #f8fafc; color: #0f172a; outline: none; }}
          .chart-menu-button {{ letter-spacing: 2px; padding-bottom: 5px; }}
          .chart-popover {{ position: absolute; right: 0; top: 36px; z-index: 5; min-width: 172px; border: 1px solid #dbe3ec; border-radius: 10px; background: rgba(255,255,255,.98); box-shadow: 0 18px 50px rgba(15,23,42,.14); padding: 6px; }}
          .chart-popover button, .chart-popover label {{ display: flex; width: 100%; align-items: center; gap: 8px; border: 0; border-radius: 8px; background: transparent; color: #334155; cursor: pointer; font: inherit; font-size: 13px; font-weight: 650; padding: 9px 10px; text-align: left; }}
          .chart-popover button:hover {{ background: #f1f5f9; color: #0f172a; }}
          .chart-settings-popover {{ min-width: 188px; }}
          .chart-table-popover {{ min-width: 240px; max-height: 278px; overflow: auto; padding: 8px; }}
          .chart-table-popover table {{ font-size: 12px; }}
          .chart-table-popover th, .chart-table-popover td {{ padding: 8px 7px; }}
          .traffic-chart {{ display: block; width: 100%; height: 260px; overflow: visible; }}
          .chart-grid-line {{ stroke: #dbe3ec; stroke-width: 1; }}
          .chart-line {{ fill: none; stroke: #2da44e; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }}
          .chart-hit-area {{ fill: transparent; cursor: pointer; }}
          .chart-dot {{ fill: #2da44e; stroke: #fff; stroke-width: 2; pointer-events: none; transition: r .16s ease, stroke-width .16s ease; }}
          .chart-point:hover .chart-dot, .chart-point:focus .chart-dot, .chart-point:focus-within .chart-dot {{ r: 6; stroke-width: 3; outline: none; }}
          .chart-y-label, .chart-x-label {{ fill: #64748b; font-size: 12px; font-weight: 650; }}
          .chart-value-labels {{ display: none; }}
          .chart-card.show-labels .chart-value-labels {{ display: block; }}
          .chart-value-label {{ fill: #0f172a; font-size: 11px; font-weight: 750; paint-order: stroke; stroke: #fff; stroke-width: 4px; }}
          .chart-tooltip {{ position: fixed; z-index: 50; pointer-events: none; min-width: 132px; border: 1px solid #dbe3ec; border-radius: 10px; background: rgba(255,255,255,.98); box-shadow: 0 18px 44px rgba(15,23,42,.16); padding: 10px 12px; color: #0f172a; transform: translate(-50%, calc(-100% - 14px)); }}
          .chart-tooltip-date {{ color: #64748b; font-size: 13px; font-weight: 800; }}
          .chart-tooltip-value {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 7px; font-size: 13px; }}
          .chart-tooltip-dot {{ display: inline-flex; height: 10px; width: 10px; border-radius: 999px; background: #2da44e; }}
          .chart-tooltip-number {{ font-size: 16px; font-weight: 800; }}
          @media (max-width: 900px) {{
            .cards, .grid, .chart-grid {{ grid-template-columns: 1fr; }}
            .topbar {{ align-items: flex-start; flex-direction: column; }}
            .top-actions {{ justify-items: start; }}
          }}
        </style>
      </head>
      <body>
        <main>
          <div class="topbar">
            <div>
              <h1>{escape(copy["title"])}</h1>
              <p class="muted">{escape(copy["description"])}</p>
            </div>
            <div class="top-actions">
              <a class="lang-switch" href="{escape(copy["language_href"])}">{escape(copy["language_switch"])}</a>
              <p class="muted">{escape(copy["updated"])} {escape(beijing_now.strftime("%Y-%m-%d %H:%M:%S"))} {escape(copy["timezone"])}</p>
            </div>
          </div>
          <div class="cards">
            {render_metric_card("today", today_page_views)}
            {render_metric_card("seven_day", seven_day_page_views)}
            {render_metric_card("total", total_page_views)}
            {render_metric_card("video", video_plays)}
            {render_metric_card("visitors", unique_visitors)}
          </div>
          <div class="grid">
            <section>
              <h2>{escape(copy["sections"]["top_pages"])}</h2>
              {render_table(top_paths, [("path", copy["columns"]["path"]), ("count", copy["columns"]["views"]), ("uniques", copy["columns"]["uniques"])])}
            </section>
            <section>
              <h2>{escape(copy["sections"]["top_referrers"])}</h2>
              {render_table(top_referrers, [("referrer_host", copy["columns"]["source"]), ("count", copy["columns"]["views"]), ("uniques", copy["columns"]["uniques"])])}
            </section>
            <section>
              <h2>{escape(copy["sections"]["top_videos"])}</h2>
              {render_video_rankings(top_videos)}
            </section>
            <section>
              <h2>{escape(copy["sections"]["daily_views"])}</h2>
              {render_table(daily_views, [("day", copy["columns"]["day"]), ("count", copy["columns"]["views"])])}
            </section>
          </div>
          <div class="chart-grid">
            {render_line_chart(copy["charts"]["views_title"], copy["charts"]["views_total"], seven_day_traffic, "views", "fourteen-day-views")}
            {render_line_chart(copy["charts"]["unique_title"], copy["charts"]["unique_total"], seven_day_traffic, "uniques", "fourteen-day-uniques", seven_day_unique_visitors)}
            {render_line_chart(copy["charts"]["stars_title"], copy["charts"]["stars_total"], github_trends["stars"], "count", "fourteen-day-stars", github_trends["star_total"])}
            {render_line_chart(copy["charts"]["forks_title"], copy["charts"]["forks_total"], github_trends["forks"], "count", "fourteen-day-forks", github_trends["fork_total"])}
          </div>
        </main>
        <script>
          (() => {{
            const tooltip = document.createElement("div");
            tooltip.className = "chart-tooltip";
            tooltip.hidden = true;
            document.body.appendChild(tooltip);

            const sourceTooltip = document.createElement("div");
            sourceTooltip.className = "source-help-card";
            sourceTooltip.hidden = true;
            document.body.appendChild(sourceTooltip);

            const deltaTooltip = document.createElement("div");
            deltaTooltip.className = "delta-help-card";
            deltaTooltip.hidden = true;
            document.body.appendChild(deltaTooltip);

            const closePopovers = (except) => {{
              document.querySelectorAll(".chart-popover").forEach((popover) => {{
                if (popover !== except) popover.hidden = true;
              }});
            }};

            const getChartData = (card) => JSON.parse(card.dataset.chart || "{{}}");

            const renderTooltip = (point) => {{
              const rect = point.getBoundingClientRect();
              tooltip.innerHTML = `
                <div class="chart-tooltip-date">${{point.dataset.label}}</div>
                <div class="chart-tooltip-value">
                  <span><span class="chart-tooltip-dot"></span> ${{point.dataset.metric}}</span>
                  <span class="chart-tooltip-number">${{point.dataset.value}}</span>
                </div>
              `;
              tooltip.style.left = `${{rect.left + rect.width / 2}}px`;
              tooltip.style.top = `${{rect.top}}px`;
              tooltip.hidden = false;
            }};

            const hideTooltip = () => {{
              tooltip.hidden = true;
            }};

            const positionFloatingCard = (trigger, card) => {{
              card.hidden = false;

              const rect = trigger.getBoundingClientRect();
              const tooltipRect = card.getBoundingClientRect();
              const margin = 12;
              const left = Math.min(
                Math.max(rect.left + rect.width / 2 - tooltipRect.width / 2, margin),
                window.innerWidth - tooltipRect.width - margin
              );
              const top = rect.bottom + tooltipRect.height + margin > window.innerHeight
                ? Math.max(rect.top - tooltipRect.height - 8, margin)
                : rect.bottom + 8;

              card.style.left = `${{left}}px`;
              card.style.top = `${{top}}px`;
            }};

            const showDeltaTooltip = (trigger) => {{
              const title = trigger.dataset.tooltipTitle || "";
              const body = trigger.dataset.tooltipBody || "";
              deltaTooltip.innerHTML = `<strong>${{title}}</strong><div>${{body}}</div>`;
              positionFloatingCard(trigger, deltaTooltip);
            }};

            const hideDeltaTooltip = () => {{
              deltaTooltip.hidden = true;
            }};

            const showSourceTooltip = (trigger) => {{
              const title = trigger.dataset.tooltipTitle || "";
              let items = [];

              try {{
                items = JSON.parse(trigger.dataset.tooltipItems || "[]");
              }} catch {{
                items = [];
              }}

              sourceTooltip.innerHTML = `
                <strong>${{title}}</strong>
                <ul>${{items.map((item) => `<li>${{item}}</li>`).join("")}}</ul>
              `;

              sourceTooltip.hidden = false;

              const rect = trigger.getBoundingClientRect();
              const tooltipRect = sourceTooltip.getBoundingClientRect();
              const margin = 12;
              const left = Math.min(
                Math.max(rect.left, margin),
                window.innerWidth - tooltipRect.width - margin
              );
              const top = rect.bottom + tooltipRect.height + margin > window.innerHeight
                ? Math.max(rect.top - tooltipRect.height - 8, margin)
                : rect.bottom + 8;

              sourceTooltip.style.left = `${{left}}px`;
              sourceTooltip.style.top = `${{top}}px`;
            }};

            const hideSourceTooltip = () => {{
              sourceTooltip.hidden = true;
            }};

            const renderDataTable = (card) => {{
              const data = getChartData(card);
              const container = card.querySelector(".chart-table-popover");
              if (!container) return;

              if (!container.hidden) {{
                container.hidden = true;
                container.innerHTML = "";
                return;
              }}

              const rows = (data.rows || [])
                .map((row) => `<tr><td>${{row.date}}</td><td>${{row.value}}</td></tr>`)
                .join("");
              container.innerHTML = `
                <table>
                  <thead><tr><th>${{data.dateLabel}}</th><th>${{data.metric}}</th></tr></thead>
                  <tbody>${{rows}}</tbody>
                </table>
              `;
              closePopovers(container);
              container.hidden = false;
            }};

            const downloadCsv = (card) => {{
              const data = getChartData(card);
              const rows = [[data.dateLabel || "Date", data.metric || "Value"], ...((data.rows || []).map((row) => [row.date, row.value]))];
              const csv = rows.map((row) => row.map((cell) => `"${{String(cell).replaceAll('"', '""')}}"`).join(",")).join("\\n");
              const blob = new Blob([csv], {{ type: "text/csv;charset=utf-8" }});
              const url = URL.createObjectURL(blob);
              const link = document.createElement("a");
              link.href = url;
              link.download = `${{(data.title || "traffic-chart").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "traffic-chart"}}.csv`;
              document.body.appendChild(link);
              link.click();
              link.remove();
              URL.revokeObjectURL(url);
            }};

            const setDataLabelsVisible = (isVisible) => {{
              document.querySelectorAll(".chart-card").forEach((card) => {{
                card.classList.toggle("show-labels", isVisible);
              }});
              document.querySelectorAll('[data-action="toggle-labels"]').forEach((checkbox) => {{
                checkbox.checked = isVisible;
              }});
            }};

            document.querySelectorAll(".chart-card").forEach((card) => {{
              card.querySelectorAll(".chart-popover").forEach((popover) => {{
                popover.addEventListener("click", (event) => event.stopPropagation());
              }});

              card.querySelectorAll(".chart-point").forEach((point) => {{
                point.addEventListener("pointerover", () => renderTooltip(point));
                point.addEventListener("pointerout", hideTooltip);
                point.addEventListener("mouseover", () => renderTooltip(point));
                point.addEventListener("mouseout", hideTooltip);
                point.addEventListener("click", () => renderTooltip(point));
                point.addEventListener("focus", () => renderTooltip(point));
                point.addEventListener("blur", hideTooltip);
              }});

              const menu = card.querySelector(".chart-menu-popover");
              const settings = card.querySelector(".chart-settings-popover");

              card.querySelector(".chart-menu-button")?.addEventListener("click", (event) => {{
                event.stopPropagation();
                if (!menu) return;
                const nextHidden = !menu.hidden;
                closePopovers();
                menu.hidden = nextHidden;
              }});

              card.querySelector(".chart-settings-button")?.addEventListener("click", (event) => {{
                event.stopPropagation();
                if (!settings) return;
                const nextHidden = !settings.hidden;
                closePopovers();
                settings.hidden = nextHidden;
              }});

              card.querySelector('[data-action="view-table"]')?.addEventListener("click", (event) => {{
                event.stopPropagation();
                renderDataTable(card);
              }});

              card.querySelector('[data-action="download-csv"]')?.addEventListener("click", (event) => {{
                event.stopPropagation();
                downloadCsv(card);
                closePopovers();
              }});

              card.querySelector('[data-action="toggle-labels"]')?.addEventListener("change", (event) => {{
                setDataLabelsVisible(event.target.checked);
              }});
            }});

            document.querySelectorAll(".source-help").forEach((trigger) => {{
              trigger.addEventListener("pointerenter", () => showSourceTooltip(trigger));
              trigger.addEventListener("pointerleave", hideSourceTooltip);
              trigger.addEventListener("mouseover", () => showSourceTooltip(trigger));
              trigger.addEventListener("mouseout", hideSourceTooltip);
              trigger.addEventListener("focus", () => showSourceTooltip(trigger));
              trigger.addEventListener("blur", hideSourceTooltip);
              trigger.addEventListener("click", (event) => {{
                event.stopPropagation();
                showSourceTooltip(trigger);
              }});
            }});

            document.querySelectorAll(".delta").forEach((trigger) => {{
              trigger.addEventListener("pointerenter", () => showDeltaTooltip(trigger));
              trigger.addEventListener("pointerleave", hideDeltaTooltip);
              trigger.addEventListener("mouseover", () => showDeltaTooltip(trigger));
              trigger.addEventListener("mouseout", hideDeltaTooltip);
              trigger.addEventListener("focus", () => showDeltaTooltip(trigger));
              trigger.addEventListener("blur", hideDeltaTooltip);
              trigger.addEventListener("click", (event) => {{
                event.stopPropagation();
                showDeltaTooltip(trigger);
              }});
            }});

            sourceTooltip.addEventListener("pointerenter", () => {{
              sourceTooltip.hidden = false;
            }});
            sourceTooltip.addEventListener("pointerleave", hideSourceTooltip);
            deltaTooltip.addEventListener("pointerenter", () => {{
              deltaTooltip.hidden = false;
            }});
            deltaTooltip.addEventListener("pointerleave", hideDeltaTooltip);

            document.addEventListener("click", () => {{
              closePopovers();
              hideSourceTooltip();
              hideDeltaTooltip();
            }});
            document.addEventListener("keydown", (event) => {{
              if (event.key === "Escape") {{
                closePopovers();
                hideTooltip();
                hideSourceTooltip();
                hideDeltaTooltip();
              }}
            }});
          }})();
        </script>
      </body>
    </html>
    """

    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/github-api/repos/{owner}/{repo}")
def github_repo_stats(owner: str, repo: str):
    if owner != GITHUB_REPO_OWNER or repo != GITHUB_REPO_NAME:
        raise HTTPException(status_code=404, detail="GitHub repo proxy not found")

    request = Request(
        GITHUB_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "opentalking-homepage",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            return JSONResponse(
                content=json.loads(response.read().decode("utf-8")),
                media_type="application/json",
                headers={"Cache-Control": "no-store"},
            )
    except HTTPError as error:
        raise HTTPException(status_code=error.code, detail="GitHub API request failed") from error
    except URLError as error:
        raise HTTPException(status_code=502, detail=f"GitHub API unavailable: {error.reason}") from error


@app.get("/{path:path}")
def serve_spa(path: str):
    target = DIST_DIR / path

    if target.is_file():
        return FileResponse(target)

    return FileResponse(DIST_DIR / "index.html")
