# 开发决策记录（DEVELOPMENT_DECISIONS）

记录关键决策、当时的选项、最终选择与理由。便于后来者理解"为什么是这样"。

## D-1. 存储选型：自研 SQLAlchemy 适配层，而非 langchain-postgres

- **时间**：V1 迁移期（六项实证，见 ARCHITECTURE §2）
- **选项**：langchain-postgres PGVectorStore / 原生 psycopg / SQLAlchemy + pgvector-python
- **决定**：SQLAlchemy 2.0 + pgvector-python 自定义适配层
- **理由**：依赖冲突（core≥1.2 vs 项目 0.3.x）是硬门槛；其单表通用 schema 无法表达版本/父子外键；sync API 在 0.0.19 实测不可用
- **代价**：约 400 行自维护存储代码（24 项集成/迁移测试覆盖）

## D-2. 版本策略：蓝绿行级切换，而非 collection-per-version

- **选项**：PG schema per version / 每版本独立 collection（旧 Chroma 方式）/ 行级 version_id + is_active 标志
- **决定**：行级版本 + 部分唯一索引（WHERE is_active）保证全库至多一个 active
- **理由**：切换 = 单条 UPDATE；外键级联保证一致性；retired 版本保留供回滚；不需要 DDL 操作
- **代价**：存储线性增长 → V2 增加 prune 端点（保留最近 N 个 retired）

## D-3. 嵌入加载：ONNX 直读而非 torch

- **理由**：bge-m3 仓库只有 pytorch_model.bin，torch<2.6 + 新 transformers 拒绝加载；ONNX 导出直接可用且推理更快
- **决定**：`BgeM3OnnxEmbeddings` 实现 LangChain Embeddings 接口（onnxruntime CPU，批量 8）
- **代价**：reranker（sentence-transformers CrossEncoder）仍依赖 torch

## D-4. 并发控制：三层防护而非任务队列

- **选项**：Celery/Redis 队列 / 仅任务表 / RLock+advisory lock+任务行
- **决定**：三层防护（进程内 RLock → 事务级 advisory lock → 唯一 running 任务行），409 冲突语义
- **理由**：单机规模不需要外部队列；PG 原生能力已足够；避免引入运维复杂度
- **验证**：故障注入 test_running_task_blocks_new_task、压测 4 并发重建恰一个成功

## D-5. 路由架构：规则优先 + LLM 兜底，而非纯 LLM 路由

- **决定**：feature_extractor（词表规则）→ evidence_checker（校准阈值）→ LLMRouter（仅规则无法判断时调用）
- **理由**：规则零成本零延迟覆盖高频模式；LLM 兜底保证泛化；V2 建立路由评测集（48/48）使规则可度量
- **已知局限**：词表仍有过拟合风险（SECOND_REVIEW P1-5 降级为已缓解）

## D-6. SSE 范围：知识库路径先行

- **决定**：`/chat/stream` 覆盖 DOCUMENT/AUTO_DOCUMENT 的 KB 检索路径；OPEN_CHAT/Agent 的流式暂缓
- **理由**：KB 路径是主用途且检索结果先于生成（sources 事件有真实数据）；路由编排（auto_chat 多分支）的流式需要事件流重设计，收益/风险比低
- **断连语义**：GeneratorExit → finally 落盘部分答案，不 yield（避免 RuntimeError）——由单测固化

## D-7. 密钥管理：环境变量唯一来源

- **决定**：V2 移除 legacy/rag.py AST 配置后门，DeepSeek 配置仅环境变量
- **理由**：死文件不能影响生产配置；.env 是唯一密钥面（gitignored）

## D-8. 证据阈值：0.25 而非 0.45（V2 校准）

- **数据**：正样本 min 0.462 / 负样本 max 0.082（tools/eval_rerank_calibration.py，golden 存档）
- **决定**：0.25 双侧等边距；0.45 距正样本最低分仅 0.012 过于贴边
- **附带**：纠正了 V1 报告"阈值形同虚设"的机制误判——实际 0.45 能拒绝负样本，问题只在余量
