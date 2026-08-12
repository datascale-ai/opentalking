"""Small, transport-independent SDP checks for the WHIP v1 publisher."""

from __future__ import annotations

import ipaddress
import re


class WhipSdpError(ValueError):
    """Raised when an offer/answer cannot be used for the fixed WHIP profile."""


_CANDIDATE_ADDRESS = re.compile(r"^a=candidate:\S+\s+\d+\s+\S+\s+\d+\s+(\S+)\s+\d+\s+typ\s+(\S+)")


def _media_sections(sdp: str) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] | None = None
    for raw in sdp.splitlines():
        line = raw.strip()
        if line.startswith("m="):
            current = [line]
            sections.append(current)
        elif current is not None and line:
            current.append(line)
    return sections


def _require_common(sdp: str, *, role: str) -> list[list[str]]:
    if not sdp.strip() or not sdp.lstrip().startswith("v=0"):
        raise WhipSdpError(f"WHIP {role} SDP is empty or missing v=0")
    if not any(line.startswith("a=group:BUNDLE ") for line in sdp.splitlines()):
        raise WhipSdpError(f"WHIP {role} SDP is missing BUNDLE")
    sections = _media_sections(sdp)
    if len(sections) != 2 or [item[0].split()[0][2:] for item in sections] != ["video", "audio"]:
        raise WhipSdpError("WHIP SDP must contain exactly video then audio m-lines")
    for section in sections:
        if "a=rtcp-mux" not in section:
            raise WhipSdpError("WHIP SDP requires rtcp-mux on every media section")
        if not any(line.startswith("a=ice-ufrag:") for line in section):
            raise WhipSdpError(f"WHIP {role} SDP is missing ICE username fragment")
        if not any(line.startswith("a=ice-pwd:") for line in section):
            raise WhipSdpError(f"WHIP {role} SDP is missing ICE password")
    return sections


def validate_offer_sdp(
    sdp: str,
    *,
    allow_private_candidates: bool = False,
    candidate_policy: str = "allowlist",
    allowed_cidrs: tuple[str, ...] | list[str] = (),
) -> None:
    sections = _require_common(sdp, role="offer")
    for section in sections:
        if "a=sendonly" not in section:
            raise WhipSdpError("WHIP offer tracks must be sendonly")
    video, audio = sections
    if not any("H264/90000" in line for line in video):
        raise WhipSdpError("WHIP offer must advertise H264")
    if not any("opus/48000" in line.lower() for line in audio):
        raise WhipSdpError("WHIP offer must advertise Opus")
    candidates = [line for line in sdp.splitlines() if line.startswith("a=candidate:")]
    if not candidates:
        raise WhipSdpError("WHIP offer must use full ICE and include candidates")
    policy = candidate_policy.strip().lower() or "allowlist"
    if policy not in {"allowlist", "relay"}:
        raise WhipSdpError("unsupported WHIP candidate policy")
    networks = [ipaddress.ip_network(item, strict=False) for item in allowed_cidrs]
    if allow_private_candidates and policy == "allowlist":
        return
    for line in candidates:
        match = _CANDIDATE_ADDRESS.match(line)
        if not match:
            continue
        candidate_type = match.group(2).lower()
        if policy == "relay" and candidate_type != "relay":
            raise WhipSdpError("WHIP relay candidate policy rejected non-relay candidate")
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            continue
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            if not any(address in network for network in networks):
                raise WhipSdpError("WHIP offer contains a private host candidate; configure approved relay/egress")


def validate_answer_sdp(offer_sdp: str, answer_sdp: str) -> None:
    offer = _require_common(offer_sdp, role="offer")
    answer = _require_common(answer_sdp, role="answer")
    if len(offer) != len(answer):  # defensive; _require_common currently fixes both at two
        raise WhipSdpError("WHIP answer media sections do not match offer")
    for offer_section, answer_section in zip(offer, answer, strict=True):
        if "a=recvonly" not in answer_section and "a=inactive" not in answer_section:
            raise WhipSdpError("WHIP answer must be recvonly or inactive")
        if offer_section[0].split()[0] != answer_section[0].split()[0]:
            raise WhipSdpError("WHIP answer m-line order does not match offer")
    if not any("H264/90000" in line for line in answer[0]):
        raise WhipSdpError("WHIP answer did not negotiate H264")
    if not any("opus/48000" in line.lower() for line in answer[1]):
        raise WhipSdpError("WHIP answer did not negotiate Opus")
