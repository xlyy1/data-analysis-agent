# 架构说明

本文记录**当前的架构**和**为什么是这样**。凡是"改架构"的决定，理由必须先写在这里
（例如：为什么不用 Celery/Redis、为什么 SQLite 不换 PostgreSQL、为什么调度器放在 worker 进程）。

## 1. 一张图

```
                          ┌──────────────────────────────┐
  浏览器 ──HTTP/SSE──────▶│  web (Nginx)                 │
                          │  · 托管 Vue3 构建产物         │
                          │  · 反代 /api → api:8000      │
                          │  · SSE 关闭 proxy_buffering  │
                          └──────────────┬───────────────┘
                                         │
                          ┌──────────────▼───────────────┐
                          │  api (FastAPI)               │
                          │  · JWT 鉴权 + RBAC 权限点     │
                          │  · 会话 / 数据源 / 报告 / 定时 │
                          │  · SSE 流式（节点级推进）      │
                          │  · /healthz /readyz /metrics │
                          └───────┬───────────────┬──────┘
                                  │               │
                   ┌──────────────▼───┐    ┌──────▼──────────────┐
                   │  LangGraph Agent │    │  任务服务客户端      │
                   │  8 节点分析链路   │    │  (超时/重试/熔断)    │
                   └──────┬───────────┘    └──────┬──────────────┘
                          │                       │ HTTP
                   ┌──────▼───────────┐    ┌──────▼──────────────────┐
                   │ 数据源连接器      │    │ task-worker (FastAPI)    │
                   │ sqlite/mysql/pg  │    │ · asyncio 任务池          │
                   │ excel/csv(落库)  │    │ · 定时调度器 + 幂等抢占    │
                   └──────┬───────────┘    │ · /readyz /metrics        │
                          │                └──────┬──────────────────┘
                          │                       │
                   ┌──────▼───────────────────────▼──────┐
                   │  agent-data 卷（单个 SQLite 文件）    │
                   │  users / datasources / conversations │
                   │  messages / reports / schedules      │
                   │  background_tasks / operation_logs   │
                   └──────────────────────────────────────┘
```

## 2. 一次提问发生了什么

```
POST /api/conversations/chat/stream
 ├─ 鉴权：JWT → User（admin/analyst/viewer）
 ├─ 归属：conversation 必须属于当前用户，否则 404（不区分"不存在"与"不是你的"）
 ├─ 数据源上下文：resolve_datasource_context
 │    ├─ 现连数据源 → describe_schema（带 TTL 缓存）
 │    │    ├─ 低基数列采样 sample_values（治"黄金会员 vs 黄金"）
 │    │    └─ 推断 relations / column_lookup / role（fact|dimension）
 │    └─ 连不上 → 退回库里的 schema 缓存（降级不阻断）
 ├─ LangGraph（节点级 SSE 进度）
 │    understand_intent → [需澄清? → 结束]
 │      → generate_query → [非只读? → 挂起并告知]
 │      → execute_query ──错误且还有重试额度──▶ generate_query（带报错回写）
 │      │                └─0 行/成功→ analyze_results
 │      → analyze_results → [诊断关键词/anomaly? → diagnose] → generate_visualization
 │      └→ format_response（把结果校验告警附在末尾）
 ├─ 落库：assistant 消息 + metadata（SQL / 图表 / 前 20 行数据 / trace_id）
 └─ 返回：text 增量 + metadata + [DONE]
```

## 3. 关键取舍（重点看这一节）

### 3.1 为什么保留 LangGraph，而不写自研编排
条件边 + 状态合并正好表达"澄清 / 确认 / 重试 / 诊断分支"四个岔路；自研只会把
`should_clarify`、`route_after_execute` 这些已经测过的逻辑重写一遍。

### 3.2 为什么 SQL 安全做成"执行侧硬闸"而不是"提示词约束"
提示词会被注入绕过。所以真正的闸放在 `app/services/sql_policy.py`，在
`execute_query` 里**执行前**跑，规则是白名单式：

| 规则 | 做法 | 拦截示例 |
|---|---|---|
| 只读 | 首关键字必须是 `select/with/explain/show/describe`，且全文无写关键字 | `DROP TABLE`、`DELETE`、`PRAGMA`、`ATTACH` |
| 单语句 | 先把字符串/注释"打码"，再检查是否还有分号 | `SELECT 1; DROP TABLE x` |
| 长度 | 超过 `SQL_MAX_CHARS`（默认 8000）拒绝 | 拼接 3000 个子句 |
| 危险函数 | `load_file` / `pg_read_file` / `xp_cmdshell` / `sleep()` / `benchmark()` | 读服务器文件、延时注入 |
| 自动 LIMIT | 没有 `LIMIT` 的查询补 `LIMIT 1000`（换行拼接，避免落进行注释） | 全表扫描 |
| 行/单元格上限 | `min(max_return_rows, max_result_cells / 列数)` | 宽表打爆内存 |

"打码"是关键：`WHERE note='delete me'` 里的 `delete` 不会误伤，`SELECT "update" FROM t`
这种引号标识符也不会。

### 3.3 为什么用 Alembic，而不再 `create_all`
`create_all` 只能建"缺失的表"，不能改列、不能加索引、也没法回滚。审计时更直接的证据是：
`models/__init__.py` 是空的，`models/log.py` 从未被导入 → `operation_logs` 表**从来没被创建过**。
现在 `app/models/__init__.py` 统一导出全部模型，Alembic 的 `target_metadata` 才完整；
启动时 `ensure_schema()` = 迁移（5 次退避重试，容忍 api/worker 同时启动）+ `create_all` 兜底。

### 3.4 为什么不用 Celery + Redis
任务量级是"一天几十个长任务"，不需要分布式队列。现有 `asyncio.Queue` + `background_tasks` 表
已经满足三条硬要求：**先落库再入队**（不丢）、**attempts 上限**（不死循环）、
**`wait_for` 硬超时**（不占 worker），并且 `recover_pending()` 能把重启前未完成任务捡回来。
多一个 Redis 就多一个"要部署、要监控、会挂"的组件。

### 3.5 为什么定时调度器跑在 task-worker 里
调度需要把任务投进本地队列（不用走 HTTP），而队列只存在于 worker 进程。
API 只提供 schedule 的 CRUD。"多副本会不会重复执行"由数据库兜：
`schedule_runs(schedule_id, scheduled_for)` 唯一约束 —— 抢不到就说明别人已经抢了。

失败隔离：单条计划失败只标记自己的 run，`consecutive_failures` 累计到 3 自动停用，
同一轮里其它计划照常执行。

### 3.6 为什么 `mock` LLM 是正式组件而不是测试 hack
CI 不能依赖付费 Key，但"图路由 / JSON 解析 / SQL 闸 / 重试 / 图表生成"这些**机制**必须
有回归门。`MockLLM` 按 system prompt 的模板特征分派到固定响应，SQL 是按 schema 机械拼的
`GROUP BY` 聚合，够喂通下游。它**不衡量模型能力**——准确率看归档的 309 条 DeepSeek 评测。

### 3.7 为什么上传要"落库 + 清洗"，而不是每次查内存 DataFrame
原来的 Excel 数据源每次查询都把 DataFrame 重新灌进 `:memory:` 再执行，10 万行时单次查询
要几秒。现在上传时清洗一次、落成 SQLite（`data/ingested/<id>.db`），查询走真实 SQL 引擎，
顺带获得增量能力：按全行内容哈希（`_row_hash` 唯一索引）去重，重复上传同一份文件不会产生重复数据。

读取阶段刻意用 `dtype=str, keep_default_na=False`：pandas 的类型推断会把 `0012` 变成 `12.0`、
把长订单号变成科学计数法，这类编码字段一旦被"聪明地"转成数字就救不回来了。
真正的数值列由清洗阶段按"90% 可解析率"重新推断。

### 3.8 权限模型：角色 → 权限点 → 路由依赖
`角色` 只有三级，但代码里不比较角色，只比较**权限点**：

```
admin   → 全部（含 sql:write / user:manage / audit:read）
analyst → 数据源读写、会话、报告、定时
viewer  → 只能读 + 提问（不能改数据源、不能执行写 SQL）
```

路由上挂 `Depends(require("datasource:write"))`，权限表集中在 `app/services/auth.py`。
好处是加角色只改一张表；坏处是不能表达"同一角色对不同资源不同权限"——本项目的粒度不需要。

### 3.9 统一错误体
```json
{"error": {"code": "datasource_not_found", "message": "数据源不存在",
           "details": {}, "request_id": "..."},
 "detail": "数据源不存在"}
```
`code` 给前端做分支（不解析文案），`request_id` 和响应头 `X-Request-ID` 一致，
用户截图报错就能在日志里定位。`detail` 是 FastAPI 默认字段，保留一版做兼容。

### 3.10 为什么把 TDesign 移出依赖（唯一一次"改技术栈"，理由写在此）
审计时 `package.json` 声明了 `tdesign-vue-next` + `@tdesign-icons-vue-next`，`main.ts` 也
`app.use(TDesign)` 全局注册了它；但**全仓库没有任何一个 `<t-xxx>` 组件**——所有界面都是
自己写的 div + `App.vue` 里那套 CSS 变量设计系统（深色 + 靛蓝）。

也就是说 TDesign 只贡献了"被打进产物但从未渲染"的体积。这次前端补齐登录/数据源/报告/定时
四个页面时，需要的是能跟现有设计系统一致的组件（抽屉、确认弹窗、错误块），引入 TDesign
反而要再写一层样式覆盖。所以处理方式是：

- 移除 `tdesign-vue-next` / `@tdesign-icons-vue-next` 两个依赖，以及 `main.ts` 里的全局注册；
- 补齐真正被用到的少量基础组件：`components/ui/BaseModal.vue`、`components/ui/ErrorAlert.vue`；
- **其余技术选型一个没动**：Vue 3 + TypeScript(strict) + Vite + Pinia + Vue Router + ECharts +
  axios + marked/highlight.js。

净效果：产物从"含一整个未使用 UI 库"变成 688 modules / 约 1 MB（gzip 后 ~300 KB），
`vue-tsc` 严格模式通过。

> 如果你的规范要求保留 TDesign（例如团队统一组件库），把两个依赖和 `app.use(TDesign)`
> 加回去即可，不影响任何业务代码——这也是当初"组件全部自绘"带来的好处。

## 4. 数据模型

| 表 | 作用 | 关键约束 |
|---|---|---|
| `users` | 账号 + 角色 | `username` 唯一 |
| `refresh_tokens` | 刷新令牌 | 只存 sha256；`revoked` 支持轮换 |
| `datasources` | 数据源 | `config`（JSON，密码只写不读回）、`table_schema`、`profile_json` |
| `conversations` / `messages` | 会话 | `(conversation_id, created_at)` 联合索引 |
| `reports` | 报告 | markdown 原稿落库，可重复下载三种格式 |
| `analysis_schedules` / `schedule_runs` | 定时分析 | `(schedule_id, scheduled_for)` **唯一** = 幂等 |
| `background_tasks` | 任务队列 | `(status, created_at)` 联合索引，支持重启恢复 |
| `operation_logs` | 审计事件 | 登录/改数据源/生成报告/调度执行 |
| `alembic_version` | 迁移版本 | — |

## 5. 单机 vs 多 Worker 的边界（必须知道）

| 能力 | 单机（现状） | 多 Worker / 多副本会怎样 |
|---|---|---|
| 元数据库 | SQLite + WAL + `busy_timeout=5000` | 🔴 单写者瓶颈，需要 PostgreSQL |
| 任务队列 | 进程内 `asyncio.Queue` + 任务表 | ⚠️ 各进程消费各自队列；跨进程靠"落库 + 恢复"兜底，没有抢占锁 |
| 定时调度 | worker 内轮询 + 唯一约束抢占 | ✅ 唯一约束保证不重复执行 |
| 登录限流 | 进程内滑动窗口 | ⚠️ 总量放大 N 倍，需要 Redis |
| SQL 限流 | 进程内滑动窗口 | ⚠️ 同上 |
| trace | 独立 SQLite 文件 | ⚠️ 多进程写同一文件，建议换集中存储 |

这些不是"待修 bug"，是**与"单机面向中小商家"的定位一致的取舍**；换成分布式方案会在
`docs/architecture.md` 这一节先写清楚理由再动手。

## 6. 目录结构

```
backend/
  app/
    agent/           LangGraph 图、状态、节点、上下文压缩、子任务调度
    api/             路由：auth / conversation / datasource / report / schedules / tasks / sql / system
    core/            统一错误体、时间工具
    datasource/      连接器：sqlite / mysql / postgres / excel(csv)
    llm/             LLM 抽象：deepseek / ollama / openai / mock
    models/          SQLAlchemy 模型（统一导出，供迁移使用）
    observability/   trace / 结构化日志 / 指标
    sandbox/         代码执行沙箱
    services/        业务：auth / ingest / profiling / schema / sql_policy / scheduler / task_queue / report ...
  alembic/           迁移脚本
  bench/             评测与回归门（agent_baseline / quality_gate / 上下文压缩）
  tests/             268 个测试
  tools/             smoke_e2e.py 等运维脚本
frontend/            Vue3 + TDesign + ECharts，Nginx 托管
docs/                audit / architecture / PRD / demo / pitch / alerts
```
