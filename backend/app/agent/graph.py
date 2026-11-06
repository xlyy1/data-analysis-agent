"""LangGraph Agent graph — compiles the full analysis pipeline."""

from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes.understand import understand_intent
from app.agent.nodes.query import generate_query
from app.agent.nodes.execute import execute_query
from app.agent.nodes.analyze import analyze_results
from app.agent.nodes.diagnose import diagnose
from app.agent.nodes.visualize import generate_visualization
from app.agent.nodes.respond import format_response


def should_clarify(state: AgentState) -> str:
    if state.get("needs_clarification"):
        return "clarify"
    return "generate_query"


def should_confirm_sql(state: AgentState) -> str:
    if state.get("sql_needs_confirmation"):
        return "confirm"
    return "execute"


def should_diagnose(state: AgentState) -> str:
    analysis_type = state.get("analysis_type", "")
    if analysis_type == "anomaly":
        return "diagnose"
    user_input = state.get("user_input", "")
    diagnostic_keywords = [
        "亏损", "下降", "异常", "问题", "原因", "为什么", "怎么办", "怎么回事",
    ]
    if any(kw in user_input for kw in diagnostic_keywords):
        return "diagnose"
    return "visualize"


def build_agent_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("understand_intent", understand_intent)
    workflow.add_node("generate_query", generate_query)
    workflow.add_node("execute_query", execute_query)
    workflow.add_node("analyze_results", analyze_results)
    workflow.add_node("diagnose", diagnose)
    workflow.add_node("generate_visualization", generate_visualization)
    workflow.add_node("format_response", format_response)

    workflow.set_entry_point("understand_intent")

    workflow.add_conditional_edges(
        "understand_intent",
        should_clarify,
        {"clarify": END, "generate_query": "generate_query"},
    )

    workflow.add_conditional_edges(
        "generate_query",
        should_confirm_sql,
        {"confirm": END, "execute": "execute_query"},
    )

    # execute_query always goes to analyze_results (or END on error)
    workflow.add_edge("execute_query", "analyze_results")

    workflow.add_conditional_edges(
        "analyze_results",
        should_diagnose,
        {"diagnose": "diagnose", "visualize": "generate_visualization"},
    )

    workflow.add_edge("diagnose", "generate_visualization")
    workflow.add_edge("generate_visualization", "format_response")
    workflow.add_edge("format_response", END)

    return workflow


agent_app = build_agent_graph().compile()
