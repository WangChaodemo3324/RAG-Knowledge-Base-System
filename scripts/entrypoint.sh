#!/usr/bin/env bash
# 容器入口：迁移 → 模型缓存自举 → 启动 API
set -e

alembic upgrade head

# 模型缓存自举：Windows bind mount（9P）上 torch 无法 mmap 加载大 safetensors
# （报 meta tensor），因此模型必须位于容器本地 Linux 文件系统（hf_cache 卷）。
# 开发环境把宿主机 HF 缓存只读挂载到 /host-cache，卷为空时一次性复制灌入；
# 生产环境无 /host-cache，首启经 HF_ENDPOINT（镜像站）直接下载到卷。
if [ -d /host-cache/hub ] && [ ! -d /app/hf-cache/hub/models--BAAI--bge-reranker-base ]; then
  echo "[entrypoint] seeding HF cache from host mount (one-time)..."
  mkdir -p /app/hf-cache/hub
  for model in models--BAAI--bge-m3 models--BAAI--bge-reranker-base; do
    if [ -d "/host-cache/hub/$model" ]; then
      cp -r "/host-cache/hub/$model" /app/hf-cache/hub/ && echo "[entrypoint] seeded $model"
    fi
  done
fi

export HF_HUB_CACHE=/app/hf-cache/hub

exec uvicorn api:app --host 0.0.0.0 --port 8012
