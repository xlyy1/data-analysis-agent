"""确定性 Mock LLM —— 让整条链路在**没有任何 API Key** 的情况下跑通。

用途（明确边界，避免被误当成"模型能力"）：
- CI / 单测：验证图路由、JSON 解析、SQL 安全闸、重试、部分成功、SSE 事件序列；
- 离线演示：`LLM_PROVIDER=mock` 时产品能点得动，不依赖外网；
- benchmark 基线：同一输入永远同一输出，适合做"机制没有回退"的回归门。

它**不是** NL2SQL 能力本身：SQL 是按 schema 里第一张表机械拼出来的
`GROUP BY` 聚合，用来喂通下游节点，不追求语义正确。真实效果必须用 DeepSeek /
Ollama 跑 `backend/bench`。
"""

from __future__ import annotations

import json
import re

from app.llm.base import BaseLLM

NUMERIC_HINTS = ("INT", "REAL", "FLOA", "DOUB", "DECIM", "NUMER", "BIGINT")

VAGUE_PATTERNS = (
    "看看",
    "情况",
    "怎么样",
    "表现如何",
    "帮我分析",
    "分析一下",
    "看一下",
)
METRIC_KEYWORDS = (
    "销售额", "销量", "利润", "成本", "收入", "毛利", "利润率", "客单价",
    "订单", "数量", "平均", "占比", "趋势", "排名", "城市", "渠道", "品类",
    "亏损", "下降", "异常", "原因", "对比", "同比", "环比", "最多", "最高",
    "最低", "总额", "合计",
)


class MockLLM(BaseLLM):
    """按 system prompt 的模板特征分派到不同固定响应。"""

    @property
    def model_name(self) -> str:
        return "mock/deterministic"

    async def chat(self, messages: list[dict], **kwargs) -> str:
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        user = "\n".join(m["content"] for m in messages if m.get("role") == "user")
        return self._dispatch(system, user)

    async def chat_stream(self, messages: list[dict], **kwargs):  # pragma: no cover - 由 chat 覆盖
        yield self._dispatch(
            "\n".join(m["content"] for m in messages if m.get("role") == "system"),
            "\n".join(m["content"] for m in messages if m.get("role") == "user"),
        )

    # ------------------------------------------------------------ dispatch

    def _dispatch(self, system: str, user: str) -> str:
        if "意图识别器" in system:
            return self._intent(user)
        if '"sql":' in system:
            return self._sql(system, user)
        if '"summary":' in system:
            return self._analyze(user)
        if '"causes":' in system:
            return self._diagnose(user)
        return self._reply(user)

    # ------------------------------------------------------------ branches

    def _intent(self, user: str) -> str:
        question = self._last_question(user)
        needs_clarification = self._is_vague(question)
        return json.dumps(
            {
                "analysis_type": self._analysis_type(question),
                "needs_clarification": needs_clarification,
                "clarification_question": (
                    "请问你想看哪个指标？例如「近三个月的销售额」或「各城市的利润率」。"
                    if needs_clarification
                    else ""
                ),
                "clarification_options": (
                    ["近三个月各渠道销售额", "各城市利润率", "销量最高的产品"]
                    if needs_clarification
                    else []
                ),
                "entities": {"time_range": "", "dimensions": [], "metrics": []},
            },
            ensure_ascii=False,
        )

    def _sql(self, system: str, user: str) -> str:
        schema = self._extract_schema(system)
        sql = self._build_sql(schema, self._last_question(user))
        return json.dumps(
            {
                "sql": sql,
                "explanation": "按 schema 里第一张表的维度列分组，对数值列求和，降序取前 20 行。",
            },
            ensure_ascii=False,
        )

    def _analyze(self, user: str) -> str:
        return json.dumps(
            {
                "summary": (
                    "查询返回了多行汇总结果，已按维度分组并按数值降序排列。"
                    "第一行是当前口径下数值最高的分组，末行最低；"
                    "组间差异明显，说明该维度对结果有区分度。"
                ),
                "key_findings": ["最高分组领先", "组间差距较大"],
            },
            ensure_ascii=False,
        )

    def _diagnose(self, user: str) -> str:
        """必须严格对齐 diagnose 节点的契约：建议放在 causes[].suggestion 里。

        历史教训：Mock 曾把建议放在顶层 `suggestions`，节点按契约取
        `causes[i].suggestion` 拿到空串，最终输出只剩 "[中优先级/中等难度] "，
        而链路其它部分是"成功"的——这类静默丢数据只能靠契约测试挡住。
        """
        return json.dumps(
            {
                "causes": [
                    {
                        "cause": "高成本低毛利品类占比偏高",
                        "evidence": "分组结果中成本相对收入偏高的分组排在末尾，拉低整体利润。",
                        "suggestion": "对低毛利品类单独核算，必要时调整售价或采购成本。",
                        "priority": "高",
                        "difficulty": "中等",
                    },
                    {
                        "cause": "渠道折扣差异",
                        "evidence": "批发类渠道单价明显低于零售，毛利被摊薄。",
                        "suggestion": "压缩批发渠道折扣力度，或设置最小起订量。",
                        "priority": "中",
                        "difficulty": "容易",
                    },
                ]
            },
            ensure_ascii=False,
        )

    def _reply(self, user: str) -> str:
        return (
            "根据查询结果，当前口径下数值最高的分组明显领先，其余分组之间的差距相对均匀。\n\n"
            "- 最高分组贡献了主要份额，是后续重点\n"
            "- 末位分组占比偏低，建议单独核查成本结构\n\n"
            "以上结论基于本次查询返回的明细汇总，如需进一步下钻可以指定城市或渠道。"
        )

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _last_question(user: str) -> str:
        """user 段可能是「问题 + 历史」，取最后一段非空行作为当前问题。"""
        lines = [line.strip() for line in user.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    @staticmethod
    def _is_vague(question: str) -> bool:
        if not question:
            return True
        if any(keyword in question for keyword in METRIC_KEYWORDS):
            return False
        return any(pattern in question for pattern in VAGUE_PATTERNS) or len(question) <= 4

    @staticmethod
    def _analysis_type(question: str) -> str:
        if any(word in question for word in ("亏损", "异常", "下降", "为什么", "原因")):
            return "anomaly"
        if any(word in question for word in ("趋势", "走势", "每月", "近三个月", "按月")):
            return "trend"
        if any(word in question for word in ("对比", "哪个", "排名", "最高", "最低", "最多")):
            return "comparison"
        if any(word in question for word in ("占比", "比例", "百分比")):
            return "proportion"
        return "summary"

    @staticmethod
    def _extract_schema(text: str) -> dict | None:
        index = text.find('"tables"')
        if index < 0:
            return None
        start = text.rfind("{", 0, index)
        if start < 0:
            return None
        try:
            payload, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _quote(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def _build_sql(self, schema: dict | None, question: str) -> str:
        tables = (schema or {}).get("tables") or []
        if not tables:
            return "SELECT 1 AS ok"
        table = tables[0]
        columns = table.get("columns") or []
        numeric = [
            column["name"]
            for column in columns
            if any(hint in str(column.get("dtype", "")).upper() for hint in NUMERIC_HINTS)
        ]
        if not numeric:
            selected = ", ".join(self._quote(column["name"]) for column in columns[:6]) or "*"
            return f"SELECT {selected} FROM {self._quote(table['name'])} LIMIT 20"

        # 维度优先选"低基数"列（schema 里带 sample_values 的），否则 GROUP BY 主键
        # 会得到一行一个订单，图表没法看；问句里点名的维度再优先一层。
        dims = [
            column["name"]
            for column in columns
            if column["name"] not in numeric and column.get("sample_values")
        ]
        if not dims:
            dims = [column["name"] for column in columns if column["name"] not in numeric]
        mentioned = [name for name in dims if name in question]
        if mentioned:
            dims = mentioned + [name for name in dims if name not in mentioned]

        metric = self._pick_metric(numeric, question)
        if dims:
            dimension = dims[0]
            return (
                f"SELECT {self._quote(dimension)} AS {self._quote('分组')}, "
                f"SUM({self._quote(metric)}) AS {self._quote('指标')} "
                f"FROM {self._quote(table['name'])} "
                f"GROUP BY {self._quote(dimension)} "
                f"ORDER BY 2 DESC LIMIT 20"
            )
        return f"SELECT SUM({self._quote(metric)}) AS {self._quote('指标')} FROM {self._quote(table['name'])}"

    @staticmethod
    def _pick_metric(numeric: list[str], question: str) -> str:
        """按问句里出现的指标词优先选列，选不到就用第一个数值列。"""
        preference = ("销售额", "金额", "收入", "利润", "销量", "数量")
        for keyword in preference:
            if keyword in question:
                for name in numeric:
                    if keyword in name:
                        return name
        for keyword in preference:
            for name in numeric:
                if keyword in name:
                    return name
        return numeric[0]


def looks_deterministic(prompt: str) -> bool:
    """给测试用：判断某个 prompt 会不会走 mock 分支。"""
    return bool(re.search(r'"sql":|"summary":|"causes":|意图识别器', prompt))
