# 第二阶段全项目审计报告（SECOND_REVIEW）

审计时间：2026-11-15。方法：重读 `feature/pgvector-migration` 全部代码与提交记录、重跑第一阶段测试（38/38 通过，报告属实）、EXPLAIN ANALYZE 实测、定向 grep 验证疑点。

**P0 结论：未发现数据安全、数据丢失或安全漏洞级问题。** 上传有扩展名/大小/文件名清洗防护、SQL 全参数化、无硬编码密钥、.env 已隔离、500 错误已通用化。以下为 P1-P3。

## P1（架构缺陷 / 并发 / 功能错误）

| # | 问题 | 位置 | 状态 |
| --- | --- | --- | --- |
| P1-1 | **async 端点阻塞事件循环**：`POST /documents/upload` 是 `async def`，但增量入库（嵌入 139 块 ≈ 分钟级 CPU + DB 写）是同步调用，阻塞期间整个服务无响应 | main.py:104 → rag_service.upload_document → pipeline | 已修复：入库移入线程池 |
| P1-2 | **AUTO 模式双重检索**：`auto_chat` 先 `retrieve_sources` 做证据判断，`qa_service.chat` 内部再检索一次——每次问答 2× embedding+RRF+rerank | chat/orchestrator.py:159,165；qa_service.chat | 已修复：检索结果透传 |
| P1-3 | **父块展开 N+1 查询**：`expand_children_to_parents` 对每个候选逐条 SELECT | pg_store.py | 已修复：单查询 IN 批量取回 |
| P1-4 | **evidence_checker 阈值 0.45 未校准**：bge-reranker-base 输出无界 logits，阈值形同虚设（routing 几乎必判"证据充分"） | routing/evidence_checker.py:11 | 已修复：实验校准（见 PERFORMANCE_REPORT §3） |
| P1-5 | **词表路由过拟合**：COMPANY_DOMAIN_WORDS 硬编码 'xx-200'、'客服平台' 等当前语料词，换语料即退化 | routing/feature_extractor.py | 已缓解：建路由评测集实测后调整（§路由评测） |
| P1-6 | **`/chat` 系端点 400 detail 直传 RuntimeError 文本**：可控范围内（均为项目自身消息），但 VersionError 等若经此路径会带内部细节 | main.py chat 系端点 | 已修复：白名单化 |

## P2（性能 / 代码质量）

| # | 问题 | 处理 |
| --- | --- | --- |
| P2-1 | `KeywordSearchService` 每次检索 2 条 SQL 做签名检查 | 已修复：签名检查加 1.5s TTL |
| P2-2 | `ShortTermMemory` 会话字典无上限（内存泄漏向量） | 已修复：LRU 上限 200 会话 |
| P2-3 | `/health` 的 database.detail 直传 DB 异常文本（可能含主机/用户信息） | 已修复：详情进日志，响应通用化 |
| P2-4 | 死代码：`backend/services/answer_route_service.py` shim 零引用 | 已删除 |
| P2-5 | 死配置：`PARENT_STORE_FILE`/`CHILD_STORE_FILE` 零引用；`_load_code_config` AST 读 legacy/rag.py 常量的 hack | 已删除，DeepSeek 配置仅环境变量 |
| P2-6 | 蓝绿旧版本无限保留（每次重建全量复制，存储线性增长；EXPLAIN 证实每版本 139 子块 × 3 版本） | 已修复：保留策略 + 管理 API（保留最近 N 个 retired，active 永不清理） |
| P2-7 | 数据库连接无 connect_timeout（坏网络下握手可挂起） | 已修复：connect_args connect_timeout=10 |
| P2-8 | 双前端 frontend/ 与 web/ 重复（783 行 × 2） | 记录不修：合并属于接口级重构，风险>收益，SSE 仅改 frontend/ |
| P2-9 | 多轮检索 query 直拼历史（稀释嵌入/BM25 信号） | 记录不修：属检索质量重构（query condense），列入 v2.1 |
| P2-10 | `route_logs.jsonl` / uvicorn 日志无轮转 | 已修复：容器日志轮转配置（compose logging max-size） |

## P3（可选优化，记录不动）

- 前端手工版本号 `?v=20260529-4`；Vue 走 unpkg CDN
- `build_llm` 每次调用新建 client（DeepSeek 调用量级下可接受）
- `web_search.py` DuckDuckGo HTML 解析脆弱（仅 fallback 链路使用）
- `ensure_bootstrapped` 内一处 raw SQL（常量字符串，无注入面）

## 已验证为"正确设计、不需修改"的疑点

1. **HNSW vs 精确扫描**：EXPLAIN ANALYZE（139 行）规划器选择 version_id 索引 + 精确 KNN 排序，执行 1.95ms——小规模下精确扫描优于 ANN 是正确行为；HNSW 索引保留规模化路径，不盲目强制。
2. **距离度量**：BGE-M3 归一化嵌入（normalize_embeddings=True）→ 余弦距离 `<=>` 匹配模型设计。
3. **蓝绿并发读**：切换为单条 UPDATE 原子操作；retired 版本数据保留，进行中的查询持有旧版本快照不受影响；无过早清理路径。
4. **并发索引**：进程内 RLock + 事务级 advisory lock + 任务行三重防护，多进程下 409 冲突语义正确（故障注入测试覆盖）。
5. **SQL 注入**：全部 ORM 参数化；仅有的 raw SQL 为常量字符串。
6. **路径穿越**：上传经 `Path(name).name` + 扩展名白名单 + `..` 无后缀必被拒（新增单测固化）。

## 文档与代码一致性抽查

- SCHEMA.md 与实际迁移一致（本轮新增保留策略字段时同步更新）
- DEPLOY.md 的 compose 命令与 docker-compose.yml 一致
- CHANGELOG 遗留问题清单与实际代码状态一致
