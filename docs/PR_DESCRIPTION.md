# PR 描述：RAG 知识库系统 — PostgreSQL + pgvector 产品化改造（V1→V3.5）

> 复制以下内容到 PR 描述框（Compare & pull request 或 `gh pr create`）。

---

## Summary

将教学级 Chroma RAG 项目重构为**生产级企业知识库系统**：存储层迁移至 PostgreSQL 16 + pgvector（蓝绿索引管线），检索链路保留并经实验校准，补齐 SSE 流式、文档生命周期、安全加固、可观测性、CI/CD 与完整验收测试。

**38 commits | 128 files | +8931/-2578 | 测试 79/79**

## 主要改造

### V1 — 存储迁移（Chroma → PostgreSQL + pgvector）
- 五表模型（index_versions / documents / parent_chunks / child_chunks / index_tasks）+ Alembic 双迁移（含 pgvector 扩展与 HNSW 索引）
- 蓝绿索引管线：building → 校验 → **原子切换** is_active → retired 保留；**永不先删后建**
- 选型实证：langchain-postgres PGVectorStore 六项缺陷否决（依赖冲突 / async-first / API 不稳 / 无外键 / 事务不可统一 / UUID 强制），自研 SQLAlchemy 适配层

### V2 — 深度工程优化
- 修复 8 个真实缺陷（事件循环阻塞 / 双重检索 / N+1 / init 竞态 / 恢复误杀 / 空版本校验缺失 / jsonb 契约 / rerank 阈值贴边）
- PostgreSQL Advisory Lock 三层并发防护（409 冲突语义）；任务心跳恢复
- rerank 阈值实验校准 0.45→0.25（正样本 min 0.462 / 负样本 max 0.082）

### V3 — 产品化与生产交付
- 文档生命周期 API：列表 / 删除（源文件 .trash 可恢复）/ 重试 / 批量上传（逐文件失败隔离）
- SSE 流式问答（断连落盘部分答案）+ 前端流式优先非流式兜底
- 安全：CORS 白名单、管理端点 API Key、进程内限流（429）、JSON 日志 + request_id
- 可观测性：/metrics（请求统计 / 路由延迟 / 四阶段耗时 / 任务成功率）
- 部署：双 compose（dev/prod）、备份恢复脚本、deploy-check 巡检、HF 缓存自举 entrypoint
- CI：三工作流（backend lint/单元/集成含 pgvector service、frontend 语法守卫、docker buildx）

## 测试结果（全部真实执行）

| 套件 | 结果 |
| --- | --- |
| 单元测试 | 42/42 |
| 集成 / 故障注入 / 迁移（独立 rag_test 库） | 34/34 |
| SSE（Mock LLM + 断连语义） | 4/4 |
| **合计** | **79/79** |
| 路由评测 | 48/48 |
| 检索回归（13 用例 × 4 端点 vs 迁移前基线） | 零回退 |
| 检索评测（V3.5 四类 12 用例） | 有答案类全命中；无答案拒答由链路层保证（分数分布实验） |
| 容器全栈 + 真实浏览器 UI | 端到端通过（流式 883 字符 + 引用渲染） |
| 并发压测 | 20 并发检索 0 错误；重建期 180 读取 0 失败 |

## 已知限制

- 多用户认证未实现（单用户定位；升级路径见 docs/DEVELOPMENT_DECISIONS.md D-9）
- 多轮检索 query condense 未做；BM25 为内存语料（规模化需迁移 PG tsvector）
- Faithfulness 批量评估需真实 LLM 逐条调用（框架已预留，未批量执行）
- CI 集成 job 首次在 GitHub 环境运行（本地等价命令已全过），如失败按日志修正

## 部署注意事项

- 首次部署必须设置：`POSTGRES_PASSWORD`、`RAG_ADMIN_API_KEY`、`DEEPSEEK_API_KEY`、`RAG_CORS_ORIGINS`（prod compose 缺失即拒绝启动）
- 模型缓存：首启经 `HF_ENDPOINT`（国内建议 hf-mirror）下载 ~3.4GB 到 `hf_cache` 卷；缓存齐全后设 `HF_HUB_OFFLINE=1` 稳定离线运行
- 宿主机新增 Alembic 迁移后必须 `docker compose up -d api --build`（避免镜像迁移漂移）
- 详细文档：`docs/DEPLOY.md`、`docs/DATABASE_BACKUP.md`、`docs/ARCHITECTURE.md`、验收报告五份
