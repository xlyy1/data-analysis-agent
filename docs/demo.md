# 验收记录（demo）

> 所有输出都是本机真实执行结果，不是"预期结果"。
> 环境：Windows 11 · Python 3.13（镜像内 3.12）· Node 22 · Docker 29.7.2
> 演示用 `LLM_PROVIDER=mock`（见文末说明），不依赖任何付费 Key。

## 0. 一条命令起全栈

```console
$ docker compose config
# 通过（services: api / task-worker / web；volumes: agent-data）

$ docker compose up -d --build --wait
 Container data-agent-task-worker-1  Healthy
 Container data-agent-api-1          Healthy
 Container data-agent-web-1          Healthy

$ docker compose ps
SERVICE       STATUS                    PORTS
api           Up (healthy)              0.0.0.0:8000->8000/tcp
task-worker   Up (healthy)              8001/tcp
web           Up (healthy)              0.0.0.0:8080->80/tcp
```

> 本机 8000 端口被其他程序占用，所以本地用了 `docker-compose.override.yml`
> 把端口映射成 18000/18080；仓库默认仍是 8000/8080。

## 1. 探针

```console
$ curl -s localhost:18000/healthz
{"status":"ok","service":"data-agent-api","version":"1.0.0","uptime_seconds":41.9}

$ curl -s localhost:18000/readyz
{"status":"ok","checks":{"database":{"ok":true,"detail":"ok"},
 "trace_store":{"ok":true,"detail":"/app/backend/../data/traces.db"},
 "task_service":{"ok":true,"detail":"http 200"}},"version":"1.0.0"}

$ curl -s localhost:18000/metrics | head -4
# HELP dsh_http_requests_total HTTP 请求总数
# TYPE dsh_http_requests_total counter
dsh_http_requests_total{method="GET",path="/readyz",status="200"} 5
dsh_http_requests_total{method="GET",path="/healthz",status="200"} 1
```

## 2. 端到端自检（45 项全绿）

```console
$ cd backend && python tools/smoke_e2e.py --base-url http://127.0.0.1:18000
=== 1. 探针 / 指标 ===
  [PASS] /healthz 200
  [PASS] /readyz 200
  [PASS] /metrics 是 Prometheus 文本
=== 2. 登录 / 鉴权 ===
  [PASS] 未带 token 访问被拒 401 — 401
  [PASS] 登录成功
  [PASS] 拿到 access+refresh
  [PASS] 角色是 admin
  [PASS] /api/auth/me 200
  [PASS] refresh 能换新 token
  [PASS] 旧 refresh token 已吊销 — 401
=== 3. 数据源 ===
  [PASS] 数据源列表 200
  [PASS] 至少有一个数据源（样例已播种） — 1 个
  [PASS] 数据源已算出 schema — 1 个有表
  [PASS] 数据质量画像可用
=== 4. 自然语言问答 ===
  [PASS] 回答问题：「各城市的销售额排名」 — SELECT "城市" … GROUP BY "城市" ORDER BY 2 DESC LIMIT 20
  [PASS] 返回了图表配置 — bar
  [PASS] 回答问题：「哪个渠道的利润最低，为什么」 — SELECT "渠道" … SUM("利润") …
  [PASS] 返回了图表配置 — bar
  [PASS] 模糊问题触发澄清：「帮我看看销售情况」
=== 5. SSE 流式 ===
  [PASS] SSE 状态码 200
  [PASS] 收到节点推进事件 — done,metadata,node,text
  [PASS] 收到文本增量
  [PASS] 收到元数据事件
  [PASS] 以 [DONE] 结束
=== 6. 报告导出 ===
  [PASS] 生成报告 200
  [PASS] 报告已落库有 id
  [PASS] 下载 markdown — 1706 bytes
  [PASS] 下载 html — 3010 bytes
  [PASS] 下载 pdf — 41087 bytes
=== 7. 权限（viewer 只读） ===
  [PASS] viewer 能登录
  [PASS] viewer 能列数据源
  [PASS] viewer 不能建数据源 403 — 403
  [PASS] viewer 不能删数据源 403 — 403
  [PASS] viewer 不能建用户 403 — 403
  [PASS] viewer 仍可做只读问答
=== 8. 恶意 SQL ===
  [PASS] 拒绝 SQL 注入（分号拼接删表） — 只允许执行单条 SQL，检测到多条语句
  [PASS] 拒绝 删表 — 只允许只读查询，拒绝执行 DROP 语句
  [PASS] 拒绝 删数据 — 只允许只读查询，拒绝执行 DELETE 语句
  [PASS] 拒绝 改数据 — 只允许只读查询，拒绝执行 UPDATE 语句
  [PASS] 拒绝 读服务器文件 — 禁止读取服务器文件
  [PASS] 拒绝 超长查询 — SQL 过长（12008 字符，上限 8000）
  [PASS] 拒绝 PRAGMA 绕过 — 只允许只读查询，拒绝执行 PRAGMA 语句
  [PASS] 正常只读查询被放行且自动补 LIMIT
=== 9. 会话持久化 ===
  [PASS] 会话消息可回读 — 8 条
  [PASS] 会话列表包含该会话

============================================================
通过 45 项，失败 0 项
全部通过 ✅
```

## 3. 上传清洗（脏 CSV）

`data/samples/门店经营明细_待清洗.csv` 里埋了：脏列名、整行空行、完全重复行、前导零编码、首尾空格。

```console
$ curl -s -X POST localhost:18000/api/datasources/upload \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@data/samples/门店经营明细_待清洗.csv"
{
  "table": "门店经营明细_待清洗",
  "ingest": {
    "rows_in": 63,
    "rows_written": 60,
    "dropped_blank": 1,
    "dropped_duplicate": 2,
    "encoding": "utf-8-sig",
    "columns": ["门店编号","门店名称","col_3","城市","月份","销售额","客流"],
    "dtypes": {"门店编号":"str","城市":"str","销售额":"float64","客流":"int64"},
    "notes": [
      "第 3 列没有列名，已命名为 col_3",
      "丢弃 1 行全空记录",
      "列 门店编号 存在前导零，保持文本类型",
      "列 销售额 已转为数值",
      "列 客流 已转为数值",
      "丢弃 2 行完全重复记录"
    ]
  }
}
# 数据源：tables=1 rows=60

# 再导一次同一份文件（增量追加） → 幂等
$ curl -s -X POST ".../api/datasources/$ID/reingest?append=true"
{"ingest": {"rows_in": 63, "rows_written": 0, ...}}
```

三个容易被忽略的点：`0012` 这类编码**没被转成 12**（否则门店编号就废了）、
空列名被命名成 `col_3` 而不是丢掉整列、重复导入不产生重复行。

## 4. Linux / CI 侧的验收命令

```console
$ cd backend && python -m pytest -q
268 passed

$ python -m ruff check .
All checks passed!

$ python -m pytest -q --cov=app --cov-fail-under=70
TOTAL  4425  1047  73%
268 passed

$ python bench/agent_baseline.py
{"cases": 8, "clarification_accuracy": 1.0, "exec_rate": 1.0,
 "chart_rate_on_answered": 1.0, "readonly_sql_rate": 1.0, "model": "mock"}
BASELINE OK

$ python bench/quality_gate.py
[PASS] text2sql.result.json: correct_rate=1 (要求 >= 1, cases=191)
…（5 套数据、309 条用例全部 PASS）
QUALITY GATE OK

$ cd ../frontend && npm ci && npm run lint && npm run build
> eslint .            # 0 error 0 warning
✓ built in 4.84s
```

## 5. 定时分析端到端（Docker 里真跑一次）

```console
$ curl -s -X POST .../api/schedules -d '{"name":"每日经营日报",
      "question":"各城市的销售额排名","interval_minutes":1440}'
{"id":"1cd846f6-…","enabled":true,"next_run_at":"2026-11-26T19:03:59",…}

$ curl -s -X POST .../api/schedules/1cd846f6-…/run
{"run_id":"f37f0741-…","task_id":"d356b11a-…","status":"queued"}

# 12 秒后看运行历史
$ curl -s .../api/schedules/1cd846f6-…/runs
[{"status":"succeeded","attempts":1,"error":null}]

# 报告也自动产出了
$ curl -s .../api/reports
[{"title":"每日经营日报 · 2026-11-25 19:09"}, …]
```

这条链路走的是 API → task-worker → 调度器抢占 → 执行 Agent → 落报告，
不是同步调用；`schedule_runs(schedule_id, scheduled_for)` 的唯一约束保证
同一时刻只会执行一次。

## 6. 重启不丢数据

```console
# 重启前
conversations=3 reports=2 datasources=2

$ docker compose down          # 保留命名卷 agent-data
$ docker compose up -d --wait  # 三个容器重新健康

# 重启后
conversations=3 reports=2 datasources=2
verdict: conversations=True reports=True datasources=True
```

会话、报告、数据源全部还在 —— 因为 SQLite 落在命名卷 `/app/data` 上，
而不是容器可写层。定时任务的"重启恢复"另有单测覆盖
（`tests/test_task_queue.py::recover_pending`）。

## 7. 并发/边界行为的单测证据

| 行为 | 用例 |
|---|---|
| 定时任务同一时刻只执行一次（唯一约束） | `tests/test_scheduler.py::TestClaim::test_same_slot_is_idempotent` |
| 单个计划失败不影响其它计划 | `tests/test_scheduler.py::TestTick::test_failure_is_isolated_between_schedules` |
| 连续失败 3 次自动停用 | `tests/test_scheduler.py::TestTick::test_schedule_disabled_after_repeated_failures` |
| 重复上传同一文件不产生重复行 | `tests/test_ingest_profiling.py::TestIngestFrame::test_append_is_idempotent` |
| 上传路径穿越被中和 | `tests/test_datasource_api.py::TestUpload::test_path_traversal_filename_is_neutralized` |
| 上传超限立刻中断 | `tests/test_datasource_api.py::TestUpload::test_oversize_rejected` |
| 删除有历史记录的计划不再 500 | `tests/test_schedules_api.py::TestCrud::test_delete_with_run_history` |
| SQL 注入/删表/超长全部拒绝 | `tests/test_sql_policy.py`（20+ 条） |
| 结果被截断要明确告知 | `tests/test_agent_graph_mock.py::TestExecutorGuard::test_result_is_truncated_with_warning` |

## 8. 关于 `LLM_PROVIDER=mock`

演示和 CI 用确定性 mock，**不是**为了掩盖模型能力：

- 它让"不需要 Key 也能把产品点通"成立（面试官 clone 下来直接跑）；
- 它让"图路由 / SQL 闸 / 重试 / 图表生成"这些机制有回归门；
- 真实模型效果见 `backend/bench/README.md`：5 套数据 309 条用例，correct_rate 与
  exec_rate 均为 1.0（DeepSeek，temperature=0），其中 2 套是未参与调参的留出集。

要用真模型：

```bash
# .env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
docker compose up -d --build
```
