from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


WeFlowDetectedFormat = Literal["chatlab_json", "raw_json", "csv", "txt", "html"]
_SUPPORTED_SUFFIXES = {".json", ".csv", ".txt", ".html", ".htm"}
_JSON_PRIORITY = {".json": 0, ".csv": 1, ".txt": 2, ".html": 3, ".htm": 3}
_SELF_NAMES = {"\u6211", "me", "self", "\u81ea\u5df1", "\u672c\u4eba"}


class WeFlowParseError(ValueError):
    """Raised when an uploaded WeFlow export cannot be parsed safely."""


@dataclass(frozen=True)
class WeFlowTurn:
    message_id: str | None
    speaker_id: str
    speaker_name: str
    content: str
    timestamp: str | None = None
    is_self: bool = False
    message_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WeFlowSpeaker:
    id: str
    name: str
    message_count: int
    is_self: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WeFlowExport:
    conversation_id: str | None
    detected_format: WeFlowDetectedFormat
    turns: list[WeFlowTurn]
    speakers: list[WeFlowSpeaker]
    source_metadata: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def parse_weflow_export(
    path: str | Path,
    *,
    source_format: str = "auto",
    timezone: str = "Asia/Shanghai",
    conversation_id: str | None = None,
) -> WeFlowExport:
    """Parse a user-uploaded WeFlow export file into normalized chat turns.

    This function intentionally accepts files only. It rejects URL/API inputs so the product
    remains an import flow instead of a WeChat/WeFlow connector.
    """

    file_path = _validate_local_file(path)
    tz = _zoneinfo(timezone)
    if file_path.suffix.lower() == ".zip":
        return _parse_zip(file_path, source_format=source_format, timezone=tz, conversation_id=conversation_id)
    data = file_path.read_bytes()
    metadata = {"source_name": file_path.name, "byte_size": len(data)}
    return _parse_payload(
        data,
        source_name=file_path.name,
        source_format=source_format,
        timezone=tz,
        conversation_id=conversation_id,
        source_metadata=metadata,
    )


def _validate_local_file(path: str | Path) -> Path:
    raw = str(path)
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https", "ws", "wss"}:
        raise WeFlowParseError("please upload an exported WeFlow file instead of a WeFlow API URL")
    file_path = Path(path)
    if not file_path.is_file():
        raise WeFlowParseError("WeFlow export file not found")
    suffix = file_path.suffix.lower()
    if suffix != ".zip" and suffix not in _SUPPORTED_SUFFIXES:
        raise WeFlowParseError(f"unsupported WeFlow export file type: {suffix or '<none>'}")
    return file_path


def _zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Shanghai")
    except ZoneInfoNotFoundError as exc:
        raise WeFlowParseError(f"unsupported timezone: {name}") from exc


def _parse_zip(
    path: Path,
    *,
    source_format: str,
    timezone: ZoneInfo,
    conversation_id: str | None,
) -> WeFlowExport:
    with zipfile.ZipFile(path) as zf:
        candidates = [info for info in zf.infolist() if not info.is_dir()]
        candidates = [info for info in candidates if Path(info.filename).suffix.lower() in _SUPPORTED_SUFFIXES]
        if not candidates:
            raise WeFlowParseError("unsupported WeFlow zip export: no JSON/CSV/TXT/HTML member found")
        candidates.sort(key=lambda info: (_JSON_PRIORITY[Path(info.filename).suffix.lower()], info.filename))
        selected = candidates[0]
        data = zf.read(selected)
    metadata = {
        "source_name": path.name,
        "archive_member": selected.filename,
        "byte_size": len(data),
    }
    return _parse_payload(
        data,
        source_name=selected.filename,
        source_format=source_format,
        timezone=timezone,
        conversation_id=conversation_id,
        source_metadata=metadata,
    )


def _parse_payload(
    data: bytes,
    *,
    source_name: str,
    source_format: str,
    timezone: ZoneInfo,
    conversation_id: str | None,
    source_metadata: dict[str, Any],
) -> WeFlowExport:
    suffix = Path(source_name).suffix.lower()
    fmt = (source_format or "auto").strip().lower()
    if fmt == "auto":
        fmt = _format_from_suffix(suffix)
    if fmt in {"json", "chatlab_json", "raw_json"}:
        payload = _load_json(data)
        return _parse_json_payload(
            payload,
            requested_format=fmt,
            timezone=timezone,
            conversation_id=conversation_id,
            source_metadata=source_metadata,
        )
    text = _decode_text(data)
    if fmt == "csv":
        return _parse_csv_text(text, timezone=timezone, conversation_id=conversation_id, source_metadata=source_metadata)
    if fmt == "txt":
        return _parse_txt_text(text, timezone=timezone, conversation_id=conversation_id, source_metadata=source_metadata)
    if fmt in {"html", "htm"}:
        return _parse_html_text(text, timezone=timezone, conversation_id=conversation_id, source_metadata=source_metadata)
    raise WeFlowParseError(f"unsupported WeFlow export format: {source_format}")


def _format_from_suffix(suffix: str) -> str:
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    if suffix == ".txt":
        return "txt"
    if suffix in {".html", ".htm"}:
        return "html"
    raise WeFlowParseError(f"unsupported WeFlow export file type: {suffix or '<none>'}")


def _load_json(data: bytes) -> Any:
    try:
        return json.loads(_decode_text(data))
    except json.JSONDecodeError as exc:
        raise WeFlowParseError("invalid WeFlow JSON export") from exc


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _parse_json_payload(
    payload: Any,
    *,
    requested_format: str,
    timezone: ZoneInfo,
    conversation_id: str | None,
    source_metadata: dict[str, Any],
) -> WeFlowExport:
    if requested_format == "chatlab_json" or _looks_like_chatlab(payload):
        return _parse_chatlab_json(payload, timezone=timezone, conversation_id=conversation_id, source_metadata=source_metadata)
    return _parse_raw_json(payload, timezone=timezone, conversation_id=conversation_id, source_metadata=source_metadata)


def _looks_like_chatlab(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if "chatlab" in payload:
        return True
    messages = _messages_from_payload(payload)
    return any(isinstance(item, dict) and ("platformMessageId" in item or "sender" in item) for item in messages[:5])


def _parse_chatlab_json(
    payload: Any,
    *,
    timezone: ZoneInfo,
    conversation_id: str | None,
    source_metadata: dict[str, Any],
) -> WeFlowExport:
    if not isinstance(payload, dict):
        raise WeFlowParseError("ChatLab JSON export must be an object")
    messages = _messages_from_payload(payload)
    member_names = _member_name_map(payload.get("members"))
    raw_meta = payload.get("meta")
    meta: dict[Any, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    cid = conversation_id or _string(meta.get("groupId") or meta.get("talker") or meta.get("id") or meta.get("name"))
    turns: list[WeFlowTurn] = []
    warnings: list[str] = []
    for index, raw in enumerate(messages):
        if not isinstance(raw, dict):
            warnings.append(f"skip non-object message at index {index}")
            continue
        content = _message_content(raw)
        if not content:
            continue
        speaker_id = _string(raw.get("sender") or raw.get("senderId") or raw.get("platformId") or raw.get("from")) or "unknown"
        speaker_name = _display_name(raw, fallback=member_names.get(speaker_id) or speaker_id)
        turns.append(
            WeFlowTurn(
                message_id=_string(raw.get("platformMessageId") or raw.get("messageId") or raw.get("id")),
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                content=content,
                timestamp=_normalize_timestamp(raw.get("timestamp") or raw.get("sendTime") or raw.get("time"), timezone),
                is_self=_is_truthy(raw.get("isSelf") or raw.get("isSend")) or speaker_name.strip().lower() in _SELF_NAMES,
                message_type=_string(raw.get("type")),
                metadata=_compact_dict(
                    {
                        "accountName": raw.get("accountName"),
                        "groupNickname": raw.get("groupNickname"),
                        "avatar": raw.get("avatar"),
                    }
                ),
            )
        )
    return _build_export(
        detected_format="chatlab_json",
        conversation_id=cid,
        turns=turns,
        source_metadata=source_metadata,
        warnings=warnings,
    )


def _member_name_map(raw_members: Any) -> dict[str, str]:
    if not isinstance(raw_members, list):
        return {}
    out: dict[str, str] = {}
    for member in raw_members:
        if not isinstance(member, dict):
            continue
        member_id = _string(member.get("platformId") or member.get("id") or member.get("wxid"))
        if member_id:
            out[member_id] = _display_name(member, fallback=member_id)
    return out


def _parse_raw_json(
    payload: Any,
    *,
    timezone: ZoneInfo,
    conversation_id: str | None,
    source_metadata: dict[str, Any],
) -> WeFlowExport:
    messages = _messages_from_payload(payload)
    if not messages:
        raise WeFlowParseError("WeFlow JSON export does not contain messages")
    cid = conversation_id
    if cid is None and isinstance(payload, dict):
        cid = _string(payload.get("talker") or payload.get("talkerId") or payload.get("conversationId"))
    turns: list[WeFlowTurn] = []
    warnings: list[str] = []
    for index, raw in enumerate(messages):
        if not isinstance(raw, dict):
            warnings.append(f"skip non-object message at index {index}")
            continue
        content = _message_content(raw)
        if not content:
            continue
        is_self = _is_truthy(raw.get("isSend") or raw.get("isSelf"))
        speaker_id = _string(raw.get("senderUsername") or raw.get("sender") or raw.get("fromUser"))
        if not speaker_id:
            speaker_id = "self" if is_self else _string(cid) or "unknown"
        speaker_name = _display_name(raw, fallback=("\u6211" if is_self else speaker_id))
        turns.append(
            WeFlowTurn(
                message_id=_string(raw.get("serverId") or raw.get("platformMessageId") or raw.get("msgId") or raw.get("id")),
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                content=content,
                timestamp=_normalize_timestamp(raw.get("createTime") or raw.get("timestamp") or raw.get("sendTime"), timezone),
                is_self=is_self,
                message_type=_string(raw.get("type") or raw.get("msgType")),
                metadata=_compact_dict(
                    {
                        "localId": raw.get("localId"),
                        "talker": raw.get("talker"),
                        "accountName": raw.get("accountName"),
                    }
                ),
            )
        )
    return _build_export(
        detected_format="raw_json",
        conversation_id=cid,
        turns=turns,
        source_metadata=source_metadata,
        warnings=warnings,
    )


def _messages_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "data", "items", "records", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _messages_from_payload(value)
            if nested:
                return nested
    return []


def _parse_csv_text(
    text: str,
    *,
    timezone: ZoneInfo,
    conversation_id: str | None,
    source_metadata: dict[str, Any],
) -> WeFlowExport:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    turns: list[WeFlowTurn] = []
    for row in reader:
        normalized = {_normalize_key(key): value for key, value in row.items() if key is not None}
        content = _first(normalized, "parsedcontent", "content", "msgcontent", "text")
        if not content:
            continue
        is_self = _is_truthy(_first(normalized, "issend", "isself", "is_send"))
        speaker_id = _first(normalized, "senderusername", "sender", "fromuser", "wxid") or ("self" if is_self else "unknown")
        speaker_name = _first(normalized, "groupnickname", "accountname", "nickname", "sendername") or ("\u6211" if is_self else speaker_id)
        turns.append(
            WeFlowTurn(
                message_id=_first(normalized, "serverid", "platformmessageid", "msgid", "id", "localid"),
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                content=content.strip(),
                timestamp=_normalize_timestamp(_first(normalized, "createtime", "timestamp", "sendtime", "time"), timezone),
                is_self=is_self or speaker_name.strip().lower() in _SELF_NAMES,
                message_type=_first(normalized, "type", "msgtype"),
                metadata={},
            )
        )
    return _build_export(
        detected_format="csv",
        conversation_id=conversation_id,
        turns=turns,
        source_metadata=source_metadata,
        warnings=[],
    )


_TXT_LINE_RE = re.compile(
    r"^\s*(?:\[(?P<bracket_time>[^\]]+)\]|(?P<plain_time>\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?))\s*(?P<speaker>[^:\uff1a]+)[:\uff1a]\s*(?P<content>.*)$"
)


def _parse_txt_text(
    text: str,
    *,
    timezone: ZoneInfo,
    conversation_id: str | None,
    source_metadata: dict[str, Any],
) -> WeFlowExport:
    turns: list[WeFlowTurn] = []
    for line in text.splitlines():
        match = _TXT_LINE_RE.match(line)
        if match:
            speaker_name = match.group("speaker").strip()
            is_self = speaker_name.lower() in _SELF_NAMES
            timestamp = match.group("bracket_time") or match.group("plain_time")
            turns.append(
                WeFlowTurn(
                    message_id=None,
                    speaker_id=_speaker_id_from_name(speaker_name),
                    speaker_name=speaker_name,
                    content=match.group("content").strip(),
                    timestamp=_normalize_timestamp(timestamp, timezone),
                    is_self=is_self,
                    metadata={},
                )
            )
        elif turns and line.strip():
            previous = turns[-1]
            turns[-1] = WeFlowTurn(
                message_id=previous.message_id,
                speaker_id=previous.speaker_id,
                speaker_name=previous.speaker_name,
                content=f"{previous.content}\n{line.strip()}",
                timestamp=previous.timestamp,
                is_self=previous.is_self,
                message_type=previous.message_type,
                metadata=previous.metadata,
            )
    return _build_export(
        detected_format="txt",
        conversation_id=conversation_id,
        turns=turns,
        source_metadata=source_metadata,
        warnings=[],
    )


class _MessageHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._row: dict[str, str] | None = None
        self._field: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        classes = set(attrs_map.get("class", "").lower().split())
        if tag.lower() == "tr":
            self._row = {}
        field = None
        if "time" in classes or "timestamp" in classes or "date" in classes:
            field = "time"
        elif "sender" in classes or "speaker" in classes or "name" in classes:
            field = "sender"
        elif "content" in classes or "message" in classes or "text" in classes:
            field = "content"
        if field:
            if self._row is None:
                self._row = {}
            self._field = field
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._field:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._field and tag.lower() in {"td", "div", "span", "p"}:
            text = "".join(self._buffer).strip()
            if self._row is not None and text:
                self._row[self._field] = text
            self._field = None
            self._buffer = []
        if tag.lower() == "tr" and self._row is not None:
            if self._row.get("sender") and self._row.get("content"):
                self.rows.append(self._row)
            self._row = None
            self._field = None
            self._buffer = []


def _parse_html_text(
    text: str,
    *,
    timezone: ZoneInfo,
    conversation_id: str | None,
    source_metadata: dict[str, Any],
) -> WeFlowExport:
    parser = _MessageHtmlParser()
    parser.feed(text)
    turns: list[WeFlowTurn] = []
    for row in parser.rows:
        speaker_name = row["sender"].strip()
        is_self = speaker_name.lower() in _SELF_NAMES
        turns.append(
            WeFlowTurn(
                message_id=None,
                speaker_id=_speaker_id_from_name(speaker_name),
                speaker_name=speaker_name,
                content=row["content"].strip(),
                timestamp=_normalize_timestamp(row.get("time"), timezone),
                is_self=is_self,
                metadata={},
            )
        )
    return _build_export(
        detected_format="html",
        conversation_id=conversation_id,
        turns=turns,
        source_metadata=source_metadata,
        warnings=[],
    )


def _build_export(
    *,
    detected_format: WeFlowDetectedFormat,
    conversation_id: str | None,
    turns: list[WeFlowTurn],
    source_metadata: dict[str, Any],
    warnings: list[str],
) -> WeFlowExport:
    if not turns:
        raise WeFlowParseError("WeFlow export does not contain readable chat messages")
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    self_flags: dict[str, bool] = {}
    speaker_metadata: dict[str, dict[str, Any]] = {}
    for turn in turns:
        counts[turn.speaker_id] = counts.get(turn.speaker_id, 0) + 1
        names.setdefault(turn.speaker_id, turn.speaker_name)
        self_flags[turn.speaker_id] = self_flags.get(turn.speaker_id, False) or turn.is_self
        speaker_metadata.setdefault(turn.speaker_id, {})
        if turn.metadata:
            speaker_metadata[turn.speaker_id].update(turn.metadata)
    speakers = [
        WeFlowSpeaker(
            id=speaker_id,
            name=names[speaker_id],
            message_count=counts[speaker_id],
            is_self=self_flags.get(speaker_id, False),
            metadata=speaker_metadata.get(speaker_id, {}),
        )
        for speaker_id in sorted(counts, key=lambda item: (-counts[item], names[item]))
    ]
    return WeFlowExport(
        conversation_id=conversation_id,
        detected_format=detected_format,
        turns=turns,
        speakers=speakers,
        source_metadata=source_metadata,
        warnings=warnings,
    )


def _display_name(raw: dict[str, Any], *, fallback: str) -> str:
    return (
        _string(raw.get("groupNickname"))
        or _string(raw.get("displayName"))
        or _string(raw.get("accountName"))
        or _string(raw.get("nickname"))
        or _string(raw.get("senderName"))
        or fallback
    )


def _message_content(raw: dict[str, Any]) -> str:
    content = _string(
        raw.get("parsedContent")
        or raw.get("content")
        or raw.get("text")
        or raw.get("message")
        or raw.get("msgContent")
    )
    return content.strip() if content else ""


def _normalize_timestamp(value: Any, timezone: ZoneInfo) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        return datetime.fromtimestamp(raw, dt_timezone.utc).astimezone(timezone).isoformat(timespec="seconds")
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _normalize_timestamp(float(text), timezone)
    normalized = text.replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized[: len(datetime.now().strftime(fmt))], fmt)
            return parsed.replace(tzinfo=timezone).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:
        parsed_iso = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed_iso.tzinfo is None:
        parsed_iso = parsed_iso.replace(tzinfo=timezone)
    return parsed_iso.astimezone(timezone).isoformat(timespec="seconds")


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def _first(row: dict[str, str | None], *keys: str) -> str | None:
    for key in keys:
        value = row.get(_normalize_key(key))
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return False


def _speaker_id_from_name(name: str) -> str:
    if name.strip().lower() in _SELF_NAMES:
        return "self"
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name.strip()).strip("_") or "unknown"


def _compact_dict(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if value not in (None, "")}
