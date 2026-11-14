# Changelog

## v2.0.0（分支 `feature/pgvector-migration`，未合入 main）

存储层从 Chroma + 三个 JSON 文件迁移到 PostgreSQL 16 + pgvector，Docker Compose 部署，完整测试与文档。

### Phase 0 — 回归基线（已验证）
- 新增 `tools/baseline_capture.py`：13 个检索用例 × 4 端点（向量/BM25/混合/重排）对当前栈采集 golden 指标
- 基线结果：四端点全部 13/13 命中；向量/混合/重排 mean_rank=1.077，BM25=1.692（`tests/golden/baseline_retrieval.json`）
- 发现：rerank 首调冷加载 38s → 引入启动预热

### Phase 1 — DB 层（代码完成，验证待环境）
- 新增 `backend/db/`（SQLAlchemy 2.0 引擎/会话/模型）、`migrations/`（Alembic，0001 初始迁移含 `CREATE EXTENSION vector` 与 HNSW 索引）
- 新增 `backend/indexing/pg_store.py`：版本生命周期、事务写入、cosine KNN、父块展开、校验、任务状态机、启动恢复
- 选型：评估 langchain-postgres PGVectorStore 后不采用（langchain-core≥1.2 与项目 0.3.x 硬冲突 + 结构性冲突，见 docs/ARCHITECTURE.md §2）；spike 脚本待 DB 就绪后取证
- 移除 `chromadb` 依赖与 `backend/indexing/{vector_store,parent_store,child_store,index_service,index_manifest,index_records}.py`

### Phase 2 — 版本化索引管线（代码完成，验证待环境）
- 新增 `backend/indexing/index_pipeline.py`：蓝绿全量构建（构建→校验→原子切换→旧版保留）、事务内文件交换、指纹跳过、启动恢复
- `KeywordSearchService` 改为从 PG active 版本加载语料，按 `(version_id, child_count)` 签名热重载
- 新增 `backend/indexing/embedding_provider.py` 共享嵌入实例

### Phase 3 — 检索切换（代码完成，验证待环境）
- `KnowledgeBase` 重写为 pgvector 门面；`hybrid_search_service` 适配 dict 候选；`doc_to_source` 支持行字典
- `rag_service.py` 重写，保持 API 响应字段兼容（data_files/chunk_count/filename 等）
- main.py 新增 `GET /index/versions`；`/health` 增加 DB 连接与 active 版本检查

### Phase 4 — 工程加固（代码完成，验证待环境）
- `backend/core/auth.py`：管理端点 X-API-Key 守卫（未配置=关闭）
- `backend/core/logging.py`：JSON 结构化日志 + X-Request-ID 中间件
- 全局异常处理（500 通用文案）、VersionError→409、修复 CORS allow_credentials 与通配符并用的问题
- RagService 启动后台预热 rerank 模型

### Phase 5 — 容器化（文件就绪，构建待环境）
- `Dockerfile`（python:3.12-slim + torch CPU）、`.dockerignore`、`docker-compose.yml`（db+api、健康检查、pgdata/hf_models 卷、`./resource data` bind mount）
- `.env.example` 补齐 DEEPSEEK/POSTGRES/RAG_ADMIN_API_KEY

### 测试
- 单元测试 27/27 通过（RRF/分块/路由/证据检查/记忆/认证）
- 集成与故障注入测试已编写（`tests/integration/test_pg_store.py`，10 个用例：版本互斥、cosine 检索、父块去重、文档交换无孤儿、任务并发拒绝、崩溃恢复、半事务回滚），**待 PostgreSQL 可用后真实运行**

### 已知问题 / 后续
- PGVectorStore spike 与全部 DB 依赖验证被 Windows「虚拟机平台」未启用阻塞（见 PROGRESS.md）
- evidence_checker 的 rerank_score 阈值 0.45 未校准（历史问题，随 v2.1 校准）
- 词表路由过拟合当前语料（历史问题）
- `tools/test_*.py` 三个旧手工脚本引用已删除的 /info 字段，将由回归测试工具替代
