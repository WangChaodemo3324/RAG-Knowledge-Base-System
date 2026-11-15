# 简历项目描述（RESUME_PROJECT_DESCRIPTION）

以下三档长度，按简历空间选用。**所有数字均为仓库真实测试产出**（见 docs/TEST_REPORT.md、tests/golden/），无虚构数据。

---

## 一行版（简历项目列表）

**企业知识库 RAG 问答系统**（Python/FastAPI/PostgreSQL+pgvector/LangChain/Docker）：蓝绿索引零停机重建、混合检索+交叉编码器精排、SSE 流式输出、PostgreSQL advisory lock 并发控制；64 项自动化测试（含故障注入与并发压测）全部通过，检索 HitRate 100%。

## 三行版（项目经历详述）

**企业知识库 RAG 问答系统** — 个人全栈项目
- 设计并实现 PostgreSQL + pgvector 蓝绿索引管线：行级版本 + 部分唯一索引原子切换，构建-校验-切换三阶段与任务心跳恢复，10+2 项故障注入测试验证"永不先删后建"；并发压测中重建期间 180 次检索零失败
- 实现 BGE-M3 向量 + jieba BM25 → RRF 融合 → CrossEncoder 精排的混合检索链路，rerank 阈值经真实分数分布实验校准（正样本 min 0.462 / 负样本 max 0.082），检索 HitRate 100%、NDCG@5 最高 0.963
- 工程化：SSE 流式问答（断连落盘部分答案）、Advisory Lock 并发控制（409 冲突语义）、结构化日志/限流/安全审计、Docker Compose 备份恢复与部署巡检脚本、GitHub Actions CI（lint/单元/集成/镜像构建）

## 面试展开要点（STAR 备查）

- **S（情境）**：教学级 RAG 项目依赖嵌入式向量库，重建"先删后建"存在数据损坏窗口，索引/元数据/版本无事务边界
- **T（任务）**：在保留检索算法的前提下，将存储与部署升级到可交付标准
- **A（行动）**：
  1. 用真实原型否决 langchain-postgres（依赖冲突等六项实证），自研 SQLAlchemy + pgvector 适配层
  2. 设计蓝绿版本管线：building→校验→原子切换→retired 保留，配任务心跳解决"崩溃任务 vs 活跃任务"区分问题
  3. 建立评测体系（检索指标/路由 48 用例/rerank 分布实验），让每个优化有数据背书
- **R（结果）**：64/64 自动化测试、压测零错误、检索零回退、备份恢复实测一致；全部决策与数据可追溯到仓库内文档与 golden 存档

---

### 使用注意

- 面试中如被问"生产用户量/并发规模"：如实说明这是**个人工程化项目**，压测数字（20 并发/180 重建期读取）来自本地 Docker 环境，不代表生产容量
- 技术栈关键词：FastAPI、SQLAlchemy 2.0、Alembic、pgvector、HNSW、BM25、RRF、CrossEncoder、蓝绿部署、Advisory Lock、SSE、Docker Compose、Pytest、GitHub Actions
