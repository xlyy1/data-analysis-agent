# 告警规则与值班手册

配套 `/metrics`（Prometheus 文本格式，`app/observability/metrics.py`）。
指标名统一前缀 `dsh_`。

## 1. 暴露的指标

| 指标 | 类型 | 标签 | 用途 |
|---|---|---|---|
| `dsh_http_requests_total` | counter | `method`, `path`(路由模板), `status` | 请求量 / 错误率 |
| `dsh_http_request_duration_seconds` | histogram | `method`, `path` | P95 延迟 |
| `dsh_agent_runs_total` | counter | `outcome`(ok/error) | 分析成功率 |
| `dsh_agent_run_duration_seconds` | histogram | — | 端到端耗时 |
| `dsh_sql_guarded_total` | counter | `reason` | SQL 被拦次数（按原因） |
| `dsh_sql_executed_total` | counter | `datasource_type` | 实际执行的只读查询 |
| `dsh_schedule_runs_total` | counter | `status` | 定时分析结果 |
| `dsh_task_queue_depth` | gauge | — | 队列积压（来自任务服务列表采样） |
| `dsh_build_info` | gauge | `version` | 版本标记 |

## 2. 告警规则（Prometheus）

```yaml
groups:
  - name: data-agent-api
    rules:
      - alert: ApiDown
        expr: up{job="data-agent-api"} == 0
        for: 1m
        labels: {severity: critical}
        annotations:
          summary: "API 不可达超过 1 分钟"
          runbook: "看 /healthz；再 docker compose logs api --tail=200"

      - alert: ApiNotReady
        expr: probe_success{job="data-agent-readyz"} == 0
        for: 3m
        labels: {severity: warning}
        annotations:
          summary: "/readyz 未就绪（元数据库或迁移有问题）"
          runbook: "curl /readyz 看 checks 字段；database.ok=false 时检查卷与迁移日志"

      - alert: HighErrorRate
        expr: |
          sum(rate(dsh_http_requests_total{status=~"5.."}[5m]))
          / sum(rate(dsh_http_requests_total[5m])) > 0.05
        for: 5m
        labels: {severity: warning}
        annotations:
          summary: "5xx 占比 > 5%"
          runbook: "按 error.request_id 在 JSON 日志里 grep 同一 request_id"

      - alert: AgentFailureRate
        expr: |
          sum(rate(dsh_agent_runs_total{outcome="error"}[10m]))
          / sum(rate(dsh_agent_runs_total[10m])) > 0.2
        for: 10m
        labels: {severity: warning}
        annotations:
          summary: "分析失败率 > 20%（模型超时/SQL 反复失败）"
          runbook: "看 dsh_sql_guarded_total 的原因分布；再看 trace 里失败节点"

      - alert: P95LatencyHigh
        expr: |
          histogram_quantile(0.95,
            sum(rate(dsh_http_request_duration_seconds_bucket[10m])) by (le, path)) > 10
        for: 10m
        labels: {severity: warning}
        annotations:
          summary: "某路由 P95 > 10s"
          runbook: "chat 路由慢通常是 LLM；先确认 LLM_PROVIDER 与模型侧延迟"

      - alert: SqlGuardSpike
        expr: increase(dsh_sql_guarded_total{reason!="sql_limit_appended"}[10m]) > 10
        for: 5m
        labels: {severity: warning}
        annotations:
          summary: "SQL 被拦截次数突增（可能是提示注入或模型跑偏）"
          runbook: "查 dsh_sql_guarded_total 的 reason：write_forbidden / multi_statement / too_long"

      - alert: ScheduleFailing
        expr: increase(dsh_schedule_runs_total{status="failed"}[1h]) > 3
        for: 5m
        labels: {severity: info}
        annotations:
          summary: "定时分析 1 小时内失败超过 3 次"
          runbook: "计划在连续失败 3 次后会自动停用；先修数据源再重新启用"

      - alert: TaskBacklog
        expr: dsh_task_queue_depth > 20
        for: 15m
        labels: {severity: warning}
        annotations:
          summary: "任务积压 > 20"
          runbook: "调大 TASK_WORKERS，或看是否有长任务卡在 120s 超时"
```

## 3. 排查路径（从 user 报告到根因）

1. 让用户给出错误提示里的 `request_id`（统一错误体里带，前端也会展示）。
2. `docker compose logs api | grep <request_id>` —— JSON 日志里同一 id 的所有行。
3. 如果是分析类错误，再按 `trace_id` 查 trace：

```bash
# trace 落在 data/traces.db
python -m app.observability.replay <trace_id>
```

4. 如果是 SQL 被拒：`dsh_sql_guarded_total{reason=...}` 对应的
   `POST /api/sql/validate` 可以把那段 SQL 单独喂进去看判定原因。

## 4. 日志字段约定

```json
{"ts": "2026-11-26T01:02:28.123", "level": "info", "logger": "access",
 "msg": "POST /api/conversations/chat -> 200", "request_id": "…", "user_id": "…",
 "method": "POST", "path": "/api/conversations/chat", "status": 200,
 "duration_ms": 1832.4, "client": "172.18.0.1"}
```

- `request_id`：来自 `X-Request-ID` 或服务端生成，同时写进响应头；
- `user_id`：鉴权通过后注入（未登录请求没有这个字段）；
- 审计类事件（登录、改数据源、生成报告、定时执行）另走 `operation_logs` 表，可按用户查。
