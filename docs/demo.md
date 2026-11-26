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
273 passed

$ python -m ruff check .
All checks passed!

$ python -m pytest -q --cov=app --cov-fail-under=70
TOTAL                                  4465   1053   1032    152    73%
273 passed

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

## 9. 真实 DeepSeek 复跑（不是 mock）

### 9.1 留出集准确率复现（25 条，2026-11-26 实跑）

```console
$ LLM_PROVIDER=deepseek python tests/evaluate_text2sql_holdout.py \
      --temperature 0 --output %TEMP%\holdout_reverify.json --verbose
[OK ] 一共多少笔到店记录 | 期望≈8000.00 实得≈8000.00
[OK ] 各城市的到店记录数是多少 | 期望7行 实得7行
[OK ] 消费金额最高的门店是哪个 | 期望包含「滨江店」实得「滨江店」
[OK ] 华东区域占整体消费金额的比例是多少 | 期望≈37.73 实得≈37.73
…（25/25 全部 OK）
{"dataset":"holdout_visits.db","holdout":true,"cases":25,
 "correct_rate":1.0,"exec_rate":1.0,"avg_gen_ms":1620.4,"avg_exec_ms":3.1,"misses":[]}
```

归档里的 100% 不是历史遗留数字，用今天的模型重跑仍然成立（写入临时文件，**未覆盖归档**）。

### 9.2 端到端问答（真实模型，3 问）

```console
Q1: 2026年各城市的销售额排名        (6528 ms)
SQL: SELECT "城市", ROUND(SUM("销售额"), 2) AS "销售额" FROM "订单明细"
     WHERE "订单日期" >= '2026-01-01' AND "订单日期" <= '2026-11-26'
     GROUP BY "城市" ORDER BY "销售额" DESC LIMIT 100
chart_type: bar | series: 1 | x轴点数: 4
answer: 2026年各城市销售额排名已出炉，**杭州以224,216.99元拔得头筹**…
        （给出排名表 + 计算说明 + 两梯队对比 + 最高最低相差 15.6%）

Q2: 2026年哪个渠道的利润最低，为什么   (12837 ms)
SQL: 一次查出 利润/销售额/成本/利润率/毛利率/订单数 6 个指标，ORDER BY 总利润 ASC
causes: 4 条（定价偏低、成本控制弱、规模效应未体现、大客户议价）
suggestions: 4 条（如"毛利率低于30%的SKU提价5%-8%""单笔毛利率门槛38%"）
answer: 给出"批发利润最低 76,116.41 元 / 利润率 34.01%"的结论 + 归因 + 可执行建议

Q3: 帮我看看销售情况                (1439 ms)
needs_clarification = true
question: 请问您想看哪个时间范围的销售情况，以及关注哪个指标？
options: ['本月销售额','上个月销售额','今年销售额','今年各月销售额趋势','各城市销售额对比']
```

**同一套问题在 mock 下也能跑通，但文案是模板**（"数值最高的分组明显领先…"）。
所以 `docs/images/02-chat.png` 这张截图是用真实 DeepSeek 生成的，其余页面截图来自
Docker 栈（带上传的 CSV 与定时任务历史）。

### 9.3 一个被真实模型纠正的文档错误

用真实模型跑"**各城市的销售额排名**"（不带时间范围）时，Agent **先反问时间段**，
不会直接出 SQL。这不是 bug：`docs/PRD.md` 明确要求"指标/时间/粒度缺一即澄清"。
是 README 里的示例问题与 PRD 自相矛盾（mock 的启发式恰好没触发澄清，掩盖了这一点）。
已把文档里的示例统一改成带时间范围的写法，并注明"不带时间会先澄清"。

## 10. 依赖与流水线安全扫描（真跑）

```console
$ trivy fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
    --skip-dirs frontend/node_modules --skip-dirs frontend/dist --exit-code 1 .
（升级前）
  @vue/server-renderer 3.5.35  GHSA-g2v6-rqmx-r4w6  fix=3.5.42,3.6.0-rc.6  HIGH
  axios                1.17.0  CVE-2026-101898/101901/101903/101905/101906/101907/101909/67320  HIGH
  follow-redirects     1.16.0  CVE-2026-111755/111756/116689  HIGH
  form-data            4.0.5   CVE-2026-12143  HIGH
  nanoid               3.3.12  CVE-2026-67213/67214  HIGH
  postcss              8.5.15  CVE-2026-73646  HIGH
  source-map-js        1.2.1   CVE-2026-93749  HIGH
  TOTAL_VULNS 17                                  → exit 1

$ npm install --save vue@^3.5.42 axios@^1.20.0 && npm update
（升级后）
  frontend/package-lock.json │ npm │ 0
  TRIVY_EXITCODE=0
```

17 → 0，是**升级依赖**换来的，`.trivyignore` 里没有任何豁免项。
升级后 `npm run lint` / `npm run build` 仍然 exit 0（vue 3.5.46 / axios 1.21.1）。

> `npm audit` 在本机不可用（registry 是 npmmirror，`/-/npm/v1/security/*` 未实现），
> 所以依赖漏洞只能靠 Trivy —— 这也是坚持把它放进 CI 的原因。

### 10.1 镜像扫描（文件系统扫描看不到系统包）

```console
$ trivy image --severity HIGH,CRITICAL --ignore-unfixed data-agent-api:latest
（修复前）
data-agent-api:latest (debian 13.8)   Total: 1 (HIGH: 1)
  libzstd1  CVE-2026-124851  1.5.7+dfsg-1 → 1.5.7+dfsg-1+deb13u1   HIGH  exit 1

$ trivy image ... data-agent-web:latest
（修复前）pcre2 / tiff / zlib 多条 HIGH（zlib 1.3.1-r2 → 1.3.2-r1 等）  exit 1
```

修复方式是在 Dockerfile 里升级基础包（`apt-get upgrade -y` / `apk upgrade --no-cache`），
不是加豁免：

```console
$ trivy image ... data-agent-api:latest          → 0 vulnerabilities   exit 0
$ trivy image ... data-agent-task-worker:latest  → 0 vulnerabilities   exit 0
$ trivy image ... data-agent-web:latest (alpine 3.21.3) → 0 vulnerabilities   exit 0
```

CI 的 docker job 里已加上这两个 `trivy image` 步骤。

```console
$ actionlint .github/workflows/ci.yml
ACTIONLINT_EXITCODE=0
```

## 11. 默认端口验证边界

```console
$ docker compose config | grep -E 'published|target'
  target: 8000   published: "8000"     # API
  target: 80     published: "8080"     # Web
```

| 端口 | 结果 | 证据 |
|---|---|---|
| Web `8080` | ✅ **实跑通过** | `web/healthz → ok`、SPA `HTTP 200`、`/api/health → {"status":"ok"}`、经 nginx 登录 `200` |
| API `8000` | ❌ **本机无法验证** | 端口被 `wslrelay`(IPv6 `::1`) + `com.docker.backend` 占用；`docker run -p 8000:80` 与 `-p 0.0.0.0:8000:80` 均报 `Bind for 0.0.0.0:8000 failed: port is already allocated` |

本机用 `docker-compose.override.yml`（已 gitignore）把 API 映射到 18000；干净机器上默认值可用。
