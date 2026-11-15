# 最终验收报告（FINAL ACCEPTANCE REPORT）— V3.5

验收时间：2026-11-15。分支 `feature/pgvector-migration`（30+ commits）。原则：**每条结论都有本机真实执行记录**，无法执行的项目如实标注。

## 一、总体验收结论

| 验收域 | 结论 |
| --- | --- |
| 安全与 Git 审计 | ✅ 通过（git 全历史 0 密钥；CORS 白名单化；限流 7 测试；上传安全 8 测试） |
| 文档生命周期 | ✅ 通过（上传/批量/删除/重试/列表/状态全链路 5+3 项测试 + 容器内真实闭环） |
| RAG 评测 | ✅ 通过（四类 12 用例：精确 4/4、跨段落 3/3、多文档 2/2、无答案职责分层澄清） |
| PostgreSQL 深度审查 | ✅ 通过（EXPLAIN 1.225ms 精确 KNN 正确；版本膨胀→prune 策略已落地） |
| 前端完整性 | ✅ 通过（**真实浏览器 UI 验证**：挂载/流式/引用/文档管理；发现并修复 3 个真实缺陷） |
| 部署验收 | ✅ 通过（修复 4 个容器级缺陷后端到端全通；见 DEPLOYMENT_ACCEPTANCE_REPORT.md） |

## 二、本阶段发现并修复的真实缺陷（7 个）

| # | 缺陷 | 发现方式 | 修复 |
| --- | --- | --- | --- |
| F-1 | App.js 仍从 unpkg 导入 Vue 符号——CN 网络 CDN 不可达 → **页面白屏**（V2 审计 P3 隐患真实爆发） | 真实浏览器 UI 测试 | Vue 本地 vendor 化 + CI 守卫改为"禁止 CDN 导入" |
| F-2 | `failedNames.join("\n")` 被 python 补丁写成**真实换行**（单引号字符串内换行 = SyntaxError，node --check 却通过——Node/Chrome 解析差异） | 浏览器动态 import 抓取 SyntaxError | 修复字符串 + 提交规范：python 补丁一律用 Edit 工具强校验 |
| F-3 | `loadInfo` 在 SSE 进行中返回并**覆盖对话记录**（时序竞争） | UI 测试（回答渲染后消失） | busy 期间禁止重置消息 |
| F-4 | `HF_ENDPOINT` 空字符串 → huggingface_hub "No scheme supplied" → **容器内 rerank 加载必然失败**（此前从未在容器内成功触发） | UI 测试 | compose 默认值 `https://huggingface.co` |
| F-5 | Windows→Linux 9P bind mount 上 torch mmap 加载大 safetensors 失败（meta tensor），宿主机正常——**决定性实验**：复制到容器本地 FS 后加载成功（meta: False） | 容器内分路径加载对照 | HF 缓存改 hf_cache 具名卷 + entrypoint 自举（一次性从宿主机缓存复制） |
| F-6 | transformers 4.57 尝试联网拉取模型仓库新增的 `additional_chat_templates` 文件，mirror 不可达即失败 | 离线加载成功 vs 在线失败对照 | 缓存齐全时 `HF_HUB_OFFLINE=1` 强制离线（compose 透传） |
| F-7 | 批量测试将测试语料写入正式知识库目录并被误提交 | 全量回归（blue-green 文件计数断言失败） | 测试自清理化（DELETE 断言防静默泄漏）+ 正式库/目录/git 三层清理 + 蓝绿测试改动态计数 |

## 三、各模块要点

**安全**：git 全历史（含已推送的 main 初始提交）扫描 0 密钥——硬编码密钥在首次 git init 前已移除，从未入库；CORS 白名单（`RAG_CORS_ORIGINS` 强制变量进 prod compose）；限流 429+Retry-After 实测；认证决策维持 D-9（单用户定位，升级路径文档化）。

**文档生命周期**：批量上传为 V3.5 新增（多文件独立入库、逐文件失败隔离、汇总反馈、前端 multiple 多选）；删除/重试/列表沿用 V3；一致性验证——上传后 `/documents` 状态、chunk 数、源文件存在性三处一致；删除后索引行/git/磁盘三层清理（`.trash` 可恢复）。

**PostgreSQL**：EXPLAIN ANALYZE 确认精确 KNN 1.225ms（139 块规模规划器正确绕开 HNSW）；发现 retired 版本累积（父块表 300 行 = 10 版本×30）→ 建议定期 `POST /index/prune`；连接池/事务/MVCC 结论维持 V2（心跳恢复 + 三层并发防护实测有效）。

**RAG 评测**：12 用例四类别——精确 4/4、跨段落 3/3、多文档 2/2 全命中；无答案场景澄清职责分层：检索端点返回候选是本职，**拒答决策在问答链路**（rerank 分数 0.082 < 校准阈值 0.25 → evidence_checker 拒答，rerank_calibration 实验数据支撑）。Faithfulness/Answer Relevance 属生成层指标，需真实 LLM 逐条评估——已预留手动冒烟路径，不做批量 API 消耗。

**部署**：全新重建容器 → healthy → 上传/删除/检索/SSE 全链路容器内验证 + 真实浏览器 UI 验证。HF 缓存自举机制（entrypoint + hf_cache 卷）解决了 Windows 9P mmap 与 CN 网络 CDN 两个部署 blockers。

## 四、无法执行/遗留（诚实清单）

| # | 事项 | 原因 |
| --- | --- | --- |
| U-1 | CI 的 GitHub 环境首跑 | 分支已推送，PR 未创建（等用户指令）；本地等价命令全过 |
| U-2 | Faithfulness/Answer Relevance 批量评估 | 需真实 LLM 逐条调用（付费 API 批量实验被禁止）；已留单次冒烟路径 |
| U-3 | 多用户认证 | D-9 决策：单用户定位 |
| U-4 | HNSW 在百级块规模的优势验证 | 当前 139 块精确扫描更快且正确；规模化后自然生效 |
| U-5 | 容器内 rerank 的 meta tensor 残留风险 | 已有 transformers fallback 兜底（本次修复），双路径任一可用 |

## 5 份专项报告

- `SECURITY_FINAL_REPORT.md` — 安全终审
- `DATABASE_FINAL_REPORT.md` — 数据库终审
- `RAG_EVALUATION_REPORT.md` — 评测终稿
- `DEPLOYMENT_ACCEPTANCE_REPORT.md` — 部署验收
- `docs/V3_FINAL_REPORT.md`（上轮）与本文构成完整交付链
