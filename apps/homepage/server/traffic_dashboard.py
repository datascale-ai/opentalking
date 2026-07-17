import json
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi.responses import HTMLResponse

from server.analytics_store import query_rows, query_value
from server.config import BEIJING_TZ, GITHUB_TOKEN_ENV, TREND_DAYS
from server.github_stats import build_github_trends, parse_event_datetime
from server.traffic_i18n import TRAFFIC_COPY


def format_number(value):
    return f"{value:,}"



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



def nice_chart_ceiling(value):
    if value <= 4:
        return 4

    if value <= 10:
        return 10

    magnitude = 10 ** (len(str(value)) - 1)

    return ((value + magnitude - 1) // magnitude) * magnitude



def beijing_day_start(day):
    return datetime(day.year, day.month, day.day, tzinfo=BEIJING_TZ).astimezone(timezone.utc).isoformat()


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

    def render_line_chart(title, total_label, points, metric_key, chart_id, total_value=None, unavailable_message=""):
        values = [point[metric_key] for point in points]
        total = sum(values) if total_value is None else total_value
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

        if unavailable_message:
            return f"""
              <section class="chart-card chart-card-unavailable" data-chart-id="{escape(chart_id)}" data-chart="{escape(chart_data)}">
                <div class="chart-head">
                  <div>
                    <h2>{escape(title)}</h2>
                    <p class="chart-summary">{escape(format_number(total))} {escape(total_label)}</p>
                  </div>
                </div>
                <div class="chart-unavailable">
                  <strong>{escape(unavailable_message)}</strong>
                  <span>{escape(GITHUB_TOKEN_ENV)}</span>
                </div>
              </section>
            """

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
          .chart-card-unavailable {{ display: flex; min-height: 336px; flex-direction: column; }}
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
          .chart-unavailable {{ display: grid; flex: 1; place-content: center; gap: 10px; min-height: 230px; border: 1px dashed #cbd5e1; border-radius: 14px; background: linear-gradient(135deg, rgba(248,250,252,.96), rgba(240,249,255,.86)); color: #475569; text-align: center; padding: 24px; }}
          .chart-unavailable strong {{ max-width: 360px; color: #0f172a; font-size: 15px; line-height: 1.6; }}
          .chart-unavailable span {{ justify-self: center; border-radius: 999px; background: #fff; border: 1px solid #dbe3ec; color: #64748b; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 12px; font-weight: 800; padding: 5px 10px; }}
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
            {render_line_chart(copy["charts"]["stars_title"], copy["charts"]["stars_total"], github_trends["stars"], "count", "fourteen-day-stars", github_trends["star_total"], "" if github_trends["stars_available"] else copy["charts"]["github_token_expired"])}
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
