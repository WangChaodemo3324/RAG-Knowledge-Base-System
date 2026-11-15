#!/usr/bin/env bash
# PostgreSQL 备份：pg_dump 自定义格式（可 pg_restore 恢复）
# 用法: ./scripts/backup-db.sh [输出目录]   默认 ./backups
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="$OUT_DIR/rag_backup_$STAMP.dump"

echo "[backup] dumping rag -> $FILE"
docker compose exec -T db pg_dump -U rag -Fc rag > "$FILE"
SIZE=$(wc -c < "$FILE")
echo "[backup] done: $SIZE bytes"
if [ "$SIZE" -lt 10000 ]; then
  echo "[backup] WARNING: archive suspiciously small — verify manually" >&2
  exit 2
fi
echo "[backup] latest: $FILE"

# 保留策略：保留最近 RETAIN 份，删除更旧的
RETAIN="${BACKUP_RETAIN:-7}"
ls -1t "$OUT_DIR"/rag_backup_*.dump 2>/dev/null | tail -n +"$((RETAIN + 1))" | while read -r old; do
  rm -f "$old"
  echo "[backup] pruned old backup: $old"
done
