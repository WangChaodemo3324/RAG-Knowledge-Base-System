# PGVector 迁移进度文件

分支：`feature/pgvector-migration`（main 不动，不推远程）
目标：Chroma + JSON 存储 → PostgreSQL + pgvector 统一存储，Docker Compose 部署，完整测试与文档。

## 已确认决策

| 决策点 | 结论 |
| --- | --- |
| API Key 认证范围 | 仅管理端点（上传/重建/清记忆），检索与问答开放 |
| 自动化测试 | 确定性测试（不调用 DeepSeek API），LLM 链路手动冒烟 |
| 旧 Chroma/JSON 代码 | 分支上干净替换，回滚靠切回 main（旧数据文件磁盘保留不碰） |
| 向量库选型 | 先评估 langchain-postgres PGVectorStore；预计采用 SQLAlchemy 2.0 + pgvector-python 自定义适配层（理由见架构文档） |
| embedding 维度 | BGE-M3 dense = 1024，pgvector Vector(1024) + HNSW vector_cosine_ops |

## 阶段状态

| Phase | 内容 | 状态 | 备注 |
| --- | --- | --- | --- |
| 0 | 回归基线采集 | ✅ 完成 | 13 用例 × 4 端点全命中，见下 |
| 1 | DB 层（compose db / models / alembic / 适配层 / 选型评估） | 🔶 代码完成，**被环境阻塞** | models/迁移/适配层/测试已写好；Docker 因 Windows 虚拟机平台未启用无法启动 |
| 2 | 版本化索引管线 + BM25 数据源切换 | 🔶 代码完成，待 DB 验证 | index_pipeline.py（蓝绿构建/增量事务交换/恢复）、KeywordSearchService 已切 PG |
| 3 | 检索切换对接 PG，回归过基线 | 🔶 代码完成，待 DB 验证 | KnowledgeBase/hybrid/rag_service 已重写，旧 Chroma/JSON 模块已删除 |
| 4 | 认证 / 结构化日志 / 异常 / 并发控制 | 🔶 代码完成，待验证 | auth.py/logging.py/main.py 重写（409/500/X-Request-ID/管理端点守卫） |
| 5 | api 镜像 + 全栈 compose + DEPLOY 文档 | 待开始 | |
| 6 | 集成 / 故障注入测试全量真实运行 | 待开始 | 阻塞同 Phase 1 |
| 7 | 文档汇总 + 代码自查 | 待开始 | |

## 环境阻塞记录（2026-11-15）

Docker Desktop 已安装（29.6.1）但引擎无法启动：
`Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_SERVICE_NOT_AVAILABLE`
- BIOS 虚拟化已开启（HyperVRequirementVirtualizationFirmwareEnabled=True）
- 但 Windows「虚拟机平台」功能未启用：vmcompute 服务不存在，hypervisor 未运行（HyperVisorPresent=False）
- 修复需要管理员 PowerShell + 重启；等用户确认后继续

## Phase 0 结果（2026-11-15）

运行环境：`.conda-py310`（py3.10.20，已补装 fastapi/pypdf/jieba/rank-bm25/python-multipart/tavily-python）
当前栈索引规模：12 个 loader 文档（6 源文件，PDF 按页拆分）/ 30 parents / 139 children

基线指标（`tests/golden/baseline_retrieval.json`）：

| 端点 | hit | mean_rank(hits) | 备注 |
| --- | --- | --- | --- |
| /search (vector) | 13/13 | 1.077 | |
| /keyword-search (BM25) | 13/13 | 1.692 | |
| /hybrid-search (RRF) | 13/13 | 1.077 | |
| /rerank-search | 13/13 | 1.077 | 首调 38s 含 CrossEncoder 冷加载 → 后续阶段需预热 |

## 已知问题（记录后继续）

- 重排序模型懒加载导致首查询卡顿（Phase 5 启动预热解决）
- 现有 full_rebuild 先删后建（迁移目标即是修复此缺陷）
- chromadb/langchain-community Chroma 弃用警告（本迁移消除）
