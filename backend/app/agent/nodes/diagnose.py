"""诊断与建议节点

针对"亏损""下降""异常"类问题，自动拆解维度，输出原因+证据+建议。
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.agent.daysince import today_context
from app.llm.factory import get_llm

DIAGNOSE_PROMPT = """你是一个企业经营诊断专家。根据数据和用户问题，进行深度诊断分析。

用户问题: {question}
分析摘要: {summary}
查询数据:
{data}

请输出至少3个可能的原因，每个原因附带数据证据和可执行建议。

返回 JSON:
{{
  "causes": [
    {{
      "cause": "原因描述",
      "evidence": "数据证据（引用具体数值）",
      "suggestion": "可执行建议（要具体，如'将产品A价格从99元调整为89元'而非'优化定价'）",
      "priority": "高|中|低",
      "difficulty": "容易|中等|困难"
    }}
  ]
}}
"""


async def diagnose(state: AgentState) -> AgentState:
    """经营诊断"""
    llm = get_llm()
    user_input = state.get("user_input", "")
    analysis_summary = state.get("analysis_summary", "")
    query_result_json = state.get("query_result_json", "{}")

    try:
        result = json.loads(query_result_json)
        rows = result.get("rows", [])[:100]
        columns = result.get("columns", [])
    except json.JSONDecodeError:
        rows, columns = [], []

    data_str = "\t".join(columns) + "\n"
    for row in rows[:30]:
        data_str += "\t".join(str(v) for v in row) + "\n"

    prompt = DIAGNOSE_PROMPT.format(question=user_input, summary=analysis_summary, data=data_str)
    full_prompt = today_context() + "\n\n" + prompt

    try:
        resp = await llm.chat([{"role": "system", "content": full_prompt}, {"role": "user", "content": "请诊断"}])
        resp = resp.strip()
        if resp.startswith("```"):
            resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
        diag = json.loads(resp)

        causes_raw = diag.get("causes", [])
        causes = [c.get("cause", "") for c in causes_raw]
        evidence = [c.get("evidence", "") for c in causes_raw]
        suggestions = [f"[{c.get('priority', '中')}优先级/{c.get('difficulty', '中等')}难度] {c.get('suggestion', '')}" for c in causes_raw]

        return {
            **state,
            "diagnosis_causes": causes,
            "diagnosis_evidence": evidence,
            "diagnosis_suggestions": suggestions,
        }
    except Exception as e:
        return {
            **state,
            "diagnosis_causes": [f"诊断出错: {e}"],
            "diagnosis_evidence": [],
            "diagnosis_suggestions": [],
        }
