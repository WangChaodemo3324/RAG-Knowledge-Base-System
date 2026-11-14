# 安全审计报告（V2）

审计时间：2026-11-15。范围：密钥管理、API 权限、注入面、文件上传、会话隔离、日志、容器。结论先行：**未发现硬编码密钥、注入漏洞或路径穿越**；发现 2 项需要运维侧动作的事项与 3 项记录在案的设计局限。

## 1. 密钥管理 ✅

- 全仓库 grep `sk-`/`tvly-`/`gho_`/`ghp_` 模式：无真实密钥（.env 已 gitignore；V1 阶段移除 legacy/rag.py 硬编码；V2 移除了 AST 读取 legacy 常量的配置后门）
- `.env.example` 仅占位符；`POSTGRES_PASSWORD` 示例值 `change_me_in_real_deployment` 要求部署时修改
- **轮换方案**：若怀疑 DeepSeek/Tavily key 泄露，在对应平台重新生成 → 更新本地 `.env` → `docker compose up -d api --build`（重建容器以注入新环境变量）。测试管理 key（`RAG_ADMIN_API_KEY`）仅用于本机测试环境，生产部署必须替换

## 2. API 权限 ✅（含 1 项运维提示）

- 管理端点（上传/重建/prune/清记忆）：`require_admin` 依赖，`secrets.compare_digest` 比较防时序攻击，401 响应含 `WWW-Authenticate`
- **运维提示**：`RAG_ADMIN_API_KEY` 留空 = 管理端点完全开放（本地开发便利性设计）。生产部署必须在 .env 设置强 key（DEPLOY.md 已标注）
- 未授权访问测试已覆盖：容器验证 9/9 中的 401/授权两用例 + 单元测试 3 例

## 3. 注入面 ✅

- SQL：全部 SQLAlchemy ORM 参数化；仅有的原生 SQL 为常量字符串（ensure_bootstrapped）与测试库的 DDL（受控测试环境、库名来自 uuid）
- 路径穿越：上传经 `Path(name).name` + 反斜杠/特殊字符清洗 + 扩展名白名单；`..`（无后缀）必被拒 —— 8 个新单测固化（tests/unit/test_upload_security.py）
- SSE/JSON 解析：Pydantic 强类型校验，非法 body 拒绝

## 4. 会话与记忆 ⚠️ 设计局限（记录）

- `session_id` 由客户端提供，无用户体系校验——知道他人 session_id 可读取其会话历史。当前为单机演示系统设计；多用户部署需引入认证（v2.1 建议）
- 记忆存储进程内存 + LRU 200 会话上限（V2 修复的泄漏向量）；重启即清空，无跨用户持久化面

## 5. 信息泄漏 ✅

- 500 → 通用文案 + 服务端日志（含 request_id）；`/health` 的 database.detail 已脱敏（仅日志）；/chat 400 仅透出项目自身可控的 RuntimeError 消息
- 日志内容：结构化日志包含用户查询文本（运营可见），不包含任何密钥

## 6. CORS ⚠️

- 现状：`allow_origins=["*"]` 且 `allow_credentials=False`——无 cookie 凭证面，浏览器侧脚本可读公开端点响应
- 建议（v2.1）：改为环境变量白名单（如 `RAG_CORS_ORIGINS=http://localhost:8012`）

## 7. 容器 ✅（含 1 项记录）

- 容器以 root 运行（Windows bind mount 的属主映射限制）；缓解：bind mount 仅 `resource data` 目录，代码/依赖只读层
- 镜像无密钥烘焙（env 运行时注入）；`docker-compose.yml` 无 `privileged`；数据库端口仅映射宿主 5433
- 日志轮转：json-file 10MB × 3（V2 修复磁盘占满风险）

## 8. 发现汇总

| # | 级别 | 事项 | 状态 |
| --- | --- | --- | --- |
| S-1 | 提示 | 生产部署必须设置 RAG_ADMIN_API_KEY 与 POSTGRES_PASSWORD | DEPLOY.md 已标注 |
| S-2 | 提示 | CORS 白名单化 | v2.1 建议 |
| S-3 | 局限 | session_id 无用户体系隔离 | 设计局限，多用户前需认证层 |
| S-4 | ✅ | 上传安全（穿越/后缀/大小）8 单测固化 | 已完成 |
| S-5 | ✅ | 管理端点防时序比较 + 401/授权实测 | 已完成 |
