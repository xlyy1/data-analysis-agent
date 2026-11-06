"""数据分析节点

对查询结果进行统计分析，返回结构化的分析摘要。
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.agent.daysince import today_context
from app.llm.factory import get_llm

ANALYZE_PROMPT = """你是一个数据分析师。根据查询结果，生成分析摘要。

分析类型: {analysis_type}
用户问题: {question}
查询结果 (前100行):
{data}

请返回 JSON:
{{
  "summary": "分析摘要（2-5句话）",
  "key_findings": ["发现1", "发现2"],
  "numbers": {{"关键数值1": "值1"}},
  "insight": "一句话核心洞察"
}}
"""


async def analyze_results(state: AgentState) -> AgentState:
    """分析查询结果"""
    llm = get_llm()
    user_input = state.get("user_input", "")
    analysis_type = state.get("analysis_type", "summary")
    query_result_json = state.get("query_result_json", "{}")

    try:
        result = json.loads(query_result_json)
        rows = result.get("rows", [])[:100]  # 只取前 100 行给 LLM
        columns = result.get("columns", [])
    except json.JSONDecodeError:
        rows, columns = [], []

    # 格式化为表格
    data_str = "\t".join(columns) + "\n"
    for row in rows[:50]:
        data_str += "\t".join(str(v) for v in row) + "\n"

    prompt = ANALYZE_PROMPT.format(analysis_type=analysis_type, question=user_input, data=data_str)
    full_prompt = today_context() + "\n\n" + prompt

    try:
        resp = await llm.chat([{"role": "system", "content": full_prompt}, {"role": "user", "content": "请分析"}])
        resp = resp.strip()
        if resp.startswith("```"):
            resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
        analysis = json.loads(resp)

        return {
            **state,
            "analysis_summary": analysis.get("summary", ""),
        }
    except Exception as e:
        return {**state, "analysis_summary": f"Analysis failed: {e}"}
