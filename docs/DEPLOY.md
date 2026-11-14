# 部署文档（Docker Compose）

## 前置要求

1. Docker Desktop ≥ 4.x（本项目验证环境：Docker 29.6.1 + Compose v5.3.0）
2. **Windows 需启用「虚拟机平台」+ WSL2**（BIOS 虚拟化开启的前提下）：

   ```powershell
   # 管理员 PowerShell
   dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
   bcdedit /set hypervisorlaunchtype auto
   # 然后重启电脑，启动 Docker Desktop，docker ps 应返回空列表且无报错
   ```

   排障：若 `wsl -d docker-desktop` 报 `HCS_E_SERVICE_NOT_AVAILABLE`，即上述功能未生效；若 `HyperVisorPresent=False` 且 bcdedit 已设 auto，重启后仍未恢复请检查 BIOS VT-x/AMD-V 与安全启动设置。

3. Linux 服务器则只需 Docker Engine + Compose 插件。

## 配置

复制 `.env.example` 为 `.env` 并填写：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | ✅ | 问答功能必需 |
| `TAVILY_API_KEY` | 可选 | 联网搜索主链路，缺省 fallback DuckDuckGo |
| `POSTGRES_USER/PASSWORD/DB` | ✅ | 数据库凭据，**生产环境务必改密码** |
| `POSTGRES_HOST_PORT` | 可选 | 宿主机暴露端口，默认 5433 |
| `RAG_DATABASE_URL` | ✅ | 本机直连（不走容器）时的连接串 |
| `RAG_ADMIN_API_KEY` | 推荐 | 管理端点（上传/重建/清记忆）的 X-API-Key；留空=不启用 |
| `HF_ENDPOINT` | 可选 | 国内网络建议 `https://hf-mirror.com` |

## 启动

```bash
docker compose up -d db          # 先起数据库（pgvector/pgvector:pg16，带健康检查）
docker compose up -d api --build # api 容器：自动 alembic upgrade head → uvicorn
docker compose ps                # 等两个服务都 healthy
curl http://127.0.0.1:8012/health
```

首次启动：
- `api` 会自动执行 Alembic 迁移（`CREATE EXTENSION vector` + 建表 + HNSW 索引）
- 无 active 版本时自动构建 v1 索引（6 份语料 → 139 子块，CPU 嵌入约 1–2 分钟）
- 首次需要下载 BGE-M3 ONNX（约 2.3GB）与 bge-reranker-base（约 1.1GB）到 `hf_models` 卷；**国内网络务必配置 HF_ENDPOINT**，否则可能超时。下载完成后重启容器不再重复下载
- 镜像约 5–6GB（torch CPU 版）；`start_period` 给了 120s + 10×15s 重试的启动宽限

## 常用操作

```bash
# 查看索引版本（蓝绿状态）
curl http://127.0.0.1:8012/index/versions

# 手动全量重建（管理端点，需 X-API-Key）
curl -X POST http://127.0.0.1:8012/knowledge-base/rebuild -H "X-API-Key: $RAG_ADMIN_API_KEY"

# 上传文档（管理端点）
curl -X POST http://127.0.0.1:8012/documents/upload -H "X-API-Key: $RAG_ADMIN_API_KEY" -F "file=@doc.md"

# 日志与数据库
docker compose logs -f api
docker compose exec db psql -U rag -d rag -c "SELECT id,name,status,is_active FROM index_versions ORDER BY id DESC LIMIT 5;"

# 停止 / 彻底清库
docker compose down
docker compose down -v   # ⚠️ 连同 pgdata 卷一起删除
```

## 数据持久化

| 卷 | 内容 |
| --- | --- |
| `pgdata` | PostgreSQL 数据（索引版本、父子块、向量、任务历史） |
| `hf_models` | HuggingFace 模型缓存（BGE-M3 / reranker） |
| `./resource data`（bind mount） | 语料目录，容器内上传的文档落到宿主机 |

## 回滚到旧栈（Chroma + JSON）

旧栈数据（`chroma_db/`、`manifest.json`、`parent_store.json`、`child_store.json`）迁移全程未触碰，且回滚不需要删除任何新组件：

```bash
docker compose down            # 停新栈（可选 -v 清库）
git checkout main              # 切回 main 分支
.conda-py310/python.exe -m uvicorn api:app --port 8012   # 旧栈原样可用
```

## 升级 Alembic 迁移

容器启动时自动 `alembic upgrade head`（单实例安全）。多实例部署时请改为在部署流程中独立执行：

```bash
docker compose exec api alembic upgrade head
```

新增迁移：`alembic revision --autogenerate -m "..."`（在装齐依赖的开发环境执行）。
