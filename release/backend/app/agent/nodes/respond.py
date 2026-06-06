"""回复生成节点

组合所有分析结果，生成友好的、结构化的最终回复。
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.agent.daysince import today_context
from app.llm.factory import get_llm

RESPONSE_PROMPT = """你是一个友好的数据分析助手。用自然、专业的语言回复用户的提问。

## 回复结构（根据情况灵活组合）：

1. **直接回答**：用户问题的核心答案，先用一句话给出结论
2. **推导说明**：如果指标是用公式计算得出的，简要说明计算逻辑（如"利润率 = 利润 / 收入 × 100% = 1500 / 50000 × 100% = 3%"）
3. **关键数据**：引用具体数值，对比参照
4. **分析发现**：洞察和趋势
5. **诊断原因**（如有亏损/下降/异常）：列出可能原因及证据
6. **优化建议**（如有）：具体可执行的建议
7. **图表说明**：简要提及已生成的图表

## 规则：
- 用中文回复，语气专业但亲切
- 数据要具体到数值，避免"大幅""略有"等模糊表述
- 回复长度适中（200-500字）
- 如果有诊断建议，必须引用数值证据
- 如果查询结果为空或报错，诚实告知，并说明可能的原因
- 对于派生指标，一定要解释计算过程

用户问题: {question}
分析类型: {analysis_type}
分析摘要: {summary}
诊断原因: {causes}
建议: {suggestions}
SQL解释: {sql_explanation}

请生成最终回复:"""


async def format_response(state: AgentState) -> AgentState:
    """生成最终回复"""
    llm = get_llm()
    user_input = state.get("user_input", "")
    analysis_type = state.get("analysis_type", "summary")
    analysis_summary = state.get("analysis_summary", "")
    causes = state.get("diagnosis_causes", [])
    suggestions = state.get("diagnosis_suggestions", [])
    sql_explanation = state.get("sql_explanation", "")

    prompt = RESPONSE_PROMPT.format(
        question=user_input,
        analysis_type=analysis_type,
        summary=analysis_summary,
        causes="\n".join(f"- {c}" for c in causes) if causes else "无",
        suggestions="\n".join(f"- {s}" for s in suggestions) if suggestions else "无",
        sql_explanation=sql_explanation or "无",
    )

    # Inject real date/time context
    time_ctx = today_context()
    full_prompt = time_ctx + "\n\n" + prompt

    try:
        resp = await llm.chat([{"role": "system", "content": full_prompt}, {"role": "user", "content": "请生成回复"}])
        return {**state, "final_response": resp}
    except Exception as e:
        return {**state, "final_response": f"抱歉，生成回复时出错: {e}"}
