"""Full-stack container verification against http://127.0.0.1:8012.

Usage (from project root, UTF-8 safe):
    .conda-py310/python.exe tools/container_verify.py

Checks: health, index versions, vector/keyword retrieval, admin auth 401 paths,
and a real blue-green rebuild via the admin API.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx

BASE = "http://127.0.0.1:8012"
ADMIN_KEY = "test-admin-key-2026"


def main() -> None:
    results: list[tuple[str, bool, str]] = []
    with httpx.Client(timeout=300.0) as client:
        health = client.get(f"{BASE}/health").json()
        ok = health.get("status") == "ok" and health["database"]["connected"]
        results.append(("health: status=ok + db connected", ok, str(health.get("database"))))

        versions = client.get(f"{BASE}/index/versions").json()
        active = versions.get("active_version") or {}
        results.append(
            ("index/versions shows active version", bool(active.get("name")), str(active.get("name"))),
        )

        r = client.post(f"{BASE}/search", json={"query": "生产环境发布失败后如何回滚？", "top_k": 3})
        ok = r.status_code == 200 and len(r.json().get("results", [])) == 3
        top_source = r.json()["results"][0]["source"] if ok else r.text[:80]
        ok = ok and "生产环境发布与回滚操作规范" in str(top_source)
        results.append(("vector search hits expected source", ok, f"top={top_source}"))

        r = client.post(f"{BASE}/keyword-search", json={"query": "差旅报销需要提交哪些材料？", "top_k": 3})
        ok = r.status_code == 200 and len(r.json().get("results", [])) == 3
        results.append(("keyword search returns 3", ok, r.text[:60]))

        r = client.post(f"{BASE}/knowledge-base/rebuild")
        results.append(("rebuild without key -> 401", r.status_code == 401, str(r.status_code)))

        r = client.post(f"{BASE}/knowledge-base/rebuild", headers={"X-API-Key": "wrong-key"})
        results.append(("rebuild with wrong key -> 401", r.status_code == 401, str(r.status_code)))

        r = client.post(f"{BASE}/knowledge-base/rebuild", headers={"X-API-Key": ADMIN_KEY})
        ok = r.status_code == 200 and r.json().get("status") == "rebuilt"
        body = r.json() if ok else r.text[:120]
        results.append(
            (
                "rebuild with admin key -> blue-green rebuild",
                ok,
                f"version={body.get('version')}, chunks={body.get('chunk_count')}, files={len(body.get('data_files', []))}",
            )
        )

        after = client.get(f"{BASE}/index/versions").json()
        new_active = (after.get("active_version") or {}).get("name", "")
        retired_count = sum(1 for v in after.get("versions", []) if v.get("status") == "retired")
        results.append(
            ("new active version switched, old retired", bool(new_active) and retired_count >= 1, f"active={new_active}, retired={retired_count}"),
        )

        r = client.post(f"{BASE}/search", json={"query": "客户数据访问控制有哪些分级？", "top_k": 2})
        ok = r.status_code == 200 and "客户数据分级与访问控制管理制度" in str(r.json()["results"][0]["source"])
        results.append(("post-rebuild retrieval on new version", ok, r.text[:60]))

    print("== container verification ==")
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        failed += 0 if ok else 1
        print(f"[{mark}] {name}  ({detail})")
    print(f"\n{len(results) - failed}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
