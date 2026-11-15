# 架构文档：PostgreSQL + pgvector 存储迁移（v2.0.0）

分支 `feature/pgvector-migration`。目标：以 PostgreSQL + pgvector 统一承载向量、父子块、文档元数据、索引版本与任务状态，替代 Chroma + 三个 JSON 文件，并以蓝绿版本策略实现"永不先删后建"的增量入库。

## 1. 系统总览

```
                    ┌──────────────────────────────────────────────┐
  frontend / web    │  FastAPI (main.py)                           │
  (Vue3 via CDN) ──▶│  · 检索/问答端点（开放）                      │
                    │  · 管理端点：X-API-Key 守卫                   │
                    │  · 全局异常处理 + JSON 结构化日志             │
                    └───────────────┬──────────────────────────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │  RagService 门面              │
                    │  · ChatOrchestrator（三模式） │
                    │  · AnswerRouteService（路由） │
                    │  · QAService / ReactAgent     │
                    └──────┬───────────────┬───────┘
                           │               │
             ┌─────────────▼───┐   ┌───────▼─────────────┐
             │ KnowledgeBase   │   │ KeywordSearchService │
             │ (向量+父块展开) │   │ (BM25，版本签名热重载)│
             └───────┬─────────┘   └───────┬─────────────┘
                     │      ┌──────────────┘
             ┌───────▼──────▼───────────────────────────┐
             │  PostgreSQL 16 + pgvector                │
             │  index_versions / documents /            │
             │  parent_chunks / child_chunks(vector) /  │
             │  index_tasks                             │
             └───────▲──────────────────────────────────┘
             ┌───────┴──────────────────────────────────┐
             │  IndexPipeline（唯一写入口）              │
             │  蓝绿版本构建 / 事务内交换 / 故障恢复     │
             └──────────────────────────────────────────┘
```

保留不变的组件：BGE-M3 ONNX 嵌入、jieba+BM25 算法、RRF 融合、bge-reranker 精排、父子分块（ChunkMetadataBuilder）、六路查询路由、ReAct Agent、Tavily 联网链路、前端。

## 2. 存储选型评估：langchain-postgres vs 自定义适配层

按迁移要求优先评估了 `langchain-postgres` 的 `PGVectorStore`，结论是**不采用**，改用 SQLAlchemy 2.0 + pgvector-python 自定义适配层（`backend/indexing/pg_store.py`）。以下六项均在实际 compose 数据库上实证（spike：`tools/evaluate_pgvectorstore.py`，隔离 venv）：

1. **依赖硬冲突**：langchain-postgres 0.0.19 要求 `langchain-core>=1.2.11`，与项目 `langchain 0.3.x / langchain-openai 0.3.35`（要求 core<1.0.0）不兼容，pip 安装即报冲突——采用它必须等待 LangChain 全家桶大版本升级。
2. **async-first 设计**：同步调用经内部事件循环桥接，Windows 默认 ProactorEventLoop 直接抛 `InterfaceError`，需全局改 SelectorEventLoopPolicy。
3. **API 不稳定**：`create_sync` 签名与早期版本完全不同（collection_name → table_name + PGEngine 对象）；同步工厂路径在 0.0.19 实际不可用（校验先于建表），只能走 async API + 显式 `ainit_vectorstore_table`。
4. **物理 schema 通用化**：单表仅 4 列（`langchain_id` UUID PK / `content` / `embedding` / `langchain_metadata`），**0 个外键**可达业务表——无法表达 `child→parent→document→version` 外键链与版本生命周期。
5. **事务不可统一**：`add_texts` 无 session 参数，无法与调用方 SQLAlchemy 事务合流，违背统一事务要求。
6. **ID 类型限制**：主键强制 UUID，任意字符串 id 直接报 `invalid input syntax for type uuid`。

自定义适配层的对价：检索查询、批量写入、校验逻辑需自行维护（约 400 行，全部有集成测试覆盖）。作为补偿，`BgeM3OnnxEmbeddings` 继续实现 LangChain `Embeddings` 接口，未来若需要可低成本换回 LangChain 检索器生态。

## 3. 版本化索引管线（蓝绿）

**全量重建**（`IndexPipeline.full_build`）：
1. 在 `index_tasks` 建任务（`pg_try_advisory_xact_lock` 关闭检查-插入竞态），创建 `building` 版本
2. 逐文件：指纹 → 加载 → 父子分块 → 嵌入（**在事务外**）→ 单事务写入该文件全部父子块
3. 构建完成后校验：孤儿子块计数、每文档父子数量比对、文件清单交叉核对
4. 校验通过 → 单条 UPDATE 原子切换 `is_active`（旧版本转 `retired` 保留可回滚），任务标 `succeeded`
5. 任何一步失败 → 版本标 `failed`、任务标 `failed`，**旧 active 版本全程未被触碰**

**增量入库**（`add_or_update_file`）：同一事务内完成"任务创建 → 旧块删除 → 新块写入 → 计数更新 → 任务完成提交"。未变化的文件（哈希相同+块数相同+分块参数相同）直接跳过。失败整体回滚，读者（MVCC）永远看到完整的旧文件或完整的新文件，不存在半更新状态。

**启动恢复**（`ensure_bootstrapped`）：启动时把遗留的 `running` 任务与超时 `building` 版本标 `failed`；若无 active 版本则自动构建 v1。

## 4. BM25 与向量的一致性

`KeywordSearchService` 每次检索前检查签名 `(active_version_id, child_count)`，变化即从 PG 重新加载语料重建 BM25。两路检索都只读同一个 active 版本；`file_name` 过滤走 SQL WHERE，天然同源。

## 5. 并发控制（三层）

| 层 | 机制 |
| --- | --- |
| 进程内 | `IndexPipeline._INDEX_LOCK`（RLock）序列化同进程写入 |
| 数据库 | `pg_try_advisory_xact_lock` 关闭任务创建竞态；任务表唯一 running 约束语义 |
| API | 重建/增量冲突返回 409 Conflict（VersionError 映射） |

## 6. 认证 / 日志 / 异常

- 管理端点（`/documents/upload`、`/knowledge-base/rebuild`、`/memory/clear`）通过 `require_admin` 校验 `X-API-Key`；`RAG_ADMIN_API_KEY` 未设置时认证关闭（本地开发）
- `backend/core/logging.py`：JSON 日志 + `X-Request-ID` 中间件（ContextVar 贯穿），每请求记录路由/耗时/状态码
- 全局异常处理：未捕获异常返回通用 500 文案，原始异常只进日志（修复旧版明文外泄）；路由冲突 409；模型未配置仍为 400/503

## 7. 回滚方案

- main 分支保持旧栈（Chroma + JSON）原样；回滚 = `git checkout main` 后照常运行
- 旧栈磁盘数据（`chroma_db/`、`manifest.json`、`parent_store.json`、`child_store.json`）迁移全程不读不写不删
- PG 为纯新增组件；`pgdata` 卷独立，删除卷即完全移除新栈数据
