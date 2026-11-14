# 第二阶段执行计划（V2.0 深度工程优化）

分支：`feature/pgvector-migration`（继续，不合 main，不推送）

## 执行顺序（按依赖关系）

| # | 模块 | 内容 | 状态 |
| --- | --- | --- | --- |
| 0 | 现状核实 | 重跑第一阶段全部测试，验证报告真实性 | ✅ 38/38 |
| 1 | 全项目二次审计 | docs/SECOND_REVIEW.md（P0-P3 分级） | |
| 2 | 独立测试数据库 | rag_test 库 + conftest fixture（故障注入不碰正式库） | |
| 3 | P1 修复 | 审计发现的架构/并发/阻塞问题 | |
| 4 | PG 深度检查 | EXPLAIN ANALYZE、N+1、约束、迁移测试、连接池 | |
| 5 | 蓝绿故障注入 | 10 项故障场景（PDF/嵌入/写库/回滚/崩溃/并发） | |
| 6 | 并发压测 | 并发上传/重建/检索 | |
| 7 | RAG 质量 | rerank 阈值实验、路由评测集、检索评测框架（Recall/MRR/NDCG） | |
| 8 | SSE 流式 | 独立流式端点 + 前端 + Mock LLM 测试 | |
| 9 | Docker 可靠性 | 备份/恢复脚本+实测、重启持久化验证、部署检查脚本 | |
| 10 | 安全审计 | docs/SECURITY_AUDIT.md + 修复 | |
| 11 | 性能基准 | docs/PERFORMANCE_REPORT.md（真实数据） | |
| 12 | 自动化测试补全 | 迁移/并发/权限/上传安全/SSE/备份恢复测试 | |
| 13 | 重构 | 去重/类型注解/死代码（每步跑回归） | |
| 14 | 文档 | INTERVIEW_GUIDE / DEVELOPMENT_DECISIONS / FINAL_ENGINEERING_REPORT | |

## 约束

- 不引入 Redis/Kafka/Celery；PG 能做的用 PG
- 故障注入一律在 rag_test 库；正式库只读操作（EXPLAIN/SELECT）
- 不推送、不合 main、不动 Docker Volume、不公开密钥
- 每模块一个 commit，实时更新 PROGRESS_V2.md
