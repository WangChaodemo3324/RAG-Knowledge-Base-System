# 部署验收报告（DEPLOYMENT_ACCEPTANCE_REPORT）

## 1. 验收环境

| 项 | 值 |
| --- | --- |
| 宿主 | Windows 11（26200）+ Docker Desktop 29.6.1 / Compose v5.3.0 |
| 镜像 | rag-api（python:3.12-slim + torch CPU + 依赖，~5-6GB） |
| 数据库 | pgvector/pgvector:pg16 容器（pgdata 具名卷） |
| 模型缓存 | hf_cache 具名卷（V3.5 新增，Linux 文件系统） |
| 语料 | `./resource data` bind mount |

## 2. 全新部署验收（真实执行）

| 步骤 | 结果 |
| --- | --- |
| `docker compose up -d db` | ✅ healthy（pg_isready） |
| 容器启动 entrypoint | ✅ alembic upgrade → 模型缓存自举 → uvicorn |
| Alembic 迁移 | ✅ 0001+0002（`\dt` + pg_extension + pg_indexes 核实） |
| healthcheck 转healthy | ✅（/health 含 DB 连通 + active 版本） |
| 文档上传（单文件） | ✅ 200 |
| 批量上传（V3.5） | ✅ 3 文件独立入库 |
| 文档列表/删除 | ✅（trash 可恢复 + 404 语义） |
| RAG 检索/重排 | ✅ 容器内 rerank 200（score 0.989） |
| SSE 流式问答 | ✅ 真实 DeepSeek（567 tokens，V2 冒烟）+ 真实浏览器 UI 流式（V3.5，883 字符） |
| 容器重启持久化 | ✅ db/api 双重启数据不变 |

## 3. V3.5 部署层发现并修复的缺陷（4 个）

| # | 缺陷 | 修复 |
| --- | --- | --- |
| D-1 | Windows bind mount（9P）上 torch mmap 加载大 safetensors 失败（meta tensor）——**决定性实验**：同一文件复制到容器本地 FS 后加载成功（meta: False） | HF 缓存改 **hf_cache 具名卷**（Linux fs）+ entrypoint 自举（从 /host-cache 只读挂载一次性复制，宿主机无缓存时经 HF_ENDPOINT 镜像下载） |
| D-2 | `HF_ENDPOINT` 空字符串 → huggingface_hub "No scheme supplied" → rerank 容器内加载必败 | compose 默认值 `https://huggingface.co` |
| D-3 | transformers 联网拉取模型仓库新增 `additional_chat_templates` 文件失败（CN 网络） | `HF_HUB_OFFLINE=1`（缓存齐全时强制离线，compose 透传 + .env.example 说明） |
| D-4 | 镜像迁移漂移（宿主机新增迁移后容器报 Can't locate revision 循环重启） | 已文档化（DEPLOY.md）：新增迁移后必须 `--build`；entrypoint 化后单实例安全 |

## 4. 一键操作命令（已在 DEPLOY.md 完整文档化）

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build  # 开发（本地模型缓存）
docker compose -f docker-compose.prod.yml up -d --build                        # 生产（强制密钥变量）
./scripts/deploy-check.sh     # 一键巡检（容器/健康/迁移/索引/磁盘）
./scripts/backup-db.sh        # 备份（RETAIN=7 保留策略）
./scripts/restore-db.sh <dump> [目标库]  # 恢复（含验证）
```

## 5. 网络环境专项（CN 部署实录）

| 问题 | 绕行 |
| --- | --- |
| auth.docker.io DNS 污染（基础镜像拉取失败） | daocloud 镜像源预拉取 + 本地 tag |
| unpkg.com 不可达（前端 Vue CDN 白屏） | Vue 本地 vendor 化（零 CDN 依赖） |
| objects.githubusercontent.com 慢/断（scoop 下载卡死） | python httpx 直连下载成功（13s/257MB） |
| hf-mirror.com 间歇不可达 | HF_HUB_OFFLINE=1 强制离线（缓存齐全后） |

## 6. 验收结论

**部署验收通过**。V3.5 部署链路（构建→迁移→自举→启动→健康检查→业务全链路）在本机 Docker 环境完整验证；四个部署级缺陷全部修复并有回归防护。生产部署前置条件（强制变量、反向代理）已在 DEPLOY.md 文档化。
