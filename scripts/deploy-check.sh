#!/usr/bin/env bash
# 部署后检查：容器状态 / API 健康 / 迁移版本 / 索引状态 / 磁盘占用
set -euo pipefail
cd "$(dirname "$0")/.."

FAIL=0
step() { printf "\n== %s ==\n" "$1"; }

step "containers"
docker compose ps --format "{{.Name}}  {{.Status}}" || FAIL=1

step "api /health"
curl -sf http://127.0.0.1:8012/health || { echo "api health FAILED"; FAIL=1; }

step "alembic revision"
docker compose exec -T db psql -U rag -d rag -tc "SELECT version_num FROM alembic_version;" || FAIL=1

step "index state"
docker compose exec -T db psql -U rag -d rag -tc \
  "SELECT name, status FROM index_versions WHERE is_active;" || FAIL=1
docker compose exec -T db psql -U rag -d rag -tc \
  "SELECT count(*) AS children FROM child_chunks WHERE version_id = (SELECT id FROM index_versions WHERE is_active);" || FAIL=1

step "disk usage (pgdata volume)"
docker compose exec -T db sh -c 'du -sh /var/lib/postgresql/data 2>/dev/null || true'

printf "\n[deploy-check] result: %s\n" "$([ "$FAIL" -eq 0 ] && echo ALL-PASS || echo HAS-FAILURES)"
exit "$FAIL"
