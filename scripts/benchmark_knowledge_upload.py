#!/usr/bin/env python3
"""Measure knowledge upload acknowledgement and indexing separately.

This benchmark deliberately uses a local fake index by default.  It measures
the storage/parser boundary without requiring LightRAG, credentials, OCR or a
network service.  Set ``OPENTALKING_BENCHMARK_INDEX_DELAY_MS`` to inject a
repeatable index delay when checking that deferred uploads do not await it.

Examples::

    python scripts/benchmark_knowledge_upload.py
    python scripts/benchmark_knowledge_upload.py --runs 5 --json results.json

The generated records are comparable across the 8/10/12/20/50 KB points and
must not be interpreted as production LightRAG latency measurements.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Make ``python scripts/benchmark_knowledge_upload.py`` work from a source
# checkout without requiring an editable package install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opentalking.agent.knowledge_index import LightRAGSearchResult, LightRAGStatus
from opentalking.agent.knowledge_store import KnowledgeStore


class BenchmarkIndex:
    """Deterministic fake index for measuring the upload boundary."""

    def __init__(self, delay_ms: float) -> None:
        self.delay = max(0.0, delay_ms) / 1000.0
        self.calls = 0

    def index_document(self, **_: str) -> None:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)

    def index_documents(self, *, documents: list[dict[str, str]], **_: Any) -> None:
        self.calls += len(documents)
        if self.delay:
            time.sleep(self.delay)

    def delete_document(self, **_: str) -> None:
        return None

    def clear_knowledge_base(self, _: str) -> None:
        return None

    def query(self, **_: Any) -> list[LightRAGSearchResult]:
        return []

    def status(self, **_: str) -> LightRAGStatus:
        return LightRAGStatus(available=True, indexed=False, reason="benchmark")


async def _heartbeat(stop: asyncio.Event, samples: list[float], interval: float = 0.001) -> None:
    previous = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(interval)
        now = time.perf_counter()
        samples.append(now - previous)
        previous = now


async def _timed(operation: Any) -> tuple[Any, float, float]:
    stop = asyncio.Event()
    samples: list[float] = []
    task = asyncio.create_task(_heartbeat(stop, samples))
    started = time.perf_counter()
    result = await operation()
    elapsed = time.perf_counter() - started
    stop.set()
    await task
    max_gap_ms = max(samples, default=0.0) * 1000.0
    return result, elapsed, max_gap_ms


def _content(size_kb: int) -> str:
    seed = (
        "OpenTalking knowledge upload benchmark.  This is a stable paragraph "
        "used to compare acknowledgement and indexing costs. 中文知识库内容。\n\n"
    ).encode("utf-8")
    target = size_kb * 1024
    data = (seed * ((target // len(seed)) + 1))[:target]
    return data.decode("utf-8", errors="ignore")


async def _run_one(root: Path, size_kb: int, run: int, delay_ms: float) -> dict[str, Any]:
    source = root / f"source-{size_kb}-{run}.md"
    source.write_text(_content(size_kb), encoding="utf-8")

    deferred_index = BenchmarkIndex(delay_ms)
    deferred = KnowledgeStore(
        db_path=root / f"deferred-{size_kb}-{run}.sqlite",
        knowledge_root=root / f"deferred-root-{size_kb}-{run}",
        knowledge_index=deferred_index,
    )
    started = time.perf_counter()
    document, ack_seconds, ack_gap_ms = await _timed(
        lambda: deferred.add_document_deferred(
            kb_id="benchmark",
            filename=source.name,
            mime_type="text/markdown",
            source_path=source,
        )
    )
    ack_wall_seconds = time.perf_counter() - started
    _, index_seconds, index_gap_ms = await _timed(
        lambda: deferred.index_document(kb_id=document.kb_id, doc_id=document.id)
    )
    indexed = await deferred.list_documents(kb_id=document.kb_id)
    indexed_document = next(item for item in indexed if item.id == document.id)

    baseline_index = BenchmarkIndex(delay_ms)
    baseline_source = root / f"baseline-source-{size_kb}-{run}.md"
    baseline_source.write_text(_content(size_kb), encoding="utf-8")
    baseline = KnowledgeStore(
        db_path=root / f"baseline-{size_kb}-{run}.sqlite",
        knowledge_root=root / f"baseline-root-{size_kb}-{run}",
        knowledge_index=baseline_index,
    )
    baseline_doc, baseline_seconds, baseline_gap_ms = await _timed(
        lambda: baseline.add_document(
            kb_id="benchmark",
            filename=source.name,
            mime_type="text/markdown",
            source_path=baseline_source,
        )
    )
    return {
        "size_kb": size_kb,
        "run": run,
        "bytes": baseline_source.stat().st_size,
        "chunks": indexed_document.chunk_count,
        "upload_ack_latency_ms": round(ack_seconds * 1000.0, 3),
        "upload_ack_wall_latency_ms": round(ack_wall_seconds * 1000.0, 3),
        "index_ready_latency_ms": round(index_seconds * 1000.0, 3),
        "deferred_total_ms": round((ack_seconds + index_seconds) * 1000.0, 3),
        "baseline_ready_latency_ms": round(baseline_seconds * 1000.0, 3),
        "ack_event_loop_max_gap_ms": round(ack_gap_ms, 3),
        "index_event_loop_max_gap_ms": round(index_gap_ms, 3),
        "baseline_event_loop_max_gap_ms": round(baseline_gap_ms, 3),
        "index_calls": deferred_index.calls,
        "baseline_status": baseline_doc.status,
        "index_status": indexed_document.status,
        "fake_index_delay_ms": delay_ms,
    }


async def _main(args: argparse.Namespace) -> list[dict[str, Any]]:
    delay_ms = float(os.environ.get("OPENTALKING_BENCHMARK_INDEX_DELAY_MS", "0"))
    with tempfile.TemporaryDirectory(prefix="opentalking-kb-benchmark-") as directory:
        root = Path(directory)
        records: list[dict[str, Any]] = []
        for size_kb in args.sizes:
            for run in range(1, args.runs + 1):
                records.append(await _run_one(root, size_kb, run, delay_ms))
        return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[8, 10, 12, 20, 50],
        help="content sizes in KiB (default: 8 10 12 20 50)",
    )
    parser.add_argument("--runs", type=int, default=3, help="runs per size (default: 3)")
    parser.add_argument("--json", type=Path, help="also write JSON records to this file")
    args = parser.parse_args()
    if args.runs < 1 or any(size < 1 for size in args.sizes):
        parser.error("--runs and --sizes must be positive")
    records = asyncio.run(_main(args))
    for record in records:
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    if args.json:
        args.json.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
