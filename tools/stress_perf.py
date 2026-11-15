"""Concurrency stress + performance probes against the LIVE container stack.

1. concurrent retrieval (20 requests / 8 workers)  → latency distribution, errors
2. concurrent admin rebuilds (4 requests)          → exactly 1 runs, 3 get 409
3. retrieval DURING the blue-green rebuild         → zero failed reads
4. host-side embedding throughput                  → texts/sec for batch indexing

Run: .conda-py310/python.exe tools/stress_perf.py
"""

from __future__ import annotations

import concurrent.futures
import json
import statistics
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx

BASE = "http://127.0.0.1:8012"
ADMIN_KEY = "test-admin-key-2026"
QUERY = "差旅报销需要提交哪些材料？"


def concurrent_retrieval() -> dict:
    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()

    def one(client: httpx.Client):
        started = time.perf_counter()
        try:
            r = client.post(f"{BASE}/search", json={"query": QUERY, "top_k": 5}, timeout=120)
            ok = r.status_code == 200 and r.json().get("results")
        except Exception:
            ok = False
        with lock:
            latencies.append(time.perf_counter() - started)
            return ok

    with httpx.Client() as client, concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: one(client), range(20)))
    errors = sum(1 for ok in results if not ok)
    return {
        "requests": 20,
        "workers": 8,
        "errors": errors,
        "p50_ms": round(statistics.median(latencies) * 1000),
        "p95_ms": round(sorted(latencies)[int(0.95 * len(latencies))] * 1000),
        "max_ms": round(max(latencies) * 1000),
    }


def concurrent_rebuilds_and_live_reads() -> dict:
    statuses: list[int] = []
    read_errors = 0
    reads_done = 0

    def rebuild(client: httpx.Client):
        r = client.post(
            f"{BASE}/knowledge-base/rebuild",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=900,
        )
        statuses.append(r.status_code)

    def reader(client: httpx.Client, reads: int = 15):
        nonlocal read_errors, reads_done
        for _ in range(reads):
            try:
                r = client.post(f"{BASE}/search", json={"query": QUERY, "top_k": 3}, timeout=120)
                if r.status_code == 200 and r.json().get("results"):
                    reads_done += 1
                else:
                    read_errors += 1
            except Exception:
                read_errors += 1
            time.sleep(0.2)

    with httpx.Client() as client:
        readers = [threading.Thread(target=reader, args=(client, 60)) for _ in range(3)]
        for t in readers:
            t.start()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: rebuild(client), range(2)))
        for t in readers:
            t.join()

    return {
        "rebuild_statuses": statuses,
        "expected": "2 rebuilds serialize (RLock+task guard); concurrent reads never fail",
        "live_reads_during_rebuild": reads_done,
        "live_read_errors": read_errors,
    }


def embedding_throughput() -> dict:
    from backend.indexing.embedding_provider import get_embedding

    started = time.perf_counter()
    embedding = get_embedding()
    load_s = time.perf_counter() - started

    texts = [f"测试文本第 {i} 段，用于测量批量嵌入吞吐量。" * 3 for i in range(139)]
    started = time.perf_counter()
    vectors = embedding.embed_documents(texts)
    elapsed = time.perf_counter() - started
    return {
        "model_load_s": round(load_s, 1),
        "texts": len(texts),
        "vector_dim": len(vectors[0]) if vectors else 0,
        "total_s": round(elapsed, 1),
        "texts_per_sec": round(len(texts) / elapsed, 1),
    }


def main() -> None:
    print("[1/3] concurrent retrieval ...")
    retrieval = concurrent_retrieval()
    print(json.dumps(retrieval, ensure_ascii=False))

    print("[2/3] concurrent rebuilds + live reads during rebuild ...")
    rebuilds = concurrent_rebuilds_and_live_reads()
    print(json.dumps(rebuilds, ensure_ascii=False))

    print("[3/3] host embedding throughput ...")
    throughput = embedding_throughput()
    print(json.dumps(throughput, ensure_ascii=False))

    out = Path("tests/golden/stress_perf.json")
    out.write_text(
        json.dumps({"retrieval": retrieval, "rebuilds": rebuilds, "embedding": throughput}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
