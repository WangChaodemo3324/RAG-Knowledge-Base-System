# 面试指南 V3 补充（产品化与生产交付专题）

V2 的 15 个基础专题见 `INTERVIEW_GUIDE.md`。本篇覆盖 V3 新增能力，同样全部锚定真实代码。

## 16. 文档删除如何保证"前后端一致"？

**简答**：删除不是单表操作——索引行（子/父块级联）、文档记录、任务状态、BM25 语料、源文件必须协调。项目用一个事务覆盖全部索引行，源文件**移入 `.trash/` 目录**（同卷原子 rename，可恢复）而非直接删除。

**本项目**：`pipeline.delete_document` 在事务内完成任务创建 → `pg_store.delete_document`（document 行删除，ON DELETE CASCADE 级联父子块）→ 源文件 replace 到 `.trash/` → 任务完成。BM25 无需手动清理：语料签名 `(version_id, child_count)` 变化触发自动重建。未知文档 → `DocumentNotFoundError` → HTTP 404；索引任务冲突 → 409。
**追问**：为什么源文件用移动而非删除？→ 删除是不可逆操作，trash 目录保留恢复窗口；定期清理 trash 属运维决策。
**代码**：`backend/indexing/index_pipeline.py::delete_document`、`backend/indexing/pg_store.py::delete_document`、`tests/integration/test_document_lifecycle.py`

## 17. 限流怎么做的？为什么不用 Redis？

**简答**：单机部署用进程内滑动窗口（per-IP + bucket）足够；Redis 只在多实例共享计数时才有必要——本项目单实例，引入 Redis 是负优化。

**本项目**：`backend/core/rate_limit.py`——general 桶 120/min、admin 桶 20/min（`RAG_RATE_LIMIT_PER_MIN` 可配，0 关闭）；X-Forwarded-For 取真实客户端 IP；内存周期清扫防泄漏；超限返回 429 + Retry-After。中间件只对 POST/DELETE/PUT 生效，健康检查豁免。
**追问**：多实例部署怎么办？→ 计数移到 PG（表或 advisory）或 Redis；语义不变。
**代码**：`backend/core/rate_limit.py`、`tests/unit/test_rate_limit_and_metrics.py`（429/Retry-After/桶隔离/XFF 共 7 用例）

## 18. 可观测性怎么平衡"够用"与"过度建设"？

**简答**：先问消费方是谁——单机项目要的是"出问题能定位、容量有依据"，不是完整监控平台。进程内计数器 + 分位数窗口 + PostgreSQL 任务统计已经覆盖请求量/错误率/各阶段延迟。

**本项目**：`/metrics` JSON 端点输出 uptime、请求总数与状态分布、错误率、per-route 延迟 p50/p95、检索各阶段耗时（embedding/vector/bm25/rerank，在代码发生处埋点）、索引任务成功率（从 PG 实时查询）。无 Prometheus/Grafana 容器——部署成本与收益不成比例，接口预留（数据结构即 Prometheus 文本格式的前身）。
**追问**：什么时候升级 Prometheus？→ 需要历史趋势、告警路由、多实例聚合时。
**代码**：`backend/core/metrics.py`、`backend/main.py`（middleware observe + /metrics）、`tests/unit/test_rate_limit_and_metrics.py::TestMetricsEndpoint`

## 19. 生产 compose 与开发 compose 怎么分离？

**简答**：开发要便利（DB 端口映射、宽松变量），生产要强制（密钥缺失即拒绝启动、最小攻击面）。两份 compose 文件 + `:?` 必填变量语法。

**本项目**：`docker-compose.prod.yml`——`POSTGRES_PASSWORD:?` / `RAG_ADMIN_API_KEY:?` / `RAG_CORS_ORIGINS:?` 强制注入；**DB 不发布端口**（仅容器网络可达）；api 只绑 `127.0.0.1`（公网经反向代理+TLS）；容器内存限制；prod 自包含 YAML 锚点。镜像漂移教训写入文档：新增迁移后必须 `--build`。
**追问**：api 为什么只绑回环？→ TLS 终结交给反向代理；应用容器不应直接暴露公网明文端口。
**代码**：`docker-compose.prod.yml`、`docs/DEPLOY.md`

## 20. CI 流水线怎么设计？本地怎么等价验证？

**简答**：PR 检查（lint → 单元 → 集成）分层失败前置；集成用 GitHub Actions service 容器（pgvector/pgvector:pg16）+ 独立测试数据库；Docker 构建不开推送权限。

**本项目**：三个工作流——backend-ci（ruff → pytest unit → pg16 service + 迁移升级/降级循环 + 集成测试）、frontend-ci（node --check 语法 + CDN 导入守卫）、docker-build（buildx + GHA 缓存 + 镜像内容 smoke）。**本地等价命令全部真实执行过**：`ruff check` 全绿、pytest 64/64、`node --check` 通过、`docker compose config` 渲染验证。坑：ruff 未配 target-version 会把 `timezone.utc` 自动改成 Python 3.11+ 的 `UTC`——已在 `ruff.toml` 固定 py310。
**追问**：为什么 CI 里不跑真实 LLM 冒烟？→ 确定性原则：CI 用 Mock LLM 边界，真实 API 只手动冒烟，避免额度消耗与不稳定断言。
**代码**：`.github/workflows/backend-ci.yml`、`ruff.toml`、`tests/conftest.py`（即弃数据库机制）
