# 审计报告（P0）

> 审计时间：2026-11-26 · 范围：仓库 `D:\data-agent` 全量代码 / 配置 / 测试 / 容器
> 方法：只读审计 → 跑基线 → 按 10 个模块盘点 → 定优先级 → 逐阶段实现并验收
>
> 结论先行：**核心 Agent 链路是好的**（8 节点图、SQL 列归属校验、失败回写重试、
> 多源降级、trace 落库都在，95 个测试全绿）；**缺的是"产品化最后一公里"**——
> 没有认证/权限、没有迁移、前端构建是坏的、没有 CI、没有可读文档。

## 1. 基线（审计时的真实状态，均为命令输出）

| 检查 | 命令 | 审计时结果 |
|---|---|---|
| 后端测试 | `cd backend && python -m pytest -q` | `95 passed in 14.94s` |
| 前端构建 | `cd frontend && npm run build` | ❌ 失败：缺 `@types/node`，`tsconfig.node.json` 未设 `composite` |
| compose 解析 | `docker compose config` | ✅ 通过（但只有 2 个服务，无卷、无 restart） |
| Lint | — | 未配置 |
| 覆盖率 | — | 未度量（后测：74%） |
| CI | `.github/workflows/` | ❌ 目录不存在 |

## 2. 十个模块的缺口盘点

| # | 模块 | 审计发现 | 严重度 | 处理 |
|---|---|---|---|---|
| 1 | **认证 / 权限** | `app/api/auth.py`、`app/services/auth.py`、`app/models/user.py` **只剩 `.pyc`，源码已丢**；`main.py` 未注册 auth 路由；所有接口写死 `DEFAULT_USER="default"`，任何人都能读写全部数据 | 🔴 阻断 | P3 重写：JWT + refresh 轮换 + PBKDF2 + admin/analyst/viewer 权限点 |
| 2 | **元数据迁移** | 无 Alembic，靠 `Base.metadata.create_all`；`models/__init__.py` 为空 → `models/log.py` 从未被导入，**`operation_logs` 表根本不会创建** | 🔴 阻断 | P1：引入 Alembic + 初始迁移 + 启动自愈；模型统一导出 |
| 3 | **前端** | `npm run build` 直接失败（类型依赖缺失）；只有 3 个页面，无登录/无权限感知/无 SSE 流式渲染 | 🔴 阻断 | P4：修构建 + 登录 + 数据源 CRUD + SSE 对话 + 报告 + 定时页 |
| 4 | **数据管道** | 上传无大小上限、无扩展名校验、**直接用用户文件名落盘（路径穿越）**；无 schema profiling；无清洗、无增量、无样例数据 | 🟠 高 | P1：profiling + 清洗 + 行哈希增量 + 样例播种 + 三重上传防护 |
| 5 | **服务化** | 数据源只有 列表/创建/删除，无详情/更新/连接测试/画像；无 `/healthz /readyz /metrics`；日志非结构化、无 request_id；错误体三种形状混用 | 🟠 高 | P3+P6：CRUD 补全 + 统一错误体 + 探针 + JSON 日志 + request_id |
| 6 | **SQL 安全** | 非 SELECT 只被标记 `sql_needs_confirmation` 后挂起，**没有执行侧硬拦截**；无长度上限；LIMIT 依赖模型自觉；行数上限在部分连接器上缺失 | 🟠 高 | P2：`sql_policy` 只读闸（单语句/长度/关键字/自动 LIMIT/单元格上限） |
| 7 | **定时调度** | 完全没有 | 🟡 中 | P5：DB 唯一约束幂等抢占 + 失败隔离 + 连续失败自动停用 |
| 8 | **可观测** | 有 trace（节点级），但没有日志关联、没有指标、没有告警规则、审计表未建 | 🟡 中 | P6：JSON 日志 + 指标 + 告警规则 + 审计事件 |
| 9 | **容器 / 部署** | 镜像只有 api/worker；**两个容器共用一个未挂载的 SQLite**（重建即丢数据）；无前端镜像/反代；无 restart | 🟡 中 | P7：加 web 镜像 + Nginx(SSE) + 命名卷 + restart + healthcheck |
| 10 | **文档 / 仓库卫生** | README 引用的 `docs/PRD.md` 不存在；无 architecture/demo；根目录有游离 xlsx、`nul`、`*.bak`；`.gitignore` 已能挡住大部分但缺少 README 说明 | 🟡 中 | P9 + 卫生清理 |

## 3. 审计时被澄清的两个"可疑点"

1. **"仓库有 `.env` / `release.zip` / `nul` / `*.bak` / `__pycache__`"** —— 这些文件确实在工作区里，
   但 `git ls-files` 显示它们**都没有被跟踪**（`.gitignore` 已覆盖）。真正的问题不是"泄密"，
   而是它们混在目录里干扰阅读；处理方式是物理清理 + 在 README 里写清"仓库里只有什么"。
2. **"`api/auth.py` 似乎只有 pyc"** —— 属实，且影响面比看起来大：`services/auth.py`、
   `models/user.py` 也只剩 pyc，等于**认证模块整体丢失**。所以 P3 不是"补个登录"，
   而是把权限模型从零重新设计（角色 → 权限点 → 路由依赖）。

## 4. 不做什么（明确取舍）

| 候选 | 决定 | 理由 |
|---|---|---|
| 换 PostgreSQL 元数据库 | ❌ 不做 | 项目定位单机 / 小规模，SQLite + WAL 足够；换库只增加部署门槛 |
| 引入 Celery + Redis | ❌ 不做 | 已用 `asyncio.Queue` + 任务表实现"提交即返回、状态可查、重启恢复"，量级不需要 Redis |
| 引入 prometheus_client | ❌ 不做 | 只需 counter/histogram/gauge，手写 ~150 行即可，少一个依赖 |
| 引入 passlib + bcrypt | ❌ 不做 | 与现有依赖版本冲突；stdlib `pbkdf2_hmac` 同理合规且零依赖 |
| 引入 python-jose | ❌ 替换为 PyJWT | jose 依赖的 `ecdsa` 有未修复安全公告（`pip-audit` 会红） |
| 前端换 Vue 3 + TS 之外的栈 | ❌ 不做 | 现有栈可用，重写不产生价值 |
| 改写 LangGraph 为自研编排 | ❌ 不做 | 图路由 + 条件边正好表达这套流程；重写只会丢功能 |

## 5. 执行顺序与验收口径

每个阶段结束都必须跑对应命令，**失败先修再继续**（不是"报告完成"）：

| 阶段 | 内容 | 验收命令 |
|---|---|---|
| P1 数据管道 | profiling / 清洗 / 增量 / 迁移 / 样例 | `pytest -q tests/test_ingest_profiling.py` + `alembic upgrade head` |
| P2 Agent 质量 | SQL 只读闸 / 限流 / 超时 / 行上限 / 基线 | `pytest -q tests/test_sql_policy.py` + `python bench/agent_baseline.py` |
| P3 服务化 | 认证 / RBAC / 数据源 CRUD / SSE / 报告 | `pytest -q tests/test_auth.py tests/test_datasource_api.py` |
| P4 前端 | 登录 / 数据源 / 对话 / 报告 | `npm run build` + `npm run lint` |
| P5 调度 | 定时 / 幂等 / 重试 / 隔离 | `pytest -q tests/test_scheduler.py` |
| P6 可观测 | 日志 / 探针 / 指标 / 审计 | `pytest -q tests/test_system_api.py` |
| P7 容器 | 三镜像 / 卷 / 健康检查 | `docker compose up -d --build --wait` |
| P8 测试与 CI | 覆盖率 / CI / 安全扫描 | `pytest --cov-fail-under=70` + CI 全绿 |
| P9 包装 | README / PRD / demo | 文档自检清单 |

## 6. 剩余风险（审计后仍然存在，已写进 README）

1. **SQLite 单写者**：api 与 worker 两个进程共享一个 SQLite 文件，靠 WAL + `busy_timeout=5000`
   扛住，写入峰值下仍可能 `database is locked`。真实多租户应换 PostgreSQL。
2. **限流是进程内的**：多副本时每个副本各算一份，总量放大 N 倍。
3. **定时调度器跑在 worker 进程里**：多副本靠 `schedule_runs` 唯一约束保证不重复执行，
   但"谁负责调度"没有领导者选举，只是幂等兜底。
4. **`mock` LLM 不是能力**：它只保证链路通；NL2SQL 准确率必须用 DeepSeek 实测（已归档 309 条）。
5. **PDF 中文依赖系统 CJK 字体**：容器里装了 `fonts-noto-cjk`，本地未装时会退化成 ASCII。
