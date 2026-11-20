"""Agent 状态定义

LangGraph 图中的状态对象，包含对话上下文、查询结果、分析输出等。
"""

from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
import operator


class AgentState(TypedDict):
    """LangGraph Agent 的全局状态"""

    # 对话消息历史
    messages: Annotated[Sequence[BaseMessage], operator.add]

    # 用户原始输入
    user_input: str

    # 当前激活的数据源 ID 列表
    datasource_ids: list[str]

    # 数据源 schema 缓存 (JSON 字符串列表)
    datasource_schemas: list[str]

    # 数据源配置 (JSON 字符串列表，含 type 和 config，供 execute_query 使用)
    datasource_configs: list[str]

    # --- Agent 流程中间结果 ---

    # 意图识别结果 (JSON 字符串)
    intent: str

    # 是否需要反问澄清
    needs_clarification: bool
    clarification_question: str
    clarification_options: list[str]

    # 生成的 SQL
    generated_sql: str
    sql_explanation: str

    # SQL 是否需要用户确认 (写操作)
    sql_needs_confirmation: bool

    # SQL 执行失败后的重试计数与上一次的错误信息
    sql_retry_count: int
    sql_error: str

    # 查询返回 0 行（合法但需要明确告知，避免编造结论）
    empty_result: bool

    # 结果确定性校验的告警（数值域 / 对账）
    result_warnings: list[dict]

    # 本次取数各数据源的成败（用于降级与提示）
    datasource_status: list[dict]

    # 查询结果 (JSON 序列化)
    query_result_json: str

    # 分析结果
    analysis_type: str  # summary | trend | comparison | proportion | correlation | anomaly
    analysis_summary: str

    # 诊断结果 (针对亏损/下降/异常)
    diagnosis_causes: list[str]  # 可能原因
    diagnosis_evidence: list[str]  # 数据证据
    diagnosis_suggestions: list[str]  # 可执行建议

    # 可视化推荐 (JSON)
    chart_config_json: str

    # 最终回复
    final_response: str

    # 错误信息
    error: str

    # 本次执行的追踪 ID（由 app.observability.trace 在首个节点写入，同一次请求内共用）
    trace_id: str
