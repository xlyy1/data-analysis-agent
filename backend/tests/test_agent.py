"""Agent 节点单元测试"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agent.state import AgentState


class TestUnderstandIntent:
    """意图理解节点测试"""

    @pytest.mark.asyncio
    async def test_summary_intent(self):
        from app.agent.nodes.understand import understand_intent

        state: AgentState = {
            "messages": [],
            "user_input": "上个月的总销售额是多少？",
            "datasource_ids": [],
            "datasource_schemas": ["table orders: order_date, product, sales, cost"],
            "intent": "",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "generated_sql": "",
            "sql_explanation": "",
            "sql_needs_confirmation": False,
            "query_result_json": "{}",
            "analysis_type": "",
            "analysis_summary": "",
            "diagnosis_causes": [],
            "diagnosis_evidence": [],
            "diagnosis_suggestions": [],
            "chart_config_json": "{}",
            "final_response": "",
            "error": "",
        }

        mock_resp = '{"analysis_type": "summary", "needs_clarification": false, "clarification_question": "", "clarification_options": [], "entities": {"time_range": "上个月", "dimensions": [], "metrics": ["销售额"]}}'

        with patch("app.agent.nodes.understand.get_llm") as mock_llm:
            mock_instance = AsyncMock()
            mock_instance.chat.return_value = mock_resp
            mock_llm.return_value = mock_instance

            result = await understand_intent(state)
            assert result["analysis_type"] == "summary"
            assert result["needs_clarification"] == False

    @pytest.mark.asyncio
    async def test_ambiguous_question(self):
        from app.agent.nodes.understand import understand_intent

        state: AgentState = {
            "messages": [],
            "user_input": "帮我看看店铺最近怎么了",
            "datasource_ids": [],
            "datasource_schemas": [],
            "intent": "",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "generated_sql": "",
            "sql_explanation": "",
            "sql_needs_confirmation": False,
            "query_result_json": "{}",
            "analysis_type": "",
            "analysis_summary": "",
            "diagnosis_causes": [],
            "diagnosis_evidence": [],
            "diagnosis_suggestions": [],
            "chart_config_json": "{}",
            "final_response": "",
            "error": "",
        }

        mock_resp = '{"analysis_type": "anomaly", "needs_clarification": true, "clarification_question": "你想分析哪个维度？", "clarification_options": ["按产品", "按渠道", "按地区"], "entities": {}}'

        with patch("app.agent.nodes.understand.get_llm") as mock_llm:
            mock_instance = AsyncMock()
            mock_instance.chat.return_value = mock_resp
            mock_llm.return_value = mock_instance

            result = await understand_intent(state)
            assert result["needs_clarification"] == True
            assert len(result["clarification_options"]) == 3


class TestGenerateQuery:
    """SQL 生成节点测试"""

    @pytest.mark.asyncio
    async def test_generates_select_only(self):
        from app.agent.nodes.query import generate_query

        state: AgentState = {
            "messages": [],
            "user_input": "每个产品的总销售额",
            "datasource_ids": [],
            "datasource_schemas": ["table products: name, sales, cost"],
            "intent": '{"analysis_type": "comparison"}',
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "generated_sql": "",
            "sql_explanation": "",
            "sql_needs_confirmation": False,
            "query_result_json": "{}",
            "analysis_type": "",
            "analysis_summary": "",
            "diagnosis_causes": [],
            "diagnosis_evidence": [],
            "diagnosis_suggestions": [],
            "chart_config_json": "{}",
            "final_response": "",
            "error": "",
        }

        mock_resp = '{"sql": "SELECT name, SUM(sales) as total_sales FROM products GROUP BY name ORDER BY total_sales DESC LIMIT 100", "explanation": "按产品名称分组汇总销售额，降序排列", "is_safe": true}'

        with patch("app.agent.nodes.query.get_llm") as mock_llm:
            mock_instance = AsyncMock()
            mock_instance.chat.return_value = mock_resp
            mock_llm.return_value = mock_instance

            result = await generate_query(state)
            assert result["generated_sql"].upper().startswith("SELECT")
            assert result["sql_needs_confirmation"] == False

    @pytest.mark.asyncio
    async def test_flags_non_select(self):
        from app.agent.nodes.query import generate_query

        state: AgentState = {
            "messages": [],
            "user_input": "删除所有订单",
            "datasource_ids": [],
            "datasource_schemas": [],
            "intent": "{}",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "generated_sql": "",
            "sql_explanation": "",
            "sql_needs_confirmation": False,
            "query_result_json": "{}",
            "analysis_type": "",
            "analysis_summary": "",
            "diagnosis_causes": [],
            "diagnosis_evidence": [],
            "diagnosis_suggestions": [],
            "chart_config_json": "{}",
            "final_response": "",
            "error": "",
        }

        mock_resp = '{"sql": "DELETE FROM orders", "explanation": "删除操作", "is_safe": false}'

        with patch("app.agent.nodes.query.get_llm") as mock_llm:
            mock_instance = AsyncMock()
            mock_instance.chat.return_value = mock_resp
            mock_llm.return_value = mock_instance

            result = await generate_query(state)
            assert result["sql_needs_confirmation"] == True


class TestAgentGraph:
    """Graph 路由逻辑测试"""

    def test_should_clarify(self):
        from app.agent.graph import should_clarify

        state_no = {"needs_clarification": False}
        assert should_clarify(state_no) == "generate_query"

        state_yes = {"needs_clarification": True}
        assert should_clarify(state_yes) == "clarify"

    def test_should_diagnose(self):
        from app.agent.graph import should_diagnose

        # 异常分析类型 → 诊断
        state_anomaly = {"analysis_type": "anomaly", "user_input": "最近销售额下降"}
        assert should_diagnose(state_anomaly) == "diagnose"

        # 包含诊断关键词 → 诊断
        state_keyword = {"analysis_type": "summary", "user_input": "为什么亏损了"}
        assert should_diagnose(state_keyword) == "diagnose"

        # 普通汇总 → 不诊断
        state_normal = {"analysis_type": "summary", "user_input": "上个月销售额是多少"}
        assert should_diagnose(state_normal) == "visualize"

    def test_should_confirm_sql(self):
        from app.agent.graph import should_confirm_sql

        assert should_confirm_sql({"sql_needs_confirmation": True}) == "confirm"
        assert should_confirm_sql({"sql_needs_confirmation": False}) == "execute"
