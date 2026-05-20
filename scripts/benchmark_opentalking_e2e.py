from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import platform
import re
import shutil
import shlex
import signal
import subprocess
import sys
import tarfile
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.request import Request, urlopen

import yaml


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_shell(cmd: str, *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-lc", cmd], cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"benchmark config must be a mapping: {path}")
    return data


def resolve_path(value: str, repo: Path) -> str:
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str((repo / path).resolve())


E2E_TECHNICAL_ROUTE_BY_MODEL = {
    "wav2lip": "mouth inpainting",
    "musetalk": "mouth inpainting",
    "quicktalk": "mouth inpainting",
}


def technical_route_for_model(model: str, model_cfg: dict[str, Any], cfg: dict[str, Any]) -> str:
    normalized = model.strip().lower()
    return E2E_TECHNICAL_ROUTE_BY_MODEL.get(normalized) or str(model_cfg.get("technical_route") or cfg.get("technical_route") or "")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    items = sorted(values)
    pos = (len(items) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return items[lo]
    return items[lo] * (hi - pos) + items[hi] * (pos - lo)


def http_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upload_reference(api_base_url: str, avatar_id: str, image_path: Path, timeout: float = 30.0) -> dict[str, Any]:
    boundary = f"----opentalking-benchmark-{int(time.time() * 1000)}"
    image = image_path.read_bytes()
    filename = image_path.name
    parts = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="avatar_id"\r\n\r\n',
        avatar_id.encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="reference_image"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: image/png\r\n\r\n",
        image,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urlrequest.Request(
        api_base_url.rstrip("/") + "/sessions/customize/reference",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_health(api_base_url: str, timeout: float = 180.0) -> None:
    deadline = time.perf_counter() + timeout
    last: Exception | None = None
    while time.perf_counter() < deadline:
        try:
            http_json(api_base_url.rstrip("/") + "/health", timeout=5.0)
            return
        except Exception as exc:
            last = exc
            time.sleep(1.0)
    raise TimeoutError(f"OpenTalking health not ready: {last}")


def wait_for_model(api_base_url: str, model: str, backend: str, timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout
    last: Any = None
    while time.perf_counter() < deadline:
        try:
            data = http_json(api_base_url.rstrip("/") + "/models", timeout=10.0)
            last = data
            for item in data.get("statuses", data if isinstance(data, list) else []):
                if item.get("id") == model:
                    if item.get("connected") and item.get("backend") == backend and backend != "mock":
                        return item
        except Exception as exc:
            last = exc
        time.sleep(1.0)
    raise TimeoutError(f"model {model}/{backend} not connected at /models; last={last}")


def gpu_info(index: int) -> dict[str, Any]:
    cp = run(["nvidia-smi", f"--id={index}", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"])
    if cp.returncode or not cp.stdout.strip():
        return {"index": index, "error": cp.stderr.strip()}
    parts = [p.strip() for p in cp.stdout.strip().splitlines()[0].split(",")]
    return {"index": index, "name": parts[0], "memory_total_gb": round(float(parts[1]) / 1024.0, 3), "driver": parts[2]}


def gpu_device_mem_gb(index: int) -> float | None:
    cp = run(["nvidia-smi", f"--id={index}", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    if cp.returncode or not cp.stdout.strip():
        return None
    return round(float(cp.stdout.strip().splitlines()[0]) / 1024.0, 3)


def gpu_process_mem_gb(pids: list[int], gpu_index: int | None = None) -> float | None:
    if not pids:
        return None
    records = gpu_process_mem_records(pids, gpu_index=gpu_index)
    if records is None:
        return None
    return round(sum(float(item["used_memory_mb"]) for item in records) / 1024.0, 3)


def retry_gpu_process_mem_gb(
    pids: list[int],
    *,
    gpu_index: int | None = None,
    attempts: int = 10,
    interval: float = 0.3,
) -> float | None:
    for _ in range(max(1, attempts)):
        value = gpu_process_mem_gb(pids, gpu_index=gpu_index)
        if value is not None:
            return value
        time.sleep(interval)
    return None


def pids_for_ports(ports: list[int]) -> list[int]:
    pids: set[int] = set()
    for port in ports:
        cp = run_shell(f"ss -ltnp '( sport = :{int(port)} )' 2>/dev/null")
        for pid in re.findall(r"pid=(\d+)", cp.stdout):
            pids.add(int(pid))
    return sorted(pids)


def proc_tree(root_pid: int) -> list[int]:
    pids = {root_pid}
    children: dict[int, list[int]] = {}
    proc_root = Path("/proc")
    if not proc_root.exists():
        return [root_pid]
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            parts = (proc / "stat").read_text().split()
            children.setdefault(int(parts[3]), []).append(int(parts[0]))
        except Exception:
            continue
    queue = [root_pid]
    while queue:
        pid = queue.pop()
        for child in children.get(pid, []):
            if child not in pids:
                pids.add(child)
                queue.append(child)
    return sorted(pids)


def read_pid_file(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            return None
        pid = int(value.split()[0])
    except Exception:
        return None
    return pid if Path(f"/proc/{pid}").exists() else None


def resolve_pid_file(path: str, repo: Path) -> Path:
    value = Path(path).expanduser()
    if value.is_absolute():
        return value
    if str(value).startswith("run/"):
        return repo.parent / value
    return (repo / value).resolve()


def default_model_pid_files(model: str, backend: str, repo: Path) -> list[Path]:
    run_dir = repo.parent / "run"
    if backend != "omnirt":
        return []
    mapping = {
        "wav2lip": ["omnirt-wav2lip.pid"],
        "quicktalk": ["omnirt-quicktalk.pid"],
        "musetalk": ["omnirt-musetalk.pid", "omnirt-musetalk-ws.pid"],
        "flashtalk": ["omnirt-flashtalk.pid"],
    }
    return [run_dir / name for name in mapping.get(model, [f"omnirt-{model}.pid"])]


def collect_related_pids(repo: Path, cfg: dict[str, Any], model: str, backend: str, model_cfg: dict[str, Any], ports: list[int]) -> dict[str, Any]:
    run_dir = repo.parent / "run"
    api_port = int(cfg.get("api_port", 8010))
    web_port = int(cfg.get("web_port", 5184))
    pid_files: list[Path] = [run_dir / f"opentalking-api-{api_port}.pid", run_dir / f"opentalking-web-{web_port}.pid"]
    pid_files.extend(default_model_pid_files(model, backend, repo))
    configured = model_cfg.get("pid_files")
    if isinstance(configured, list):
        pid_files.extend(resolve_pid_file(str(item), repo) for item in configured)

    root_pids: dict[int, str] = {}
    pid_file_map: dict[str, int | None] = {}
    for pid_file in pid_files:
        pid = read_pid_file(pid_file)
        pid_file_map[str(pid_file)] = pid
        if pid is not None:
            root_pids[pid] = str(pid_file)

    for pid in pids_for_ports(ports):
        root_pids.setdefault(pid, "port-listener")

    related: set[int] = set()
    for pid in root_pids:
        related.update(proc_tree(pid))
    return {"pids": sorted(related), "root_pids": dict(sorted(root_pids.items())), "pid_files": pid_file_map}


def gpu_process_mem_records(pids: list[int], gpu_index: int | None = None) -> list[dict[str, Any]] | None:
    if not pids:
        return None
    wanted = {int(pid) for pid in pids}
    query = "gpu_uuid,pid,process_name,used_memory"
    cp = run(["nvidia-smi", f"--query-compute-apps={query}", "--format=csv,noheader,nounits"])
    if cp.returncode:
        return None
    uuid_by_index: dict[int, str] = {}
    if gpu_index is not None:
        gpu_cp = run(["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits"])
        for line in gpu_cp.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 2:
                try:
                    uuid_by_index[int(parts[0])] = parts[1]
                except ValueError:
                    continue
    target_uuid = uuid_by_index.get(gpu_index) if gpu_index is not None else None
    records: list[dict[str, Any]] = []
    for line in cp.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[1])
            used_mb = float(parts[3])
        except ValueError:
            continue
        if pid not in wanted:
            continue
        if target_uuid is not None and parts[0] != target_uuid:
            continue
        records.append({
            "gpu_uuid": parts[0],
            "pid": pid,
            "process_name": parts[2],
            "used_memory_mb": used_mb,
            "used_memory_gb": round(used_mb / 1024.0, 3),
        })
    return records


def rss_gb_for_pids(pids: list[int]) -> float | None:
    total = 0
    seen = False
    for pid in pids:
        status = Path(f"/proc/{pid}/status")
        if not status.exists():
            continue
        seen = True
        try:
            for line in status.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    break
        except Exception:
            continue
    return round(total / 1024.0 / 1024.0, 3) if seen else None


class ResourceSampler:
    def __init__(
        self,
        *,
        gpu_index: int,
        pids: list[int] | None = None,
        pid_provider: Any | None = None,
        interval: float = 0.2,
    ) -> None:
        self.gpu_index = gpu_index
        self.pids = pids or []
        self.pid_provider = pid_provider
        self.interval = interval
        self.max_device_vram_gb: float | None = None
        self.max_process_vram_gb: float | None = None
        self.max_cpu_gb: float | None = None
        self.max_process_vram_pids: list[int] = []
        self.latest_pids: list[int] = list(self.pids)
        self._stop = asyncio.Event()

    def current_pids(self) -> list[int]:
        if self.pid_provider is None:
            return list(self.pids)
        try:
            pids = list(self.pid_provider())
        except Exception:
            pids = list(self.pids)
        if pids:
            self.latest_pids = sorted({int(pid) for pid in pids})
            return self.latest_pids
        return list(self.latest_pids)

    async def sample(self) -> None:
        while not self._stop.is_set():
            pids = self.current_pids()
            dev = gpu_device_mem_gb(self.gpu_index)
            proc = gpu_process_mem_gb(pids, gpu_index=self.gpu_index)
            cpu = rss_gb_for_pids(pids)
            if dev is not None:
                self.max_device_vram_gb = dev if self.max_device_vram_gb is None else max(self.max_device_vram_gb, dev)
            if proc is not None and (self.max_process_vram_gb is None or proc > self.max_process_vram_gb):
                self.max_process_vram_gb = proc
                self.max_process_vram_pids = list(pids)
            if cpu is not None:
                self.max_cpu_gb = cpu if self.max_cpu_gb is None else max(self.max_cpu_gb, cpu)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()


async def sse_events(api_base_url: str, session_id: str, sink: list[dict[str, Any]], stop: asyncio.Event) -> None:
    import httpx

    url = api_base_url.rstrip("/") + f"/sessions/{session_id}/events"
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            event = "message"
            data_lines: list[str] = []
            async for line in resp.aiter_lines():
                if stop.is_set():
                    return
                if line == "":
                    if data_lines:
                        try:
                            sink.append({"event": event, "data": json.loads("\n".join(data_lines)), "received_unix": time.time()})
                        except Exception:
                            sink.append({"event": event, "data": "\n".join(data_lines), "received_unix": time.time()})
                    event = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())


async def setup_webrtc(api_base_url: str, session_id: str, first_video: asyncio.Event, first_video_time: dict[str, float], video_frames: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaRelay

    pc = RTCPeerConnection()
    relay = MediaRelay()
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    track_state: dict[str, Any] = {
        "relay": relay,
        "source_tracks": {},
        "record_tracks": {},
        "audio_ready": asyncio.Event(),
        "video_ready": asyncio.Event(),
    }

    @pc.on("track")
    def on_track(track: Any) -> None:
        track_state["source_tracks"][track.kind] = track
        track_state["record_tracks"][track.kind] = relay.subscribe(track, buffered=False)
        if track.kind == "audio" and not track_state["audio_ready"].is_set():
            track_state["audio_ready"].set()
        if track.kind == "video" and not track_state["video_ready"].is_set():
            track_state["video_ready"].set()
        if track.kind != "video":
            return
        observer_track = relay.subscribe(track)

        async def recv_loop() -> None:
            while True:
                try:
                    frame = await observer_track.recv()
                except Exception:
                    return
                video_frames["count"] = video_frames.get("count", 0) + 1
                capture = video_frames.get("capture")
                frames = video_frames.setdefault("frames", [])
                if capture and len(frames) < int(video_frames.get("max_frames", 250)):
                    try:
                        frames.append(frame.to_ndarray(format="bgr24"))
                    except Exception:
                        pass
                if "first_frame" not in video_frames:
                    try:
                        video_frames["first_frame"] = frame.to_ndarray(format="bgr24")
                    except Exception:
                        pass
                if not first_video.is_set():
                    first_video_time["unix"] = time.time()
                    first_video.set()

        asyncio.create_task(recv_loop())

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    answer = http_json(
        api_base_url.rstrip("/") + f"/sessions/{session_id}/webrtc/offer",
        method="POST",
        payload={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        timeout=30.0,
    )
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    return pc, track_state


def write_video_sample(path: Path, frames: list[Any], fps: float = 25.0) -> bool:
    if not frames:
        return False
    try:
        import cv2
        import numpy as np

        frame = np.asarray(frames[0])
        height, width = frame.shape[:2]
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (width, height))
        if not writer.isOpened():
            return False
        for item in frames:
            writer.write(np.asarray(item))
        writer.release()
        return True
    except Exception:
        return False


def mux_audio_into_video(video_path: Path, audio_path: Path) -> bool:
    if not video_path.exists() or not audio_path.exists() or audio_path.stat().st_size == 0:
        return False
    tmp_path = video_path.with_name(video_path.stem + ".with_audio.mp4")
    cp = run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(tmp_path),
    ])
    if cp.returncode:
        return False
    tmp_path.replace(video_path)
    return True


def media_file_has_streams(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    cp = run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ])
    if cp.returncode:
        return False
    streams = {line.strip() for line in cp.stdout.splitlines() if line.strip()}
    return "audio" in streams and "video" in streams


def probe_media_streams(path: Path) -> dict[str, dict[str, float]]:
    cp = run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,start_time,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ])
    if cp.returncode:
        raise RuntimeError(f"ffprobe failed for {path}: {cp.stderr.strip()}")
    data = json.loads(cp.stdout or "{}")
    format_duration = float((data.get("format") or {}).get("duration") or 0.0)
    streams: dict[str, dict[str, float]] = {}
    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind not in {"audio", "video"} or kind in streams:
            continue
        start = float(stream.get("start_time") or 0.0)
        duration = float(stream.get("duration") or format_duration or 0.0)
        streams[kind] = {"start": start, "duration": duration}
    return streams


def normalize_webrtc_sample(path: Path) -> bool:
    if not media_file_has_streams(path):
        return False
    streams = probe_media_streams(path)
    audio = streams.get("audio")
    video = streams.get("video")
    if not audio or not video:
        return False
    common_start = max(audio["start"], video["start"])
    common_end = min(audio["start"] + audio["duration"], video["start"] + video["duration"])
    duration = common_end - common_start
    if duration <= 0.25:
        return False

    raw_path = path.with_name(path.stem + ".raw" + path.suffix)
    tmp_path = path.with_name(path.stem + ".normalized" + path.suffix)
    path.replace(raw_path)
    video_offset = max(0.0, common_start - video["start"])
    audio_offset = max(0.0, common_start - audio["start"])
    cp = run([
        "ffmpeg",
        "-y",
        "-i",
        str(raw_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-filter:v",
        f"trim=start={video_offset:.6f}:duration={duration:.6f},setpts=PTS-STARTPTS",
        "-filter:a",
        f"atrim=start={audio_offset:.6f}:duration={duration:.6f},asetpts=PTS-STARTPTS",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(tmp_path),
    ])
    if cp.returncode:
        raw_path.replace(path)
        tmp_path.unlink(missing_ok=True)
        return False
    tmp_path.replace(path)
    return media_file_has_streams(path)


def prepare_benchmark_avatar(repo: Path, base_avatar_id: str, *, model: str, timestamp: str) -> tuple[str, Path]:
    avatars_root = repo / "examples" / "avatars"
    base_dir = (avatars_root / base_avatar_id).resolve()
    try:
        base_dir.relative_to(avatars_root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"invalid base avatar id: {base_avatar_id}") from exc
    if not base_dir.is_dir() or not (base_dir / "manifest.json").is_file():
        raise RuntimeError(f"base avatar not found: {base_avatar_id}")
    safe_model = re.sub(r"[^A-Za-z0-9_-]+", "-", model).strip("-") or "model"
    avatar_id = f"benchmark-{timestamp}-{safe_model}"
    target_dir = avatars_root / avatar_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(base_dir, target_dir, ignore=shutil.ignore_patterns("reference_custom.*"))
    manifest_path = target_dir / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = dict(raw.get("metadata") or {})
    metadata["base_avatar_id"] = raw.get("id") or base_avatar_id
    raw["id"] = avatar_id
    raw["name"] = f"Benchmark {base_avatar_id} {safe_model}"
    raw["metadata"] = metadata
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return avatar_id, target_dir


def load_audio_duration(path: Path, target_path: Path, seconds: float) -> float:
    cp = run(["ffmpeg", "-y", "-i", str(path), "-t", str(seconds), "-ac", "1", "-ar", "16000", "-f", "wav", str(target_path)])
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip())
    with wave.open(str(target_path), "rb") as handle:
        return round(handle.getnframes() / float(handle.getframerate()), 3)


def omnirt_port_from_config(model_cfg: dict[str, Any], cfg: dict[str, Any]) -> int:
    url = str(model_cfg.get("omnirt") or cfg.get("omnirt") or "")
    if not url:
        raise RuntimeError("backend=omnirt requires an omnirt URL in model config")
    try:
        return int(url.rstrip("/").rsplit(":", 1)[1])
    except Exception as exc:
        raise RuntimeError(f"cannot parse OmniRT port from URL: {url}") from exc


def stop_pid(pid: int, timeout: float = 20.0) -> None:
    targets = list(reversed(proc_tree(pid)))
    for item in targets:
        try:
            os.kill(item, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if not any(Path(f"/proc/{item}").exists() for item in targets):
            return
        time.sleep(0.2)
    for item in targets:
        try:
            os.kill(item, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass


def stop_pid_files(pid_files: list[Path]) -> None:
    for pid_file in pid_files:
        pid = read_pid_file(pid_file)
        if pid is not None:
            stop_pid(pid)
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass


def omnirt_extra_ports(model: str, model_cfg: dict[str, Any], port: int) -> list[int]:
    ports = [port]
    if model == "musetalk":
        ports.append(int(model_cfg.get("musetalk_port", 8766)))
    return ports


def stop_omnirt_model(repo: Path, cfg: dict[str, Any], model: str, backend: str, model_cfg: dict[str, Any]) -> None:
    if backend != "omnirt":
        return
    port = omnirt_port_from_config(model_cfg, cfg)
    pid_files = default_model_pid_files(model, backend, repo)
    configured = model_cfg.get("pid_files")
    if isinstance(configured, list):
        pid_files.extend(resolve_pid_file(str(item), repo) for item in configured)
    stop_pid_files(pid_files)
    for pid in pids_for_ports(omnirt_extra_ports(model, model_cfg, port)):
        stop_pid(pid)


def start_omnirt_model(repo: Path, cfg: dict[str, Any], model: str, backend: str, model_cfg: dict[str, Any], gpu_index: int, out_dir: Path) -> None:
    if backend != "omnirt":
        return
    port = omnirt_port_from_config(model_cfg, cfg)
    env = os.environ.copy()
    home = str(Path.home())
    repo_parent = str(repo.parent)
    env["PATH"] = f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
    env["DIGITAL_HUMAN_HOME"] = repo_parent
    env["OMNIRT_PORT"] = str(port)
    env["OMNIRT_HOST"] = "0.0.0.0"
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    env["TMPDIR"] = str(repo.parent / "tmp")
    env["PIP_CACHE_DIR"] = env.get("PIP_CACHE_DIR", f"{home}/.cache/pip")
    env["UV_CACHE_DIR"] = env.get("UV_CACHE_DIR", f"{home}/.cache/uv")
    env.setdefault("UV_DEFAULT_INDEX", "https://pypi.tuna.tsinghua.edu.cn/simple")
    env.setdefault("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    if model == "wav2lip":
        env["OMNIRT_MODEL_ROOT"] = str(repo.parent / "models")
        cmd = ["bash", "scripts/quickstart/start_omnirt_wav2lip.sh", "--device", "cuda", "--port", str(port), "--skip-install"]
    elif model == "musetalk":
        env["OMNIRT_MODEL_ROOT"] = str(repo.parent / "models")
        musetalk_port = str(model_cfg.get("musetalk_port", 8766))
        env["OMNIRT_MUSETALK_PORT"] = musetalk_port
        cmd = ["bash", "scripts/quickstart/start_omnirt_musetalk.sh", "--device", "cuda", "--port", str(port), "--musetalk-port", musetalk_port, "--skip-install"]
    elif model == "quicktalk":
        quicktalk_root = repo / "models" / "quicktalk" / "checkpoints"
        env["OMNIRT_MODEL_ROOT"] = str(repo / "models")
        env["OMNIRT_QUICKTALK_MODEL_ROOT"] = str(quicktalk_root)
        env["OMNIRT_QUICKTALK_CHECKPOINT"] = str(quicktalk_root / "quicktalk.pth")
        cmd = ["bash", "scripts/quickstart/start_omnirt_quicktalk.sh", "--device", "cuda:0", "--port", str(port), "--skip-install"]
    else:
        raise RuntimeError(f"unsupported benchmark-managed OmniRT model: {model}")

    original_env = repo / "scripts" / "quickstart" / "env"
    benchmark_env = out_dir / "logs" / "benchmark-quickstart.env"
    override_keys = [
        "DIGITAL_HUMAN_HOME",
        "OMNIRT_MODEL_ROOT",
        "OMNIRT_PORT",
        "OMNIRT_HOST",
        "CUDA_VISIBLE_DEVICES",
        "TMPDIR",
        "PIP_CACHE_DIR",
        "UV_CACHE_DIR",
        "UV_DEFAULT_INDEX",
        "PIP_INDEX_URL",
        "OMNIRT_MUSETALK_PORT",
        "OMNIRT_QUICKTALK_MODEL_ROOT",
        "OMNIRT_QUICKTALK_CHECKPOINT",
    ]
    lines = ["# Generated by benchmark_opentalking_e2e.py; do not edit."]
    if original_env.exists():
        lines.append(f"source {shlex.quote(str(original_env))}")
    for key in override_keys:
        if key in env:
            lines.append(f"export {key}={shlex.quote(str(env[key]))}")
    benchmark_env.parent.mkdir(parents=True, exist_ok=True)
    benchmark_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["OPENTALKING_QUICKSTART_ENV"] = str(benchmark_env)

    log_path = out_dir / "logs" / "start-omnirt.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as handle:
        cp = subprocess.run(cmd, cwd=repo, env=env, stdout=handle, stderr=subprocess.STDOUT)
    if cp.returncode:
        raise RuntimeError(f"failed to start OmniRT {model}; see {log_path}")


def start_opentalking(repo: Path, cfg: dict[str, Any], model: str, backend: str, model_cfg: dict[str, Any], out_dir: Path) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["OPENTALKING_BENCHMARK_TIMING"] = "1"
    env["OPENTALKING_TTS_PROVIDER"] = str(cfg.get("tts_provider") or "edge")
    if cfg.get("tts_voice"):
        env["OPENTALKING_TTS_VOICE"] = str(cfg["tts_voice"])
    if cfg.get("tts_model"):
        env["OPENTALKING_QWEN_TTS_MODEL"] = str(cfg["tts_model"])
    cmd = [
        "bash",
        "scripts/start_unified.sh",
        "--backend",
        backend,
        "--model",
        model,
        "--api-port",
        str(cfg.get("api_port", 8010)),
        "--web-port",
        str(cfg.get("web_port", 5184)),
        "--host",
        str(cfg.get("host", "0.0.0.0")),
    ]
    if backend == "omnirt":
        omnirt = str(model_cfg.get("omnirt") or cfg.get("omnirt") or "")
        if not omnirt:
            raise RuntimeError("backend=omnirt requires model omnirt URL")
        cmd.extend(["--omnirt", omnirt])
    log_path = out_dir / "logs" / "start-opentalking.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    return subprocess.Popen(cmd, cwd=repo, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)


def stop_opentalking(repo: Path, cfg: dict[str, Any]) -> None:
    api_port = int(cfg.get("api_port", 8010))
    web_port = int(cfg.get("web_port", 5184))
    script = f"""
set +e
repo_root={str(repo)!r}
home_dir="$(cd "$repo_root/.." && pwd)"
run_dir="$home_dir/run"
stop_pid_file() {{
  pid_file="$1"
  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file" 2>/dev/null)"
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      for _ in $(seq 1 20); do
        kill -0 "$pid" >/dev/null 2>&1 || break
        sleep 0.5
      done
      kill -0 "$pid" >/dev/null 2>&1 && kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$pid_file"
  fi
}}
stop_pid_file "$run_dir/opentalking-api-{api_port}.pid"
stop_pid_file "$run_dir/opentalking-web-{web_port}.pid"
for pid in $(pgrep -f "$repo_root/.venv/bin/.*opentalking-unified" || true); do
  [ "$pid" = "$$" ] && continue
  if tr '\\0' '\\n' < "/proc/$pid/environ" 2>/dev/null | grep -qx "OPENTALKING_UNIFIED_PORT={api_port}"; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
done
for pid in $(pgrep -f "$repo_root/apps/web/node_modules/.bin/vite .*--port {web_port}" || true); do
  [ "$pid" = "$$" ] && continue
  kill "$pid" >/dev/null 2>&1 || true
done
"""
    run_shell(script, cwd=repo)


def write_csv(path: Path, row: dict[str, Any]) -> None:
    keys = [
        "测试日期", "测试人", "模型", "技术路线", "backend", "硬件", "OS", "驱动环境", "commit",
        "输入类型", "输出分辨率", "输出 FPS", "chunk size", "冷启动时间", "预热时间", "TTFA",
        "TTFV", "首轮总延迟", "稳态 FPS", "RTF", "idle 显存", "推理峰值显存",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerow({key: row.get(key, "not_measured") for key in keys})


async def run_once(args: argparse.Namespace) -> None:
    repo = Path(args.repo_root).resolve()
    cfg = read_yaml(Path(args.config).resolve() if Path(args.config).is_absolute() else repo / args.config)
    model = args.model or str(cfg.get("model"))
    backend = args.backend or str(cfg.get("backend"))
    if not args.tester and not cfg.get("tester"):
        raise SystemExit("--tester or tester in config is required")
    tester = args.tester or str(cfg["tester"])
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    model_cfg = dict(models.get(model, {}))
    gpu_index = int(args.gpu_index if args.gpu_index is not None else model_cfg.get("gpu", cfg.get("gpu_index", 0)))
    model_cfg.setdefault("backend", backend)
    backend = str(model_cfg.get("backend") or backend)
    api_base_url = str(args.api_base_url or cfg.get("api_base_url") or f"http://127.0.0.1:{cfg.get('api_port', 8010)}")
    hardware = gpu_info(gpu_index)
    label = re.sub(r"[^A-Za-z0-9]+", "_", str(hardware.get("name", "unknown_gpu"))).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else repo / "outputs" / "benchmarks" / "opentalking-e2e" / f"{timestamp}-{label}-{model}-{backend}"
    for sub in ("logs", "raw", "samples"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    input_cfg = cfg.get("input") if isinstance(cfg.get("input"), dict) else {}
    audio_src = Path(resolve_path(str(input_cfg.get("audio_path", "configs/benchmark/input/ttsmaker-file.mp3")), repo))
    ref_src = Path(resolve_path(str(input_cfg.get("ref_image", "configs/benchmark/input/reference.png")), repo))
    shutil.copy2(ref_src, out_dir / "input_reference.png")
    audio_duration = load_audio_duration(audio_src, out_dir / "input_audio.wav", float(input_cfg.get("audio_duration_seconds", 7.0)))

    stop_opentalking(repo, cfg)
    omnirt_started_by_benchmark = False
    if backend == "omnirt" and not args.reuse_omnirt:
        stop_omnirt_model(repo, cfg, model, backend, model_cfg)
    cold_start0 = time.perf_counter()
    if backend == "omnirt" and not args.reuse_omnirt:
        start_omnirt_model(repo, cfg, model, backend, model_cfg, gpu_index, out_dir)
        omnirt_started_by_benchmark = True
    process = start_opentalking(repo, cfg, model, backend, model_cfg, out_dir)
    try:
        wait_for_health(api_base_url, timeout=float(args.timeout))
        model_status = wait_for_model(api_base_url, model, backend, timeout=float(args.timeout))
        cold_start = time.perf_counter() - cold_start0
        ports = [int(cfg.get("api_port", 8010))]
        if backend == "omnirt" and model_cfg.get("omnirt"):
            try:
                ports.append(int(str(model_cfg["omnirt"]).rstrip("/").rsplit(":", 1)[1]))
            except Exception:
                pass
        pid_info = collect_related_pids(repo, cfg, model, backend, model_cfg, ports)
        pids = pid_info["pids"]

        def current_related_pids() -> list[int]:
            return collect_related_pids(repo, cfg, model, backend, model_cfg, ports)["pids"]

        service_ready_device_vram = gpu_device_mem_gb(gpu_index)
        service_ready_proc_vram = retry_gpu_process_mem_gb(pids, gpu_index=gpu_index)


        base_avatar_id = str(args.avatar_id or cfg.get("avatar_id", "office-woman"))
        avatar_id, benchmark_avatar_dir = prepare_benchmark_avatar(repo, base_avatar_id, model=model, timestamp=timestamp)
        try:
            upload_reference(api_base_url, avatar_id, ref_src)
        except Exception as exc:
            raise RuntimeError(f"failed to upload benchmark reference image: {exc}") from exc
        create_payload = {
            "avatar_id": avatar_id,
            "model": model,
            "tts_provider": cfg.get("tts_provider"),
            "tts_voice": cfg.get("tts_voice"),
        }
        session = http_json(api_base_url.rstrip("/") + "/sessions", method="POST", payload={k: v for k, v in create_payload.items() if v}, timeout=60.0)
        session_id = session["session_id"]
        events: list[dict[str, Any]] = []
        stop_sse = asyncio.Event()
        sse_task = asyncio.create_task(sse_events(api_base_url, session_id, events, stop_sse))
        await asyncio.sleep(0.5)
        first_video = asyncio.Event()
        first_video_time: dict[str, float] = {}
        video_frames: dict[str, Any] = {"capture": False, "max_frames": 250, "frames": []}
        pc, track_state = await setup_webrtc(api_base_url, session_id, first_video, first_video_time, video_frames)

        warm_start = time.perf_counter()
        speak_common = {
            "tts_provider": cfg.get("tts_provider"),
            "voice": cfg.get("tts_voice"),
            "tts_model": cfg.get("tts_model") or None,
        }
        warm_payload = {"text": str(cfg.get("warmup_prompt", "你好，这是预热测试。")), **speak_common}
        http_json(api_base_url.rstrip("/") + f"/sessions/{session_id}/speak", method="POST", payload={k: v for k, v in warm_payload.items() if v}, timeout=30.0)
        warm_deadline = time.perf_counter() + float(args.timeout)
        while time.perf_counter() < warm_deadline and not any(e["event"] == "speech.timing" for e in events):
            await asyncio.sleep(0.2)
        warmup_seconds = time.perf_counter() - warm_start
        post_warmup_pids = current_related_pids()
        idle_device_vram = gpu_device_mem_gb(gpu_index)
        idle_proc_vram = retry_gpu_process_mem_gb(post_warmup_pids, gpu_index=gpu_index)
        idle_vram_measured = idle_proc_vram is not None
        events.clear()
        first_video.clear()
        first_video_time.clear()
        video_frames["count"] = 0
        video_frames["frames"] = []
        video_frames.pop("first_frame", None)
        video_frames["capture"] = True

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    track_state["video_ready"].wait(),
                    track_state["audio_ready"].wait(),
                ),
                timeout=10.0,
            )
        except Exception:
            pass
        record_tracks = track_state["record_tracks"]
        video_track = record_tracks.get("video")
        audio_track = record_tracks.get("audio")

        sampler = ResourceSampler(gpu_index=gpu_index, pids=post_warmup_pids, pid_provider=current_related_pids)
        sampler_task = asyncio.create_task(sampler.sample())
        request_unix = time.time()
        speak_payload = {"text": str(cfg.get("prompt", "OpenTalking benchmark fixed input")), **speak_common}
        http_json(api_base_url.rstrip("/") + f"/sessions/{session_id}/speak", method="POST", payload={k: v for k, v in speak_payload.items() if v}, timeout=30.0)
        try:
            await asyncio.wait_for(first_video.wait(), timeout=float(args.timeout))
        except asyncio.TimeoutError as exc:
            raise TimeoutError("first WebRTC video frame was not received") from exc

        sample_path: Path | None = None
        sample_written = False
        video_mock_path = out_dir / "samples" / "video_output_mocked.txt"
        video_mock_path.write_text(
            "\n".join(
                [
                    "E2E sample video output is intentionally mocked/disabled.",
                    "The benchmark still observes the OpenTalking WebRTC video track for first-frame and timing metrics.",
                    "A recorded MP4 is not equivalent to the browser's real-time WebRTC playback because container muxing preserves track timestamp offsets.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        deadline = time.perf_counter() + float(args.timeout)
        timing: dict[str, Any] | None = None
        while time.perf_counter() < deadline:
            for event in events:
                if event["event"] == "speech.timing":
                    timing = dict(event["data"])
                elif event["event"] == "speech.ended" and timing and first_video.is_set():
                    deadline = min(deadline, time.perf_counter() + 1.0)
            if timing and first_video.is_set():
                if len(video_frames.get("frames", [])) >= min(50, int(video_frames.get("max_frames", 250))):
                    if any(e["event"] == "speech.ended" for e in events):
                        break
            await asyncio.sleep(0.2)
        video_frames["capture"] = False
        sampler.stop()
        await sampler_task
        if timing is None:
            raise TimeoutError("speech.timing was not received")
        if idle_proc_vram is None or sampler.max_process_vram_gb is None:
            raise RuntimeError(
                "related-process GPU memory was not measured; "
                f"idle={idle_proc_vram!r}, peak={sampler.max_process_vram_gb!r}, pids={pids!r}"
            )
        peak_process_vram = max(idle_proc_vram, sampler.max_process_vram_gb)

        # The WebRTC track can deliver an idle/reference frame before speech starts.
        # Use the server-side speech media milestone for the required first-response
        # metric, and keep the aiortc frame observation as transport evidence.
        e2e_first = timing.get("e2e_first_response_ms")
        chunk_lat = [float(v) for v in timing.get("chunk_latency_ms", [])]
        actual_width = timing.get("output_width") or model_cfg.get("width", "not_measured")
        actual_height = timing.get("output_height") or model_cfg.get("height", "not_measured")
        actual_fps = timing.get("output_fps") or model_cfg.get("fps", model_status.get("fps", "not_measured"))
        if timing.get("chunk_samples") and timing.get("sample_rate"):
            actual_chunk = f"{round(float(timing['chunk_samples']) / float(timing['sample_rate']) * 1000)}ms"
        else:
            actual_chunk = model_cfg.get("chunk_size", "not_measured")
        result = {
            "测试日期": cfg.get("test_date") or datetime.now().strftime("%Y-%m-%d"),
            "测试人": tester,
            "模型": model,
            "技术路线": technical_route_for_model(model, model_cfg, cfg),
            "backend": backend,
            "硬件": hardware.get("name"),
            "OS": platform.platform(),
            "驱动环境": f"driver {hardware.get('driver')} / torch unknown",
            "commit": f"{run(['git', 'rev-parse', 'HEAD'], cwd=repo).stdout.strip()} + {run(['git', '-C', str(repo.parent / 'omnirt'), 'rev-parse', 'HEAD']).stdout.strip()}",
            "输入类型": cfg.get("input_type", "audio+image"),
            "输出分辨率": f"{actual_width}x{actual_height}",
            "输出 FPS": actual_fps,
            "chunk size": actual_chunk,
            "冷启动时间": round(cold_start, 3),
            "预热时间": round(warmup_seconds, 3),
            "TTFA": round(float(timing.get("ttfa_ms") or 0.0), 3),
            "TTFV": round(float(timing.get("ttfv_ms") or 0.0), 3),
            "首轮总延迟": round(float(e2e_first or 0.0), 3),
            "稳态 FPS": round(float(timing.get("steady_fps") or 0.0), 3),
            "RTF": round(float(timing.get("rtf") or 0.0), 4),
            "idle 显存": idle_proc_vram,
            "推理峰值显存": peak_process_vram,
        }
        raw = {
            "result": result,
            "timing": timing,
            "events": events,
            "model_status": model_status,
            "resource": {
                "gpu_index": gpu_index,
                "vram_result_scope": "related_process_only",
                "vram_definition": {
                    "idle_vram_gb": "OpenTalking + OmniRT related PID GPU memory on the target GPU after warmup and before the measured speak request",
                    "peak_inference_vram_gb": "Peak GPU memory of the same related PID set on the target GPU during the measured speak request",
                },
                "vram_measurement_status": {
                    "idle_process_measured": idle_vram_measured,
                    "peak_process_measured": sampler.max_process_vram_gb is not None,
                    "device_values_are_diagnostic_only": True,
                },
                "service_ready_device_vram_gb_diagnostic": service_ready_device_vram,
                "service_ready_process_vram_gb": service_ready_proc_vram,
                "post_warmup_idle_device_vram_gb_diagnostic": idle_device_vram,
                "idle_process_vram_gb": idle_proc_vram,
                "peak_device_vram_gb_diagnostic": sampler.max_device_vram_gb,
                "peak_process_vram_gb": peak_process_vram,
                "speak_sample_peak_process_vram_gb": sampler.max_process_vram_gb,
                "peak_cpu_gb": sampler.max_cpu_gb,
                "pids": pids,
                "post_warmup_pids": post_warmup_pids,
                "latest_pids": sampler.latest_pids,
                "peak_process_vram_pids": sampler.max_process_vram_pids,
                "root_pids": pid_info["root_pids"],
                "pid_files": pid_info["pid_files"],
                "ports": ports,
                "nvidia_smi_process_records": gpu_process_mem_records(sampler.latest_pids or pids, gpu_index=gpu_index) or [],
                "nvidia_smi_snapshot": run(["nvidia-smi"]).stdout,
            },
            "avatar": {"base_avatar_id": base_avatar_id, "benchmark_avatar_id": avatar_id, "benchmark_avatar_dir": str(benchmark_avatar_dir)},
            "input": {"audio": str(audio_src), "reference": str(ref_src), "duration_seconds": audio_duration},
            "output_video_frames_observed": video_frames.get("count", 0),
            "output_sample_path": "",
            "output_video_mocked": True,
            "output_video_mock_note": str(video_mock_path),
        }
        (out_dir / "result.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_csv(out_dir / "result.csv", result)
        md = ["# OpenTalking E2E Benchmark", ""]
        for key, value in result.items():
            md.append(f"- {key}: {value}")
        md += [
            f"- chunk latency p50: {round(percentile(chunk_lat, 0.50) or 0.0, 3)}ms",
            f"- chunk latency p95: {round(percentile(chunk_lat, 0.95) or 0.0, 3)}ms",
            f"- 日志路径: {out_dir / 'logs'}",
            f"- 输出样例路径: mocked ({video_mock_path})",
            "",
        ]
        report = out_dir / f"{label}_opentalking_e2e_benchmark_result.md"
        report.write_text("\n".join(md), encoding="utf-8")
        archive = out_dir / f"{label}_opentalking_e2e_artifacts.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(out_dir.rglob("*")):
                if path != archive and path.is_file():
                    tar.add(path, arcname=path.relative_to(out_dir))
        await pc.close()
        stop_sse.set()
        sse_task.cancel()
        print(json.dumps({"output_dir": str(out_dir), "result": result, "raw": str(out_dir / "result.json")}, ensure_ascii=False, indent=2))
    finally:
        if "benchmark_avatar_dir" in locals():
            shutil.rmtree(benchmark_avatar_dir, ignore_errors=True)
        stop_opentalking(repo, cfg)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                process.terminate()
        if omnirt_started_by_benchmark and not args.keep_omnirt:
            stop_omnirt_model(repo, cfg, model, backend, model_cfg)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/opentalking-e2e.yaml")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--api-base-url", default="")
    parser.add_argument("--backend", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--avatar-id", default="")
    parser.add_argument("--tester", default="")
    parser.add_argument("--gpu-index", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--reuse-omnirt", action="store_true", help="reuse an already-running OmniRT service; cold start then excludes OmniRT startup")
    parser.add_argument("--keep-omnirt", action="store_true", help="keep benchmark-started OmniRT service running after the test")
    args = parser.parse_args()
    asyncio.run(run_once(args))


if __name__ == "__main__":
    main()
