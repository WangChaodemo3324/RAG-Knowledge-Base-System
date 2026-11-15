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
| 5 | api 镜像 + 全栈 compose + DEPLOY 文档 | ✅ 完成 | 镜像构建+容器 healthy；发现并修复 onnxruntime 隐式依赖、COPY 路径语法 |
| 6 | 集成 / 故障注入测试全量真实运行 | ✅ 完成 | 11/11 通过（真实 PG）；发现 3 个真实缺陷并修复 |
| 7 | 文档汇总 + 代码自查 | ✅ 完成 | ARCHITECTURE/SCHEMA/DEPLOY/TEST_REPORT/CHANGELOG 全部产出 |

## 最终验证汇总（2026-11-15）

| 套件 | 结果 |
| --- | --- |
| 单元测试 | 27/27 ✅ |
| 集成/故障注入（真实 PG） | 11/11 ✅ |
| 检索回归 vs 基线（13 用例 × 4 端点） | 全过，mean_rank 逐位一致，零回退 ✅ |
| 容器全栈验证（tools/container_verify.py） | 9/9 ✅（含管理端认证、容器内蓝绿重建、版本切换） |
| 数据泄漏检查 | active 版本测试前后一致，零泄漏 ✅ |

分支共 7 个提交，main 未动，未推送远程。

## 当前完成度小结（2026-11-15 第二轮）

- 单元测试 **27/27 通过**（RRF/语义分块/路由特征/证据检查/路由决策/记忆/认证）
- 代码自查修复：db_health 不再触发重服务初始化；增量入库 try/except 冗余与误导注释清理；版本名加随机后缀防同秒冲突
- 回归工具升级：`--label`（新栈采集）+ `--compare`（与基线对比并检测 hit→miss 回退）
- main 分支仍为旧栈，分支回滚路径随时可用

## 环境阻塞记录（2026-11-15，已全部解除）

1. ~~Windows「虚拟机平台」未启用~~ → ✅ UAC 提权 dism 启用两功能 + hypervisorlaunchtype auto + 重启，全部生效（`scripts/enable-vm-platform.ps1`，transcript 实证"操作成功完成"×3）
2. ~~Docker Hub auth.docker.io DNS 污染~~ → ✅ 基础镜像经 daocloud 镜像源预拉取 + 本地 tag，构建不再依赖 Hub 鉴权

## 真实验证结果（2026-11-15，详见 docs/TEST_REPORT.md）

| 验证项 | 结果 |
| --- | --- |
| Alembic 真实迁移 | ✅ 5 表 + vector 扩展 + HNSW 索引 |
| 集成/故障注入测试 | ✅ 11/11（3 个真实缺陷被测试抓出并修复：bm25 迭代 bug、跨会话提交缺失、测试数据泄漏） |
| 检索回归 vs 基线 | ✅ 四端点 13/13 全过，mean_rank 逐位一致，零 hit→miss 回退 |
| v1 蓝绿构建 | ✅ 自动 bootstrap（v_20261114180105_c6c3，7 文档/30 父/139 子与旧栈一致） |
| PGVectorStore spike | ✅ 六项实证（依赖冲突/async-first/API 不稳/无外键/事务不可统一/UUID 限制）→ 自定义适配层定案 |
| 容器全栈验证 | 🔄 镜像构建中（基础镜像本地化后重试） |

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
