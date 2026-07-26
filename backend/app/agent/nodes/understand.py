"""意图理解节点

识别用户的自然语言意图，判断分析类型、是否需要澄清。
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.agent.daysince import today_context
from app.llm.factory import get_llm

INTENT_PROMPT = """你是一个数据分析意图识别器。根据用户输入和数据源schema，判断分析意图。

## 支持的7类分析场景：
- summary: 汇总统计（总和、平均值、最大最小值等）
- trend: 趋势分析（随时间变化）
- comparison: 对比分析（不同类别之间比较）
- proportion: 占比分析（各部分占整体的比例，包括比率、百分比等）
- correlation: 相关性分析（两个变量之间的关系）
- anomaly: 异常检测（发现异常值或突变）
- calculate: 派生指标计算（用户要的指标在schema中没有直接列，需要从已有列计算，如利率=利润/收入）

## 重要：自动识别派生指标
即使用户要的指标名（如"利率""毛利率""转化率""客单价"）在schema中没有直接出现，也要判断为 calculate 类型，而不是说"指标不存在"。
只要 schema 中有可以计算出该指标的相关列（如有"利润""收入"就能算利率），就标记 needs_clarification=false。

## 澄清规则
如果用户的问题模糊不清、缺少关键信息（如时间范围、分析维度），且无法从数据推断，才标记 needs_clarification=true。

数据源 Schema:
{schema}

请返回 JSON（不要包含其他内容）:
{{
  "analysis_type": "summary|trend|comparison|proportion|correlation|anomaly|calculate",
  "needs_clarification": true|false,
  "clarification_question": "反问内容（如需）",
  "clarification_options": ["选项A", "选项B"],
  "entities": {{"time_range": "时间范围", "dimensions": ["维度"], "metrics": ["指标"]}}
}}
"""


async def understand_intent(state: AgentState) -> AgentState:
    """分析用户意图"""
    llm = get_llm()
    user_input = state.get("user_input", "")
    schemas = "\n".join(state.get("datasource_schemas", []))

    prompt = INTENT_PROMPT.format(schema=schemas or "暂无数据源schema")

    # Inject real date/time context so LLM knows what "上个月" means
    time_ctx = today_context()
    full_prompt = time_ctx + "\n\n" + prompt

    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=user_input),
    ]

    try:
        resp = await llm.chat([{"role": "system", "content": full_prompt}, {"role": "user", "content": user_input}])
        # 尝试解析 JSON
        resp = resp.strip()
        if resp.startswith("```"):
            resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(resp)

        return {
            **state,
            "intent": json.dumps(result),
            "analysis_type": result.get("analysis_type", "summary"),
            "needs_clarification": result.get("needs_clarification", False),
            "clarification_question": result.get("clarification_question", ""),
            "clarification_options": result.get("clarification_options", []),
        }
    except Exception as e:
        return {**state, "error": f"Intent understanding failed: {e}"}
