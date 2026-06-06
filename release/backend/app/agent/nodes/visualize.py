"""Visualization node — builds ECharts option from real query results."""

import json

from app.agent.state import AgentState


async def generate_visualization(state: AgentState) -> AgentState:
    """Build ECharts config from real query results — no LLM needed"""
    analysis_type = state.get("analysis_type", "summary")
    query_result_json = state.get("query_result_json", "{}")

    try:
        result = json.loads(query_result_json)
        rows = result.get("rows", [])[:20]
        columns = result.get("columns", [])
    except json.JSONDecodeError:
        rows, columns = [], []

    if not columns or not rows:
        return {**state, "chart_config_json": "{}"}

    # --- Build ECharts option programmatically from real data ---
    # Use first column as labels, remaining numeric columns as series
    labels = [str(r[0]) for r in rows] if len(columns) > 0 else []
    numeric_data = []
    for ci in range(1, len(columns)):
        try:
            values = [float(r[ci]) if r[ci] is not None else 0 for r in rows]
            if any(v != 0 for v in values):
                numeric_data.append({"name": str(columns[ci]), "data": values})
        except (ValueError, TypeError):
            pass

    chart_type = "bar"
    if analysis_type == "trend":
        chart_type = "line"
    elif analysis_type == "proportion" or analysis_type == "calculate":
        chart_type = "bar"
    elif analysis_type == "correlation":
        chart_type = "scatter"

    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [s["name"] for s in numeric_data], "textStyle": {"color": "#8fa3b8"}},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
    }

    if chart_type == "pie":
        if numeric_data:
            option.update({
                "tooltip": {"trigger": "item"},
                "series": [{
                    "name": numeric_data[0]["name"],
                    "type": "pie",
                    "radius": "60%",
                    "data": [{"name": labels[i], "value": numeric_data[0]["data"][i]} for i in range(min(len(labels), len(numeric_data[0]["data"])))],
                    "label": {"color": "#8fa3b8"},
                }],
            })
    elif chart_type == "scatter":
        if len(numeric_data) >= 2:
            option.update({
                "xAxis": {"type": "value", "name": numeric_data[0]["name"], "nameTextStyle": {"color": "#8fa3b8"}},
                "yAxis": {"type": "value", "name": numeric_data[1]["name"], "nameTextStyle": {"color": "#8fa3b8"}},
                "series": [{
                    "name": f"{numeric_data[0]['name']} vs {numeric_data[1]['name']}",
                    "type": "scatter",
                    "data": [[numeric_data[0]["data"][i], numeric_data[1]["data"][i]] for i in range(min(len(numeric_data[0]["data"]), len(numeric_data[1]["data"])))],
                }],
            })
    else:
        option.update({
            "xAxis": {"type": "category", "data": labels, "axisLabel": {"color": "#8fa3b8", "rotate": 30}},
            "yAxis": {"type": "value", "axisLabel": {"color": "#8fa3b8"}},
            "series": [
                {"name": s["name"], "type": chart_type, "data": s["data"], "itemStyle": {"color": "#4da6ff"}}
                for s in numeric_data
            ],
        })

    chart_config = {
        "chart_type": chart_type,
        "title": f"查询结果 ({result.get('row_count', len(rows))} 行)",
        "echarts_option": option,
    }
    return {**state, "chart_config_json": json.dumps(chart_config, ensure_ascii=False)}
