"""诊断节点的契约测试。

背景：真实验收跑 Docker 时发现 `diagnosis_suggestions` 全是 "[中优先级/中等难度] "
（建议正文为空），根因是 Mock 的输出不符合节点契约、而节点对偏差输出又是静默丢弃。
这里把"建议必须有正文"钉成断言，防止再次静默丢数据。
"""

from __future__ import annotations

import json

import pytest

from app.agent.nodes.diagnose import diagnose
from app.llm import mock as mock_module
from app.llm.mock import MockLLM

pytestmark = pytest.mark.asyncio

BASE_STATE = {
    "user_input": "哪个渠道的利润最低，为什么",
    "analysis_summary": "批发渠道利润最低",
    "query_result_json": json.dumps(
        {
            "columns": ["渠道", "利润"],
            "rows": [["线下", 100], ["线上", 80], ["批发", 20]],
        },
        ensure_ascii=False,
    ),
}


class _FixedLLM:
    def __init__(self, payload):
        self._payload = payload

    async def chat(self, messages, **kwargs):
        return json.dumps(self._payload, ensure_ascii=False)


class TestDiagnoseContract:
    async def test_mock_output_produces_non_empty_suggestions(self, monkeypatch):
        """默认 mock 必须走通契约：每个建议都要有正文，不能只剩优先级前缀。"""
        monkeypatch.setattr(mock_module.MockLLM, "chat", MockLLM.chat)
        result = await diagnose(dict(BASE_STATE))

        assert result["diagnosis_causes"], "应产出原因"
        assert len(result["diagnosis_suggestions"]) == len(result["diagnosis_causes"])
        for suggestion in result["diagnosis_suggestions"]:
            body = suggestion.split("]", 1)[-1].strip()
            assert body, f"建议正文为空：{suggestion!r}"
            assert len(body) >= 6

    async def test_documented_shape_is_parsed(self, monkeypatch):
        payload = {
            "causes": [
                {
                    "cause": "批发渠道成本倒挂",
                    "evidence": "批发渠道每单利润为负",
                    "suggestion": "把批发折扣从 8.2 折收到 9 折",
                    "priority": "高",
                    "difficulty": "容易",
                }
            ]
        }
        monkeypatch.setattr(
            "app.agent.nodes.diagnose.get_llm", lambda: _FixedLLM(payload)
        )
        result = await diagnose(dict(BASE_STATE))
        assert result["diagnosis_causes"] == ["批发渠道成本倒挂"]
        assert result["diagnosis_evidence"] == ["批发渠道每单利润为负"]
        assert result["diagnosis_suggestions"] == ["[高优先级/容易难度] 把批发折扣从 8.2 折收到 9 折"]

    async def test_sibling_suggestions_list_is_not_dropped(self, monkeypatch):
        """模型把建议放到顶层 suggestions 时，也要按序号补回，而不是留空。"""
        payload = {
            "causes": [{"cause": "A", "evidence": "e1"}, {"cause": "B", "evidence": "e2"}],
            "suggestions": ["建议一：调整售价", "建议二：收紧折扣"],
        }
        monkeypatch.setattr(
            "app.agent.nodes.diagnose.get_llm", lambda: _FixedLLM(payload)
        )
        result = await diagnose(dict(BASE_STATE))
        assert "建议一：调整售价" in result["diagnosis_suggestions"][0]
        assert "建议二：收紧折扣" in result["diagnosis_suggestions"][1]

    async def test_plain_string_causes_are_tolerated(self, monkeypatch):
        payload = {"causes": ["原料涨价", "渠道折扣过大"]}
        monkeypatch.setattr(
            "app.agent.nodes.diagnose.get_llm", lambda: _FixedLLM(payload)
        )
        result = await diagnose(dict(BASE_STATE))
        assert result["diagnosis_causes"] == ["原料涨价", "渠道折扣过大"]
        assert len(result["diagnosis_suggestions"]) == 2


class _CapturingLLM:
    def __init__(self):
        self.prompts: list[str] = []

    async def chat(self, messages, **kwargs):
        self.prompts.append("\n".join(m["content"] for m in messages))
        return "回复"


class TestDiagnosisReachesAnswerPrompt:
    async def test_suggestions_are_injected_into_response_prompt(self, monkeypatch):
        """诊断结果必须真的进入"生成回答"的 prompt。

        mock 模型的最终文案是固定模板（那是模型能力，不是链路问题），
        所以这里断言的是**链路**：causes / suggestions 确实被传给了回答节点。
        """
        import app.agent.nodes.respond as respond_module

        captured = _CapturingLLM()
        monkeypatch.setattr(respond_module, "get_llm", lambda: captured)

        state = {
            "user_input": "哪个渠道的利润最低，为什么",
            "analysis_type": "anomaly",
            "analysis_summary": "批发渠道利润最低",
            "diagnosis_causes": ["批发渠道成本倒挂"],
            "diagnosis_suggestions": ["[高优先级/容易难度] 收紧批发折扣至 9 折"],
            "error": "",
            "empty_result": False,
        }
        result = await respond_module.format_response(state)

        assert captured.prompts, "回答节点必须调用模型"
        prompt = captured.prompts[0]
        assert "批发渠道成本倒挂" in prompt, "原因没进 prompt"
        assert "收紧批发折扣至 9 折" in prompt, "建议没进 prompt"
        assert result["final_response"] == "回复"
