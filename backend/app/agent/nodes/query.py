"""SQL generation node - generates safe SELECT queries from user questions and schema."""

import json

from app.agent.state import AgentState
from app.agent.daysince import today_context
from app.llm.factory import get_llm

SQL_GEN_PROMPT = """You are a senior SQL data analyst. You never guess column names — you ONLY use what the schema gives you.

## MANDATORY WORKFLOW — do ALL steps in order

### STEP 0 — Use "总" columns, do NOT manually sum

The system automatically injects "总{{suffix}}" columns into the schema (e.g. "总销量", "总利润", "总成本").
When the user asks for any total/aggregate metric, simply use the corresponding "总" column.
Example: user says "各产品的总销量" → use column "总销量" directly, do NOT write "京东销量"+"天猫销量"+...

### STEP 1 — Read the schema and find the "总" columns

Scan every column name in the schema. Columns that share the same **suffix** (ending characters) represent the same metric split across different categories (platforms, quarters, regions, etc.).

Example: schema has these columns: 产品名称, 京东销量, 天猫销量, 拼多多销量, 京东利润, 天猫利润, 拼多多利润, 京东成本, 天猫成本, 拼多多成本

GROUP them:
- Suffix "销量" → [京东销量, 天猫销量, 拼多多销量]
- Suffix "利润" → [京东利润, 天猫利润, 拼多多利润]
- Suffix "成本" → [京东成本, 天猫成本, 拼多多成本]
- Standalone → [产品名称]

### STEP 2 — Interpret the user's question using the groupings

| User says | Real meaning | How to compute |
|-----------|-------------|----------------|
| "某产品的销量" / "总销量" | That product's total sales across ALL platforms AND ALL orders | GROUP BY 产品, SUM("总销量") |
| "某产品的利润" / "总利润" | That product's total profit across ALL platforms AND ALL orders | GROUP BY 产品, SUM("总利润") |
| "某产品的成本" / "总成本" | That product's total cost across ALL platforms AND ALL orders | GROUP BY 产品, SUM("总成本") |
| "某产品的利率" / "利润率" | Per-product: total profit / total revenue × 100（利润率分母是==收入==，不是成本） | GROUP BY 产品, SUM("总利润") / SUM("总收入") × 100 |
| "某产品的毛利率" | Per-product: (SUM("总收入") - SUM("总成本")) / SUM("总收入") × 100 |
| "某产品的成本加成率 / 加价率" | Per-product: (SUM("总收入") - SUM("总成本")) / SUM("总成本") × 100 | GROUP BY 产品, (SUM("总收入") / SUM("总成本") - 1) × 100 |
| "总销量最高/最低的产品" | Group by product, sum, then rank | GROUP BY 产品, ORDER BY SUM("总销量") DESC |
| "单个产品的X" / "每件产品的X" | Always GROUP BY product | GROUP BY 产品, then compute metric |
| "哪个平台销量最高" | Compare across platforms | SUM each platform's "销量" column separately |
| "单件利率" / "单件利润率" | Per-product profit rate | GROUP BY 产品, SUM("总利润")/SUM("总收入")×100 |

### 过滤值必须与列的样本取值一致

schema 中部分列附带 `sample_values`（该列的真实取值）。
写 WHERE 条件前先看这一列有没有 sample_values：
- 有：过滤值必须**取自 sample_values**，不能照抄问句里的说法
  （例如问"黄金会员"，sample_values 是 ["普通","白银","黄金","钻石"]，应写 `会员等级 = '黄金'`）
- 没有：保留问句中的值，不要自行加后缀或改写

### 维度列的选择

- 用户说的是**品类词**（如“手机配件”“音频设备”）→ 过滤条件落在 产品类别 列
- 用户说的是**具体商品名**（如“充电宝”“运动耳机”）→ 过滤条件落在 产品名称 列
- 拿不准时先看 schema 里两列的实际取值，不要默认用 产品名称

### 表归属与 JOIN（先确认字段在哪张表）

schema 里有 `relations`、`column_lookup`、每张表的 `role`（fact / dimension）。

1. 过滤或聚合前，先在 `column_lookup` 里查这个字段属于哪张表。字段不在 fact 表时，必须按 `relations` JOIN 对应的 dimension 表，不能把维度字段直接写在 fact 表上。
2. 问“某院区 / 某科室 / 某职称 / 某区域”的数量、金额、平均值时，先 JOIN 再过滤。
3. 只 SELECT 问句需要的列。问“最高的一单是多少钱”就只返回金额，不要把单号一起返回；问“哪个城市”就只返回城市。

### 指标口径（分母约定）

- 利润率 / 利率 = 利润 ÷ 收入
- 成本加成率 / 加价率 = 利润 ÷ 成本
- 毛利率 = (收入 − 成本) ÷ 收入
- 占比 = 部分 ÷ 整体（同类合计）

若用户未说明口径且两种算法都可能，按上表默认值计算，不要替换分母。

### CRITICAL: When to use GROUP BY

**If the schema has multiple rows for the same product (order-level data), you MUST use GROUP BY when asking about products.**

Rule: the "总X" columns sum across PLATFORMS on each row (京东+天猫+拼多多), but they do NOT sum across ROWS. To get product-level totals, use:
```sql
SELECT "产品名称", SUM("总销量") AS "产品总销量"
FROM data
GROUP BY "产品名称"
ORDER BY "产品总销量" DESC
```

### STEP 3 — Write the SQL using ONLY real column names

**Golden rule: every column reference must be an EXACT copy-paste from the schema above.**

Examples based on schema [产品名称, 京东销量, 天猫销量, 拼多多销量, 总销量, 京东利润, 天猫利润, 拼多多利润, 总利润, 京东成本, 天猫成本, 拼多多成本, 总成本]:

```
-- User: "各产品的总销量" (multiple orders per product → MUST GROUP BY)
SELECT "产品名称", SUM("总销量") AS "产品总销量"
FROM data
GROUP BY "产品名称"
ORDER BY "产品总销量" DESC

-- User: "各产品的利润率" (per product → GROUP BY)
SELECT "产品名称",
       ROUND(SUM("总利润") * 100.0 / NULLIF(SUM("总成本"), 0), 2) AS "利润率(%)"
FROM data
GROUP BY "产品名称"
ORDER BY "利润率(%)" DESC

-- User: "总销量最高的3个产品" (per product ranking → GROUP BY)
SELECT "产品名称", SUM("总销量") AS "产品总销量"
FROM data
GROUP BY "产品名称"
ORDER BY "产品总销量" DESC
LIMIT 3

-- User: "上个月单件利率最高的三个产品" (per product rate → GROUP BY)
SELECT "产品名称",
       ROUND(SUM("总利润") * 100.0 / NULLIF(SUM("总成本"), 0), 2) AS "利润率(%)"
FROM data
WHERE "日期列" >= '2026-05-01' AND "日期列" <= '2026-05-31'
GROUP BY "产品名称"
ORDER BY "利润率(%)" DESC
LIMIT 3

-- User: "各产品在京东和天猫的总利润" (per product, specific platforms)
SELECT "产品名称",
       SUM("京东利润" + "天猫利润") AS "京东天猫总利润"
FROM data
GROUP BY "产品名称"
ORDER BY "京东天猫总利润" DESC
```

### CRITICAL RULES

1. **"总X" columns sum across platforms PER ROW — NOT across rows.** If the table has multiple orders per product, you MUST use `SUM("总X")` + `GROUP BY "产品名称"` for product-level metrics.
2. **When user asks about products/单个/每件/各XX, use GROUP BY.** The grouping column is usually the first text column (产品名称, 品类, 区域 etc).
3. **Column names = copy-paste from schema** — do not translate, do not shorten, do not invent
4. **NULLIF(denominator, 0) on every division**
5. **ROUND(..., 2) on all computed values**
6. **Only SELECT — no INSERT/UPDATE/DELETE**

### SQL RULES
- Wrap Chinese column names in double quotes: "列名"
- Only SELECT statements
- All divisions use NULLIF(col, 0)
- ROUND to 2 decimal places
- Add LIMIT (default 100)
- Before returning, verify: every column name in your SQL exists in the schema above

## Schema:
{schema}

## Question: {question}
## Intent: {intent}

Return JSON (no markdown fences):
{{
  "sql": "SELECT ...",
  "explanation": "Step-by-step: 1) what columns you found in schema, 2) how you grouped them, 3) how you computed the answer",
  "is_safe": true,
  "derived_metric": "Formula if applicable, else null"
}}"""


async def generate_query(state: AgentState) -> AgentState:
    llm = get_llm()
    user_input = state.get("user_input", "")
    schemas = "\n".join(state.get("datasource_schemas", []))
    intent = state.get("intent", "{}")

    prompt = SQL_GEN_PROMPT.format(schema=schemas, question=user_input, intent=intent)
    full_prompt = today_context() + "\n\n" + prompt

    previous_error = state.get("sql_error") or ""
    if previous_error and state.get("sql_retry_count", 0) > 0:
        full_prompt += (
            "\n\n## 上一次 SQL 执行失败（必须修正）\n"
            f"{previous_error}\n"
            "上面的 SQL 已经执行报错。请检查列名、表名、聚合写法与方言差异，重新生成一条可执行的 SQL。\n"
        )

    try:
        resp = await llm.chat([
            {"role": "system", "content": full_prompt},
            {"role": "user", "content": user_input},
        ])
        resp = resp.strip()
        if resp.startswith("```"):
            resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(resp)
        sql = result.get("sql", "")
        is_select = sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("WITH")

        return {
            **state,
            "generated_sql": sql,
            "sql_explanation": result.get("explanation", ""),
            "sql_needs_confirmation": not is_select,
            "error": "",
            "empty_result": False,
        }
    except Exception as e:
        return {**state, "error": f"SQL generation failed: {e}"}
