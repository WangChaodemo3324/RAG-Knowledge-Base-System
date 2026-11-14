# 面试指南：RAG 知识库系统（基于真实实现）

每题四段：简明回答 → 本项目实现 → 可能追问 → 代码位置。所有内容均可在仓库中验证。

---

## 1. 为什么从 Chroma 迁移到 PostgreSQL + pgvector？

**简答**：Chroma 是嵌入式向量库，索引与元数据/版本/任务状态分散在 JSON 文件里，多者之间没有事务边界——重建时"先删旧索引再建新"存在损坏窗口。PG + pgvector 把向量、父子块、版本、任务放进同一事务系统，蓝绿切换成为单条 UPDATE。

**本项目**：六项实证拒绝 langchain-postgres PGVectorStore（依赖冲突 langchain-core≥1.2 vs 项目 0.3.x、async-first 在 Windows 抛事件循环错、API 不稳定、单表 4 列无外键、事务不可统一、UUID 强制），自研 SQLAlchemy 2.0 适配层；迁移测试（升级/降级/升级循环）守护 schema 契约。

**追问**：pgvector 与 Milvus/Qdrant 的取舍？→ 单机亿级以下 + 强事务诉求选 pgvector；超大规模/多租户向量优先考虑专用库。
**代码**：`tools/evaluate_pgvectorstore.py`、`docs/ARCHITECTURE.md §2`、`migrations/versions/0001|0002`、`tests/integration/test_migrations.py`

## 2. pgvector 如何实现向量相似度检索？

**简答**：向量存为 `vector(N)` 列，SQL 里用操作符计算距离（余弦 `<=>`、L2 `<->`、内积 `<#>`），ORDER BY 距离 + LIMIT 即 Top-K。

**本项目**：BGE-M3 归一化嵌入（1024 维）→ 余弦距离匹配模型设计；`embedding.cosine_distance(query_vec)` 由 SQLAlchemy 生成；候选经 JOIN documents 实现 file_name 过滤。EXPLAIN ANALYZE 实测：139 行时规划器走 version_id 索引 + 精确排序（1.95ms），HNSW 为规模化保留。
**追问**：为什么归一化后余弦与内积等价？→ cos = dot/(|a||b|)，|a|=|b|=1。
**代码**：`backend/indexing/pg_store.py::search_children`、`tests/golden/stress_perf.json`

## 3. HNSW 是什么？

**简答**：分层可导航小世界图——多层跳表式图结构，查询从顶层贪心下行，O(logN) 近似最近邻；参数 M（每节点出边）、ef_construction（建图候选）、ef_search（查询候选）权衡精度与速度。

**本项目**：`CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`；当前 139 行精确扫描更快，规划器自动绕开——不盲目强制索引是实测结论。
**追问**：HNSW vs IVFFlat？→ IVFFlat 聚类桶需先训练、召回/速度调优靠 probes；HNSW 无需训练、召回更稳、内存更高。
**代码**：`migrations/versions/0001_initial_schema.py`（ix_child_chunks_embedding_hnsw）

## 4. BM25 和向量检索如何融合？

**简答**：向量管语义（同义改写），BM25 管词面（产品型号、专有名词精确命中），互补召回。

**本项目**：jieba 分词 BM25Okapi（语料来自 PG active 版本，签名 `(version_id, child_count)` TTL 1.5s 热重载，与向量同版本）；召回各取 top-k 后进入 RRF。
**追问**：BM25 为什么需要分词器？→ 中文无空格分词，jieba 精确模式 + 停用词过滤。
**代码**：`backend/services/keyword_search_service.py`、`backend/indexing/pg_store.py::load_children_for_bm25`

## 5. RRF 的工作原理。

**简答**：Reciprocal Rank Fusion——每个检索器给出排名，文档得分 = Σ 1/(k+rank)，k=60 抑制头部排名的过度影响；只看名次不看原始分，天然免归一化。

**本项目**：`_add_ranked_candidates` 按检索器累加 rrf_score，记录 vector_rank/bm25_rank/retrievers 供溯源；融合后送 rerank。
**追问**：k 调大/调小什么效果？→ k 越大排名差距越平缓（更民主），越小头部越强势。
**代码**：`backend/services/hybrid_search_service.py`，单测 `tests/unit/test_retrieval_logic.py::TestRRFusion`

## 6. CrossEncoder 为什么需要重排序？

**简答**：Bi-encoder 把查询与文档独立编码成向量（快，可预计算，但交互粗）；CrossEncoder 把 (query, doc) 拼接后 jointly 编码（慢，但捕捉细粒度交互），因此先用向量粗召回 top-30，再用交叉编码器精排 top-5。

**本项目**：bge-reranker-base（CPU）精排混合召回候选；阈值经真实实验校准：正样本 min 0.462 / 负样本 max 0.082 → 0.25 双侧等边距；rerank NDCG@5=0.963 为四路最高（tests/golden/retrieval_metrics.json）。
**追问**：延迟怎么权衡？→ CPU 精排 ~300ms/10 候选；可换 ONNX 量化或降候选数。
**代码**：`backend/services/rerank_service.py`、`tools/eval_rerank_calibration.py`

## 7. Parent-Child Retrieval 解决什么问题？

**简答**：小块检索精准但上下文不足，大块上下文足但检索噪声大——用小块（700 字）做匹配，命中后返回其父块（1800 字）给 LLM。

**本项目**：`write_chunks` 建立 child→parent FK；`expand_children_to_parents` 单查询批量取父块 + 去重（同父多子命中只返回一次，附 matched_child 溯源元数据）。
**追问**：去重为什么必要？→ 同一父块内多个子块都命中时，不去重会浪费 top-k 名额并产生重复上下文。
**代码**：`backend/indexing/pg_store.py::expand_children_to_parents`、`backend/indexing/chunking.py`

## 8. 蓝绿索引如何避免数据丢失？

**简答**：新版本在 `building` 状态完整构建 → 数量/孤儿/清单校验 → 单条 UPDATE 原子切换 `is_active` → 旧版本转 `retired` 保留。全程旧版本可读，任何失败只留下 `failed` 标记。

**本项目**：10 项故障注入全过——嵌入服务全挂时**拒绝激活空版本**（V2 修复的真缺陷）、PDF 单文件失败降级（6/7 文件照常服务）、切换前后崩溃恢复、交换中途回滚旧块完好。
**追问**：旧版本何时可删？→ `POST /index/prune` 保留最近 N 个 retired；正在执行的查询持有旧 version_id 快照，prune 时机须避开重建窗口。
**代码**：`backend/indexing/index_pipeline.py`、`tests/integration/test_blue_green_faults.py`

## 9. PostgreSQL 事务如何保证一致性？

**简答**：MVCC + 原子提交——增量入库的"删旧块+写新块"在同一事务，提交前其他会话看到完整旧数据，提交后看到完整新数据，失败回滚零残留。

**本项目**：`_incremental_locked` 单事务完成任务创建/删除/写入/计数；`session_scope` 提交-回滚封装；测试实证跨会话 READ COMMITTED 语义（第二会话看不到未提交数据，回滚后旧块完好）。
**追问**：长事务有什么风险？→ 持锁、膨胀、快照过旧——本项目嵌入在事务外完成，事务只包 DB 写入（毫秒级）。
**代码**：`backend/db/__init__.py::session_scope`、`tests/integration/test_pg_store.py::test_partial_transaction_rollback`

## 10. Advisory Lock 如何解决并发问题？

**简答**：PG 应用级咨询锁，不锁行只锁"约定的键"；事务级锁（`pg_try_advisory_xact_lock(key)`）随事务提交/回滚自动释放，进程崩溃无死锁残留。

**本项目**：三层并发控制——进程内 RLock（同进程序列化）→ 事务级 advisory lock（关闭 check-then-insert 竞态）→ index_tasks 唯一 running 行（跨进程协调）；冲突返回 409。故障注入验证：并发重建恰一个成功其余 409。
**追问**：为什么不用 SELECT FOR UPDATE？→ 需要锁的是"索引任务"这种无行实体的资源，advisory lock 语义更贴切且无行膨胀。
**代码**：`backend/indexing/pg_store.py::start_task`、`tests/golden/stress_perf.json`

## 11. FastAPI 如何处理异步请求？

**简答**：`async def` 端点跑在事件循环上（适合 I/O 等待），`def` 端点自动进线程池（适合同步库）——混用同步阻塞代码在 async def 里会卡死整个服务。

**本项目**：检索端点全部 `def`（线程池）；V2 修复的真实缺陷——上传端点的分钟级索引曾直接阻塞事件循环，现经 `run_in_threadpool` 执行；SSE 用同步生成器 + StreamingResponse（starlette 线程池迭代），断连经 GeneratorExit 传播，finally 落盘部分答案。
**追问**：什么时候必须 async？→ 高并发 I/O 等待（LLM 流式、外部 API）；CPU 密集（嵌入）永远线程/进程池。
**代码**：`backend/main.py`（/documents/upload、/chat/stream）、`backend/services/qa_service.py::chat_stream`、`tests/integration/test_sse.py`

## 12. Docker Compose 如何组织服务？

**简答**：db（pgvector/pgvector:pg16 + pg_isready 健康检查 + 具名卷）+ api（构建镜像、depends_on condition: service_healthy、启动即 alembic upgrade → uvicorn）；模型缓存卷避免每次重建下载 3.4GB。

**本项目**：踩过的真实坑都有解——镜像漂移（宿主机新增迁移后必须 `--build` 重建，否则容器报 Can't locate revision 循环重启）、带空格路径用 COPY JSON 数组、torch CPU 源分装、日志 10MB×3 轮转、DNS 污染时镜像源预拉取。
**追问**：多实例怎么扩展？→ 迁移移出容器启动（CI/CD 执行）；advisory lock 保证全局仅一个索引任务。
**代码**：`docker-compose.yml`、`Dockerfile`、`docs/DEPLOY.md`

## 13. 数据库如何备份和恢复？

**简答**：`pg_dump -Fc` 自定义格式（压缩+并行恢复友好）→ `pg_restore` 到目标库；脚本内置体积自检与临时验证库流程。

**本项目**：backup-db.sh（2.5MB dump 实测）→ restore-db.sh（恢复到 rag_restore_test 验证 417 行一致后清理）→ deploy-check.sh（容器/健康/迁移版本/索引状态/磁盘一键巡检，实测 ALL-PASS）；重启持久化前后快照一致。
**追问**：备份策略？→ 全量重建或重要上传后触发 + 生产每日 cron；pgdata 卷是持久层，`down -v` 才删。
**代码**：`scripts/backup-db.sh`、`scripts/restore-db.sh`、`scripts/deploy-check.sh`、`docs/DATABASE_BACKUP.md`

## 14. 如何评估 RAG 检索质量？

**简答**：检索质量看 Hit Rate/Recall@K/MRR/NDCG（排序位置敏感），生成质量看 faithfulness/答案正确性——检索命中 ≠ 答案正确，两层必须分开评。

**本项目**：13 用例 × 4 端点真实评测——vector MRR 0.962 / keyword 0.733 / hybrid 0.962 / rerank NDCG@5 0.963 最高但延迟最高；迁移前后同集对比（零回退）作为回归门禁；路由 48/48、rerank 阈值经分布实验校准。
**追问**：为什么 hybrid MRR 没超过 vector？→ 该语料上向量已经很强，RRF 融合主要贡献在鲁棒性（词面精确命中场景），指标持平即符合预期。
**代码**：`tools/eval_retrieval.py`、`tools/eval_routing.py`、`tools/eval_rerank_calibration.py`、`tests/golden/*.json`

## 15. SSE 如何实现流式输出？

**简答**：HTTP 长连接 `text/event-stream`，服务端按 `data: ...\n\n` 逐块推送；相比 WebSocket 单向更简单，自动走 HTTP 基础设施。

**本项目**：`POST /chat/stream` 事件序列 sources → token* → done（[DONE] 终止符）；LLM 侧 `llm.stream()` 逐 chunk；**断连语义**：客户端断开触发 GeneratorExit，finally 中落盘部分答案到会话记忆并跳过 yield（避免 generator ignored GeneratorExit 的 RuntimeError）；错误以 error 事件下发不中断已生成内容；前端 fetch + ReadableStream 逐块解析、失败自动回退非流式端点。
**追问**：为什么要跳过 finally 里的 yield？→ 生成器被 close 时 GeneratorExit 激活中再 yield 会抛 RuntimeError，断连路径只做副作用（写记忆）不产出。
**代码**：`backend/main.py::/chat/stream`、`backend/services/qa_service.py::chat_stream`、`frontend/src/api.js::submitRagStream`、`tests/integration/test_sse.py`

---

## 高频系统设计追问备用

- **如果语料到 100 万块怎么办？**：HNSW 生效（ef_search 调优）；BM25 语料内存化改为 PG tsvector 或外部索引；父块展开已批量查询；连接池按并发调优。
- **如果两个 Pod 同时部署？**：advisory lock 全局互斥索引任务；迁移移出容器启动；会话记忆需外置（Redis/PG）。
- **如何防止幻觉？**：rerank 阈值校准 + 证据不足拒答（NO_EVIDENCE）+ 私有内部问题禁止公网补料 + 提示词强制编号引用 + 历史对话不得作事实来源。
