import json
import os
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse
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
ANALYTICS_DB_PATH = Path(os.getenv("HOMEPAGE_ANALYTICS_DB", ROOT / ".analytics" / "homepage_analytics.sqlite3"))
ANALYTICS_HASH_SALT = os.getenv("HOMEPAGE_ANALYTICS_SALT", "opentalking-homepage")
MAX_FIELD_LENGTH = 500
BEIJING_TZ = timezone(timedelta(hours=8))

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
        "timezone": "UTC+8",
        "language_switch": "EN",
        "language_href": "/en/traffic",
        "empty": "暂无数据。",
        "cards": {
            "today": "今日访问",
            "seven_day": "7 天访问",
            "total": "累计访问",
            "video": "视频播放",
            "visitors": "访客",
        },
        "sections": {
            "top_pages": "热门页面",
            "top_referrers": "来源排行",
            "top_videos": "视频播放排行",
            "daily_views": "每日访问",
        },
        "charts": {
            "views_title": "过去 7 天访问量",
            "unique_title": "过去 7 天独立访客",
            "views_total": "Views",
            "unique_total": "Unique Visitors",
        },
        "video_names": {
            "hero-companion-character": "首页主视觉：陪伴类角色",
            "case-ecommerce-livestream": "案例：电商带货",
            "case-news-anchor": "案例：新闻主播",
            "case-companion-character": "案例：陪伴类角色",
            "case-anime-talk-show": "案例：动漫脱口秀",
            "case-creative-performance": "案例：创意演唱 / 模仿秀",
            "case-mobile-recording": "案例：实时手机录制",
        },
        "columns": {
            "path": "路径",
            "views": "访问",
            "uniques": "独立访客",
            "source": "来源",
            "video": "视频",
            "plays": "播放",
            "day": "日期",
        },
    },
    "en": {
        "html_lang": "en",
        "title": "OpenTalking Traffic",
        "description": "Lightweight first-party analytics. IP addresses are stored as hashes only.",
        "updated": "Updated",
        "timezone": "UTC+8",
        "language_switch": "中",
        "language_href": "/traffic",
        "empty": "No data yet.",
        "cards": {
            "today": "Today views",
            "seven_day": "7-day views",
            "total": "Total views",
            "video": "Video plays",
            "visitors": "Visitors",
        },
        "sections": {
            "top_pages": "Top Pages",
            "top_referrers": "Top Referrers",
            "top_videos": "Top Videos",
            "daily_views": "Daily Views",
        },
        "charts": {
            "views_title": "Total views in last 7 days",
            "unique_title": "Unique visitors in last 7 days",
            "views_total": "Views",
            "unique_total": "Unique Visitors",
        },
        "video_names": {
            "hero-companion-character": "Hero: Companion Character",
            "case-ecommerce-livestream": "Case: E-commerce Livestream",
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
            "day": "Day",
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
    days = [today - timedelta(days=offset) for offset in reversed(range(7))]
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
            "label": value["label"],
            "views": value["views"],
            "uniques": len(value["visitors"]),
        }
        for value in day_keys.values()
    ]


def nice_chart_ceiling(value):
    if value <= 4:
        return 4

    if value <= 10:
        return 10

    magnitude = 10 ** (len(str(value)) - 1)

    return ((value + magnitude - 1) // magnitude) * magnitude


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
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    seven_days_ago = (now - timedelta(days=7)).isoformat()

    total_page_views = query_value("SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'page_view'")
    today_page_views = query_value(
        "SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'page_view' AND created_at >= ?",
        (today_start,),
    )
    seven_day_page_views = query_value(
        "SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'page_view' AND created_at >= ?",
        (seven_days_ago,),
    )
    video_plays = query_value("SELECT COUNT(*) AS count FROM analytics_events WHERE event_name = 'video_play'")
    unique_visitors = query_value("SELECT COUNT(DISTINCT ip_hash) AS count FROM analytics_events WHERE ip_hash != ''")

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
        GROUP BY referrer_host
        ORDER BY count DESC
        LIMIT 10
        """
    )
    top_videos = query_rows(
        """
        SELECT video_id, COUNT(*) AS count
        FROM analytics_events
        WHERE event_name = 'video_play'
        GROUP BY video_id
        ORDER BY count DESC
        LIMIT 10
        """
    )
    top_videos = [
        {
            **row,
            "video_label": copy["video_names"].get(row.get("video_id"), row.get("video_id") or "-"),
        }
        for row in top_videos
    ]
    daily_views = query_rows(
        """
        SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
        FROM analytics_events
        WHERE event_name = 'page_view' AND created_at >= ?
        GROUP BY day
        ORDER BY day DESC
        LIMIT 7
        """,
        (seven_days_ago,),
    )
    seven_day_traffic = build_seven_day_traffic(beijing_now)

    def render_table(rows, columns):
        if not rows:
            return f'<p class="empty">{escape(copy["empty"])}</p>'

        head = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
        body_parts = []

        for row in rows:
            cells = []

            for key, _ in columns:
                value = row.get(key, "") or "-"

                cells.append(f"<td>{escape(str(value))}</td>")

            body_parts.append("<tr>" + "".join(cells) + "</tr>")

        body = "".join(body_parts)

        return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'

    def render_line_chart(title, total_label, points, metric_key):
        values = [point[metric_key] for point in points]
        total = sum(values)
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
        x_labels = [
            f'<text class="chart-x-label" x="{x:.1f}" y="{height - 12}" text-anchor="middle">{escape(point["label"])}</text>'
            for x, _, point in coords
        ]
        dots = [
            f'<circle class="chart-dot" cx="{x:.1f}" cy="{y:.1f}" r="4">'
            f'<title>{escape(point["label"])}: {point[metric_key]}</title>'
            f'</circle>'
            for x, y, point in coords
        ]

        return f"""
          <section class="chart-card">
            <div class="chart-head">
              <div>
                <h2>{escape(title)}</h2>
                <p class="chart-summary">{escape(format_number(total))} {escape(total_label)}</p>
              </div>
              <span class="chart-menu" aria-hidden="true">...</span>
            </div>
            <svg class="traffic-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
              <g>{''.join(horizontal_lines)}</g>
              <g>{''.join(vertical_lines)}</g>
              <polyline class="chart-line" points="{polyline}" />
              <g>{''.join(dots)}</g>
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
          .value {{ margin-top: 8px; font-size: 26px; font-weight: 750; }}
          .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
          .chart-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 14px; }}
          section {{ padding: 18px; overflow: hidden; }}
          h2 {{ margin: 0 0 14px; font-size: 16px; }}
          .table-wrap {{ max-height: 330px; overflow: auto; }}
          table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
          th, td {{ padding: 10px 8px; border-bottom: 1px solid #eef2f7; text-align: left; vertical-align: top; }}
          th {{ position: sticky; top: 0; background: rgba(255,255,255,.96); color: #64748b; font-size: 12px; font-weight: 700; }}
          .empty {{ margin: 0; color: #94a3b8; font-size: 13px; }}
          .chart-card {{ min-height: 336px; }}
          .chart-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 8px; }}
          .chart-head h2 {{ margin-bottom: 8px; font-size: 20px; line-height: 1.25; }}
          .chart-summary {{ margin: 0; color: #64748b; font-size: 14px; font-weight: 650; }}
          .chart-menu {{ color: #64748b; font-size: 22px; font-weight: 800; letter-spacing: 3px; line-height: 1; }}
          .traffic-chart {{ display: block; width: 100%; height: 260px; overflow: visible; }}
          .chart-grid-line {{ stroke: #dbe3ec; stroke-width: 1; }}
          .chart-line {{ fill: none; stroke: #2da44e; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }}
          .chart-dot {{ fill: #2da44e; stroke: #fff; stroke-width: 2; }}
          .chart-y-label, .chart-x-label {{ fill: #64748b; font-size: 12px; font-weight: 650; }}
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
            <div class="card"><div class="label">{escape(copy["cards"]["today"])}</div><div class="value">{today_page_views}</div></div>
            <div class="card"><div class="label">{escape(copy["cards"]["seven_day"])}</div><div class="value">{seven_day_page_views}</div></div>
            <div class="card"><div class="label">{escape(copy["cards"]["total"])}</div><div class="value">{total_page_views}</div></div>
            <div class="card"><div class="label">{escape(copy["cards"]["video"])}</div><div class="value">{video_plays}</div></div>
            <div class="card"><div class="label">{escape(copy["cards"]["visitors"])}</div><div class="value">{unique_visitors}</div></div>
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
              {render_table(top_videos, [("video_label", copy["columns"]["video"]), ("count", copy["columns"]["plays"])])}
            </section>
            <section>
              <h2>{escape(copy["sections"]["daily_views"])}</h2>
              {render_table(daily_views, [("day", copy["columns"]["day"]), ("count", copy["columns"]["views"])])}
            </section>
          </div>
          <div class="chart-grid">
            {render_line_chart(copy["charts"]["views_title"], copy["charts"]["views_total"], seven_day_traffic, "views")}
            {render_line_chart(copy["charts"]["unique_title"], copy["charts"]["unique_total"], seven_day_traffic, "uniques")}
          </div>
        </main>
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
