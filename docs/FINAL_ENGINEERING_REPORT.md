# 最终工程报告（FINAL ENGINEERING REPORT）— V2.0 深度优化

分支 `feature/pgvector-migration`，V2 阶段共 12 个提交（V2-1 ~ V2-14b），main 未动，未推送远程。

## 1. 实际完成的功能（全部已实现 + 已测试 + 已验证）

| 项 | 状态 | 证据 |
| --- | --- | --- |
| 全项目二次审计 | ✅ | docs/SECOND_REVIEW.md（P0=0、P1=6、P2=10、P3 记录；含 1 项 V1 误判勘误） |
| 独立测试数据库 | ✅ | 每用例 rag_test_<uuid> 即建即弃 + 真实迁移；故障注入零接触正式库 |
| P1/P2 修复（14 项） | ✅ | 事件循环阻塞、双重检索、N+1、签名 TTL、记忆 LRU、/health 脱敏、死代码、版本保留 prune、日志轮转、connect_timeout 等 |
| PG/pgvector 深度检查 | ✅ | EXPLAIN ANALYZE（1.95ms 精确 KNN，规划器行为正确）；迁移测试升级/降级循环；**发现并修复 json→jsonb 契约不符（迁移 0002）** |
| 蓝绿故障注入（10+2 场景） | ✅ | PDF 降级、嵌入全挂拒空版本、写失败回滚、切换前后崩溃、并发串行化、BM25 快照一致性、重复重建零重复 |
| 并发压测 | ✅ | 20 并发检索 0 错误；重建期 180 次读取 0 失败；**发现并修复 2 个并发 P1**（init 竞态、恢复误杀） |
| RAG 质量 | ✅ | rerank 阈值校准 0.25（分布实验）；路由评测 48/48；检索指标四端点 HitRate 100% |
| SSE 流式 | ✅ | /chat/stream + 前端流式/兜底 + 4 测试（含断连语义）+ **真实 DeepSeek 冒烟（567 tokens 流式）** |
| Docker 可靠性 | ✅ | 备份/恢复实测（2.5MB→417 行一致）、重启持久化、deploy-check ALL-PASS、镜像漂移修复 |
| 安全审计 | ✅ | docs/SECURITY_AUDIT.md（S-1~S-5）；上传安全 8 单测 |
| 自动化测试 | ✅ | **64/64**（单元 35 + 集成/故障注入/迁移/SSE 29） |
| 文档 | ✅ | ARCHITECTURE/SCHEMA/DEPLOY/TEST_REPORT/CHANGELOG 更新 + 新增 SECOND_REVIEW/PERFORMANCE_REPORT/SECURITY_AUDIT/DATABASE_BACKUP/INTERVIEW_GUIDE/DEVELOPMENT_DECISIONS |

## 2. 修改的核心文件

- `backend/indexing/`：pg_store.py（N+1 修复、心跳恢复、prune）、index_pipeline.py（空版本拒绝、session 注入、心跳）
- `backend/services/`：rag_service.py（线程池上传、双检锁）、qa_service.py（precomputed_sources、chat_stream）、keyword_search_service.py（PG 语料+TTL）、memory_store.py（LRU）、evidence_checker.py（0.25）、feature_extractor.py（指代标记）、main.py（SSE/prune/脱敏/线程池）
- `backend/db/models.py` + `migrations/0002`：JSONB 契约对齐
- `tests/`：conftest（隔离 DB）、test_blue_green_faults.py、test_migrations.py、test_sse.py、test_upload_security.py（新增 5 个文件）
- `tools/`：eval_rerank_calibration.py、eval_routing.py、eval_retrieval.py、stress_perf.py、container_verify.py、baseline_capture.py（对比模式）
- `Dockerfile`、`docker-compose.yml`（日志轮转）、`scripts/backup-db.sh`、`restore-db.sh`、`deploy-check.sh`、`enable-vm-platform.ps1`
- `frontend/src/api.js`、`App.js`（SSE）

## 3. Git Commit 清单（V2 阶段，按序）

```
V2-1: 二次审计报告 SECOND_REVIEW + EXPLAIN 实测 + 第二阶段计划
V2-2: 独立测试数据库 + env.py URL 覆盖 bug + str(url) 密码掩码陷阱 + IPv6 环境记录
V2-3: P1/P2 修复批一（10 项）
V2-4: Alembic 迁移测试（含 jsonb 契约修复 0002）
V2-5: 蓝绿故障注入 10 场景 + 空版本拒绝修复
V2-7: RAG 质量评测（校准/路由/指标）
V2-8: SSE 流式
V2-9: Docker 可靠性
V2-10: 安全审计
V2-13: import 清理 + README
V2-6: 并发压测修复（init 竞态 + 心跳恢复）
V2-14a/b/c: 文档 + 最终回归
```

## 4. 测试实际执行结果

| 套件 | 结果 |
| --- | --- |
| 单元测试 | 35/35 |
| 集成/故障注入/迁移（真实 PG，独立库） | 30/30 |
| SSE（Mock LLM + 断连语义） | 4/4 |
| **合计** | **69/69** |
| 检索回归（13 用例 × 4 端点 vs 基线） | 零回退 |
| 路由评测 | 48/48 |
| 容器全栈验证 | 9/9 |
| 真实 DeepSeek SSE 冒烟 | 通过（567 tokens） |

## 5. 性能数据（摘要，详见 PERFORMANCE_REPORT）

- 检索延迟：vector 506ms / BM25 127ms / hybrid 326ms / rerank 9.4s（含冷加载）
- Rerank 分数分离度：正 min 0.462 / 负 max 0.082 → 阈值 0.25
- 并发：20 请求 0 错误；重建期 180 读取 0 失败；重建串行化正确
- 嵌入吞吐：2.2 texts/s（CPU ONNX）；全量重建嵌入 ~64s

## 6. 安全审计结果

无硬编码密钥、无注入、无路径穿越（8 单测固化）、管理端点防时序比较、错误脱敏。运维提示与设计局限见 docs/SECURITY_AUDIT.md（CORS 白名单化、session 认证为 v2.1 建议）。

## 7. 未解决的问题 / 阻塞（诚实清单）

| # | 事项 | 状态 |
| --- | --- | --- |
| U-1 | 双前端合并（frontend/ 与 web/ 重复 783 行） | 记录不修：接口级重构风险 > 收益 |
| U-2 | 多轮检索 query condense（历史直拼稀释检索信号） | v2.1 建议 |
| U-3 | CORS 白名单化、session 用户认证 | v2.1 建议（多用户部署前必须） |
| U-4 | p95 长尾（20s 单次容器 CPU 抖动） | 记录；建议请求级超时 |
| U-5 | 宿主机内存紧张时 CrossEncoder 偶发 meta-tensor 加载失败 | 已观测+文档；生产建议独立推理进程 |
| U-6 | route_logs.jsonl 仍为文件日志（未入库） | 可接受，量小 |

## 8. 仍需人工完成的事项

1. 生产部署前：设置强 `RAG_ADMIN_API_KEY` 与 `POSTGRES_PASSWORD`（.env）
2. 决定分支合入 main / 推送远程（未授权，未执行）
3. 真实 LLM 全链路的长期使用验证（本次仅 1 次冒烟调用）

## 9. 下一阶段建议（v2.1）

1. query condense（多轮检索改写）+ 生成质量评测（faithfulness）
2. SSE 扩展到 OPEN_CHAT/Agent 路径
3. CORS 白名单 + 用户认证层
4. 语料规模化：HNSW 参数调优 + BM25 迁移 PG tsvector
5. CI：GitHub Actions 跑 pytest（unit 全量 + integration 需自建 PG service）
