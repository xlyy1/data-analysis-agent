# 对话式数据分析师 Agent

面向中小工厂和电商商家的 AI 数据分析助手。用自然语言提问，Agent 自动完成从数据查询到经营建议的全流程。

## 功能

- **数据接入**：上传 Excel/CSV，连接 MySQL/PostgreSQL/SQLite
- **自然语言分析**：用聊天方式提问，Agent 自动生成 SQL 并执行
- **诊断与建议**：针对亏损/下降/异常自动拆解维度、输出原因和建议
- **可视化**：自动选择合适的图表类型，支持交互
- **报告导出**：一键生成 Markdown/PDF/HTML 报告
- **多轮对话**：记住上下文，模糊时主动反问澄清
- **权限控制**：按角色分配数据权限

## 快速开始

### Windows

双击项目根目录的 `start.bat`，一键启动前后端。

### 手动启动

```bash
# 1. 配置环境
cp .env.example .env
# 编辑 .env，填入 DeepSeek API Key

# 2. 安装后端依赖并启动
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. 安装前端依赖并启动（新终端）
cd frontend
npm install
npm run dev
```

# 4. 访问
# 前端: http://localhost:3000
# API 文档: http://localhost:8000/docs

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python 3.11+) |
| Agent 引擎 | LangGraph |
| LLM | DeepSeek API / Ollama 本地模型 |
| 系统数据库 | SQLite |
| 前端 | Vue 3 + TDesign + ECharts + Vite |

## 项目结构

```
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── agent/    # LangGraph Agent 引擎
│   │   ├── llm/      # LLM 抽象层
│   │   ├── datasource/ # 数据源连接器
│   │   ├── sandbox/  # 代码执行沙箱
│   │   ├── api/      # REST API 路由
│   │   ├── models/   # SQLAlchemy 模型
│   │   └── services/ # 业务逻辑
│   └── tests/
├── frontend/         # Vue 3 前端
├── start.bat         # Windows 一键启动脚本
├── .env.example
└── README.md
```

## 验收场景

参考 `docs/PRD.md` 中的四个验收场景 (A/B/C/D)。
