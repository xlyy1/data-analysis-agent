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
| "某产品的利率" / "利润率" | Per-product: total profit / total cost × 100 | GROUP BY 产品, SUM("总利润") / SUM("总成本") × 100 |
| "某产品的毛利率" | Per-product: (revenue - cost) / cost × 100 | GROUP BY 产品, (SUM("总收入") / SUM("总成本") - 1) × 100 |
| "总销量最高/最低的产品" | Group by product, sum, then rank | GROUP BY 产品, ORDER BY SUM("总销量") DESC |
| "单个产品的X" / "每件产品的X" | Always GROUP BY product | GROUP BY 产品, then compute metric |
| "哪个平台销量最高" | Compare across platforms | SUM each platform's "销量" column separately |
| "单件利率" / "单件利润率" | Per-product profit rate | GROUP BY 产品, SUM("总利润")/SUM("总成本")×100 |

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
        }
    except Exception as e:
        return {**state, "error": f"SQL generation failed: {e}"}
