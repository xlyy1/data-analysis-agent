# Benchmark 索引

本目录放**评测脚本**和**归档结果**。分两类，用途完全不同，不要混着看。

## 1. 需要 LLM 的准确率评测（要 Key，不进 CI）

| 脚本 | 数据 | 用例 | 归档结果 | correct_rate | exec_rate | 说明 |
|---|---|---|---|---|---|---|
| `tests/evaluate_text2sql.py` | 自建销售库 | 191 | `tests/data/text2sql.result.json` | 1.0 | 1.0 | 主数据集，temperature=0 |
| `tests/evaluate_text2sql_holdout.py` | `holdout_visits.db` | 25 | `text2sql_holdout.result.json` | 1.0 | 1.0 | 留出集，**未参与任何提示词调整** |
| `tests/evaluate_text2sql_holdout2.py` | `holdout_library.db` | 22 | `text2sql_holdout2.result.json` | 1.0 | 1.0 | 第三套数据，修复 sample_values 后只跑一次 |
| `tests/evaluate_text2sql_join.py` | `warehouse.db`（5 万行，4 表） | 41 | `text2sql_join.result.json` | 1.0 | 1.0 | 跨表 JOIN / 字段归属 |
| `tests/evaluate_text2sql_scale.py` | `sales_large.db`（3 万行） | 30 | `text2sql_scale.result.json` | 1.0 | 1.0 | 规模与延迟 |
| `tests/evaluate_clarification.py` | 澄清边界集 | — | `clarification_*.json` | — | — | 该澄清/不该澄清的边界 |

合计 **309 条 NL2SQL 用例**，DeepSeek（temperature=0）下 correct_rate 与 exec_rate 均为 1.0，
平均生成延迟 1.5–2.1 s。复跑：

```bash
cd backend
export DEEPSEEK_API_KEY=sk-...
python tests/evaluate_text2sql.py
```

> 这些数字是**已归档的历史结果**，CI 不会重跑（有成本、有随机性）。
> `bench/quality_gate.py` 只校验归档结果仍达到门槛，防止有人把数字改差。

## 2. 不需要 Key 的机制回归门（进 CI）

| 脚本 | 作用 | 归档 |
|---|---|---|
| `agent_baseline.py` | 用 `LLM_PROVIDER=mock` 跑通完整图（8 用例），校验路由 / SQL 只读 / 执行 / 图表 / 澄清 5 个机制点 | `agent_baseline.json` |
| `quality_gate.py` | 校验上面那批 LLM 评测的归档结果是否达标 | 读取 `tests/data/*.result.json` |
| `context_retention_eval.py` | 上下文压缩的事实留存率（`--no-llm` 走抽取式兜底） | `retention_*.json` |
| `context_lost_facts_eval.py` / `context_e2e_eval.py` | 压缩后的事实级 / 端到端问答留存 | `lost_facts_20.json` / `e2e_*.json` |

```bash
cd backend
python bench/agent_baseline.py        # 逐项比对基线，回退即退非 0
python bench/quality_gate.py          # 归档准确率门槛
python bench/context_retention_eval.py --no-llm
```

### 上下文压缩的实际效果（`retention_24x15.json`）

24 段会话 × 15 个埋点事实，压缩后：

- 抽取式兜底：事实留存 4.2%，token 压缩到 12.3%
- 混合（LLM 摘要 + 抽取兜底）：事实留存 **100%**，token 压缩到 31.2%

这组数字说明了取舍：**纯抽取式压缩省 token 但丢事实**，加上 LLM 摘要后事实全保留，
代价是多花 ~19% token。
