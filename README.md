# 对话式数据分析师 Agent

面向中小工厂和电商商家的 AI 数据分析助手。用自然语言提问，Agent 自动完成从数据查询到经营建议的全流程。

## 功能

- **数据接入**：上传 Excel/CSV，连接 MySQL/PostgreSQL/SQLite
- **自然语言分析**：聊天式提问，Agent 自动生成 SQL 并执行
- **智能计算**：自动识别列名后缀，跨列聚合（如三平台销量求和），推导利率等派生指标
- **诊断与建议**：针对亏损/下降/异常自动拆解维度、输出原因和建议
- **可视化**：基于 ECharts 的交互图表，自动选择图表类型
- **报告导出**：一键生成 Markdown 报告
- **多轮对话**：记住上下文，模糊时主动反问澄清

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python 3.11+) |
| Agent 引擎 | LangGraph |
| LLM | DeepSeek API / Ollama 本地模型 / OpenAI 兼容 |
| 系统数据库 | SQLite |
| 前端 | Vue 3 + TDesign + ECharts + Vite |

## 快速开始

### 准备

1. 安装 Python 3.11+ 和 Node.js 18+
2. 克隆项目到本地

### 后端

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
# 编辑 .env，填入 DeepSeek API Key
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 访问

- 前端：http://localhost:3000
- API 文档：http://localhost:8000/docs

## 项目结构

```
├── backend/          # FastAPI 后端
│   └── app/
│       ├── agent/    # LangGraph Agent 引擎
│       ├── llm/      # LLM 抽象层
│       ├── datasource/ # 数据源连接器
│       ├── sandbox/  # 代码执行沙箱
│       ├── api/      # REST API 路由
│       ├── models/   # SQLAlchemy 模型
│       └── services/ # 业务逻辑
├── frontend/         # Vue 3 前端
│   └── src/
│       ├── components/ # UI 组件
│       ├── views/      # 页面视图
│       ├── stores/     # Pinia 状态管理
│       └── router/     # Vue Router
├── data/             # 运行时数据 (数据库、上传文件)
├── .env.example      # 环境变量模板
└── README.md
```

## Agent 工作流

```
用户提问 → 意图识别 → SQL 生成 → 数据执行 → 结果分析
                                         ↓
        格式回复 ← 可视化 ← 诊断 (可选)
```

Agent 能够：

1. **识别列名语义**：自动按后缀分组列（如"京东销量""天猫销量""拼多多销量"→"总销量"），跨列求和由代码计算保证准确性
2. **派生指标**：根据用户问题从已有列推导利率、增长率、占比等
3. **时间感知**：自动注入当前真实日期到提示词，正确理解"上个月""去年"等模糊时间表述
4. **聚合感知**：当数据为订单级时自动添加 GROUP BY 产品维度

## 环境变量

复制 `.env.example` 为 `.env`，修改：

```ini
# LLM 提供商: deepseek | ollama | openai
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_MODEL=deepseek-chat
```

## 许可

MIT
