# 安全终审报告（SECURITY_FINAL_REPORT）

审计时间：2026-11-15（V3.5 验收轮）。方法：全历史逐提交内容扫描 + 运行时实测 + 代码审读。

## 1. Git 历史审计（本轮核心）

| 检查 | 方法 | 结果 |
| --- | --- | --- |
| DeepSeek key（sk- 32 hex） | `git grep` 全部 rev-list 提交内容 | **0 处**——含已推送的 main 初始提交 96736ef |
| Tavily key（tvly-） | 同上 | **0 处** |
| GitHub token（gho_/ghp_） | 同上 | **0 处** |
| 密码赋值模式（backend 目录全历史） | `git grep -liE "password=..."` | **0 处** |
| `.env` 入库检查 | `git ls-files` | 未跟踪（142 个跟踪文件中 0 密钥文件） |

**结论：密钥从未进入任何 git 提交**——V1 前置的"先修密钥再 init"顺序经全历史扫描证实有效。GitHub 上已推送的 main 初始提交同样干净，**无需历史重写或密钥轮换**（若用户仍不放心可选轮换 DeepSeek/Tavily key，操作见 SECURITY_AUDIT.md §1）。

## 2. 运行时安全（实测）

| 项 | 结果 |
| --- | --- |
| 管理端点认证 | 401（无 key/错 key）+ 200（有效 key）实测；`secrets.compare_digest` 防时序 |
| 限流 | 429 + Retry-After 实测（general/admin 双桶独立，XFF 支持） |
| 上传安全 | 路径穿越/双后缀/非法字符/空名 8 项单测全过；批量上传保持同等防护 |
| 错误脱敏 | 500 通用文案；/health detail 脱敏；/chat 400 白名单内可控消息 |
| CORS | 白名单化（`RAG_CORS_ORIGINS`），prod compose 强制变量缺失即拒绝启动 |
| SQL 注入 | ORM 参数化 + 仅常量原生 SQL（历史扫描确认） |

## 3. 已知设计局限（非漏洞，多用户部署前必须处理）

1. `session_id` 由客户端提供——无用户体系下的会话隔离仅防"误访问"，不防"恶意访问"（D-9 决策记录）
2. 限流为进程内存实现——多实例部署需外置计数
3. 容器以 root 运行（Windows bind mount 属主映射限制）——缓解：仅挂载 resource data 目录

## 4. V3.5 新增面核查

- 批量上传端点：与单文件同等安全防护（扩展名白名单/大小/文件名清洗）；认证依赖一致（admin）
- /metrics 端点：无敏感数据（计数与分位数）；index_tasks 统计不含文档内容
- /documents 端点：列表开放（文件名元数据）；删除/重试 admin 保护

## 5. 最终结论

**安全验收通过**。全部检查项有实测或扫描记录；遗留项均为"多用户化前置条件"而非当前漏洞。
