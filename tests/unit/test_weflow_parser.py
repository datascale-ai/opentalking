from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from opentalking.persona.weflow_parser import WeFlowParseError, parse_weflow_export


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_parse_chatlab_json_export(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "chatlab.json",
        {
            "chatlab": {"version": "0.0.2", "generator": "WeFlow"},
            "meta": {"name": "Project room", "platform": "wechat", "type": "group", "groupId": "room@chatroom"},
            "members": [
                {
                    "platformId": "wxid_li",
                    "accountName": "Li Si",
                    "groupNickname": "Product",
                    "avatar": "https://example.test/avatar.jpg",
                }
            ],
            "messages": [
                {
                    "sender": "wxid_li",
                    "accountName": "Li Si",
                    "groupNickname": "Product",
                    "timestamp": 1738713600,
                    "type": 0,
                    "content": "Where are we today?",
                    "platformMessageId": "12345678901234567890",
                }
            ],
        },
    )

    result = parse_weflow_export(path, timezone="Asia/Shanghai")

    assert result.detected_format == "chatlab_json"
    assert result.conversation_id == "room@chatroom"
    assert result.source_metadata["source_name"] == "chatlab.json"
    assert result.speakers[0].id == "wxid_li"
    assert result.speakers[0].name == "Product"
    assert result.turns[0].message_id == "12345678901234567890"
    assert result.turns[0].speaker_id == "wxid_li"
    assert result.turns[0].speaker_name == "Product"
    assert result.turns[0].timestamp == "2025-02-05T08:00:00+08:00"
    assert result.turns[0].content == "Where are we today?"


def test_parse_raw_weflow_json_export(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "raw.json",
        {
            "success": True,
            "talker": "wxid_friend",
            "messages": [
                {
                    "localId": 1,
                    "serverId": "6116895530414915131",
                    "createTime": 1738713600,
                    "isSend": 0,
                    "senderUsername": "wxid_friend",
                    "parsedContent": "I like your short replies.",
                    "content": "ignored when parsedContent exists",
                },
                {
                    "localId": 2,
                    "serverId": "6116895530414915132",
                    "createTime": 1738713660,
                    "isSend": 1,
                    "senderUsername": "self_wxid",
                    "content": "Noted.",
                },
            ],
        },
    )

    result = parse_weflow_export(path)

    assert result.detected_format == "raw_json"
    assert result.conversation_id == "wxid_friend"
    assert [turn.is_self for turn in result.turns] == [False, True]
    assert result.turns[0].message_id == "6116895530414915131"
    assert result.turns[0].content == "I like your short replies."
    assert result.turns[1].speaker_id == "self_wxid"


def test_parse_csv_export_preserves_long_ids(tmp_path: Path) -> None:
    path = tmp_path / "messages.csv"
    path.write_text(
        "serverId,createTime,isSend,senderUsername,accountName,content\n"
        "9223372036854775807123,2025-02-05 08:00:00,0,wxid_li,Li,morning\n",
        encoding="utf-8",
    )

    result = parse_weflow_export(path, conversation_id="wxid_li")

    assert result.detected_format == "csv"
    assert result.conversation_id == "wxid_li"
    assert result.turns[0].message_id == "9223372036854775807123"
    assert result.turns[0].speaker_name == "Li"


def test_parse_txt_export(tmp_path: Path) -> None:
    path = tmp_path / "messages.txt"
    path.write_text(
        "[2025-02-05 08:00:00] Li: morning\n"
        "[2025-02-05 08:01:00] me\uff1aI am good today\n",
        encoding="utf-8",
    )

    result = parse_weflow_export(path)

    assert result.detected_format == "txt"
    assert [turn.speaker_name for turn in result.turns] == ["Li", "me"]
    assert result.turns[0].content == "morning"
    assert result.turns[1].is_self is True


def test_parse_html_export(tmp_path: Path) -> None:
    path = tmp_path / "messages.html"
    path.write_text(
        """
<html><body><table>
  <tr class="message"><td class="time">2025-02-05 08:00:00</td><td class="sender">Li</td><td class="content">hello &amp; haha</td></tr>
</table></body></html>
""".strip(),
        encoding="utf-8",
    )

    result = parse_weflow_export(path)

    assert result.detected_format == "html"
    assert result.turns[0].speaker_name == "Li"
    assert result.turns[0].content == "hello & haha"


def test_zip_export_prefers_json_member(tmp_path: Path) -> None:
    archive = tmp_path / "weflow-export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("messages.html", "<html><body>not preferred</body></html>")
        zf.writestr(
            "nested/messages.json",
            json.dumps(
                {
                    "chatlab": {"version": "0.0.2", "generator": "WeFlow"},
                    "meta": {"name": "Friend", "platform": "wechat", "type": "private"},
                    "members": [],
                    "messages": [
                        {
                            "sender": "wxid_li",
                            "accountName": "Li",
                            "timestamp": 1738713600,
                            "type": 0,
                            "content": "zip json member",
                            "platformMessageId": "abc-1",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )

    result = parse_weflow_export(archive)

    assert result.detected_format == "chatlab_json"
    assert result.source_metadata["archive_member"] == "nested/messages.json"
    assert result.turns[0].content == "zip json member"


def test_rejects_api_url_or_unsupported_file(tmp_path: Path) -> None:
    with pytest.raises(WeFlowParseError, match="upload"):
        parse_weflow_export("http://127.0.0.1:5031/api/v1/messages?talker=wxid_xxx")

    unsupported = tmp_path / "avatar.png"
    unsupported.write_bytes(b"not a chat export")
    with pytest.raises(WeFlowParseError, match="unsupported"):
        parse_weflow_export(unsupported)
