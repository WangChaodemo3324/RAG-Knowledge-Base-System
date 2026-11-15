# V3.0 执行计划（产品化与生产交付）

分支：`feature/pgvector-migration`（继续，不合 main，不推送）

## 模块顺序（按依赖关系）

| # | 模块 | 内容 | 状态 |
| --- | --- | --- | --- |
| 0 | 现状核实 | 测试/容器/前端差异 | ✅ 35/35，web/=旧变体（components 相同，App/api/main/index 有差异且缺 V2 更新） |
| 1 | 文档管理后端 | 删除/重试/状态/列表端点 + BM25/PG 协调 + 测试 | |
| 2 | 安全完善 | CORS 白名单化、限流、认证决策文档 | |
| 3 | 可观测性 | 轻量 /metrics 端点 + 阶段耗时（不引入监控容器） | |
| 4 | 前端产品化 | 基于 frontend/ 产品化（文档列表/删除/进度/重试/空态/错误态），web/ 验证后移除 | |
| 5 | CI/CD | GitHub Actions 工作流（本地验证 YAML + 等价命令） | |
| 6 | 备份自动化 | 保留策略脚本 + 验证 + 迁移回滚文档 | |
| 7 | 生产部署 | docker-compose.prod.yml + 部署文档 | |
| 8 | 最终质量审查 | 全量回归 + 评测 + 容器验证 | |
| 9 | 求职交付 | INTERVIEW_GUIDE_V3 / PROJECT_PRESENTATION / RESUME_DESCRIPTION / V3_FINAL_REPORT | |

## 安全边界

不推送、不合 main、不动卷、不删正式数据、不泄密钥、不调用付费 API（真实 LLM 冒烟 ≤2 次）。
