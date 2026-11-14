#!/usr/bin/env bash
# PostgreSQL 恢复：把 backup-db.sh 产出的 .dump 恢复到指定数据库（默认临时验证库）
# 用法: ./scripts/restore-db.sh <dump文件> [目标数据库名]  目标库默认 rag_restore_test
set -euo pipefail
cd "$(dirname "$0")/.."

DUMP_FILE="${1:?usage: restore-db.sh <dump-file> [target-db]}"
TARGET_DB="${2:-rag_restore_test}"

if [ ! -f "$DUMP_FILE" ]; then
  echo "[restore] dump file not found: $DUMP_FILE" >&2
  exit 1
fi

echo "[restore] recreating database $TARGET_DB"
docker compose exec -T db psql -U rag -d postgres -c "DROP DATABASE IF EXISTS \"$TARGET_DB\" WITH (FORCE);"
docker compose exec -T db psql -U rag -d postgres -c "CREATE DATABASE \"$TARGET_DB\" OWNER rag;"

echo "[restore] restoring $DUMP_FILE -> $TARGET_DB"
docker compose exec -T db pg_restore -U rag -d "$TARGET_DB" --no-owner --exit-on-error < "$DUMP_FILE"

ROWS=$(docker compose exec -T db psql -U rag -d "$TARGET_DB" -tc "SELECT count(*) FROM child_chunks;")
echo "[restore] verified: child_chunks rows = $ROWS"
echo "[restore] done. 如为验证目的，请手动删除临时库:"
echo "  docker compose exec db psql -U rag -d postgres -c 'DROP DATABASE IF EXISTS \"$TARGET_DB\" WITH (FORCE);'"
