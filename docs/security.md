# 安全说明

这份文档只回答三件事：**仓库里有没有凭据**、**跑起来之后哪些默认值必须改**、**怎么自己复核**。

## 1. 仓库里没有真实凭据（可复核）

扫描的是**全部提交**，不只是当前文件：

```console
$ git rev-list --all | wc -l
42

$ git grep -I -l -E 'sk-[A-Za-z0-9_-]{24,}'    $(git rev-list --all)   # DeepSeek/OpenAI 风格
$ git grep -I -l -E 'ghp_[A-Za-z0-9]{20,}|github_pat_' $(git rev-list --all)
$ git grep -I -l -E 'AKIA[0-9A-Z]{16}'         $(git rev-list --all)   # AWS
$ git grep -I -l -E '\-\-\-\-\-BEGIN [A-Z ]*PRIVATE KEY\-\-\-\-\-' $(git rev-list --all)
$ git grep -I -l -E 'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' $(git rev-list --all)
（以上全部无输出 = 干净）
```

| 检查项 | 结论 |
|---|---|
| `.env` 是否被提交过 | **从未**（遍历所有提交的文件树确认） |
| `.env.example` 的 Key 字段 | 全部为空（`DEEPSEEK_API_KEY=` 等长度为 0） |
| `data/`（含 `agent.db`：用户、会话、报告） | 被 gitignore，从未提交 |
| 被跟踪的 4 个 `backend/data/*.db` | 评测用的**合成数据**：`loans/books`、`visits/stores`、`orders/products`、`orders/customers/products/suppliers`，**不含** `users`/`conversations` 等表 |
| 提交信息里是否夹带密钥 | 无 |
| 文档/截图里是否出现本机路径 | 已清理（曾有一处 `C:\Users\<user>\...` 与本地 xlsx 绝对路径） |

## 2. Docker 场景下的 Key 传递

`docker compose` 会自动读取仓库根的 `.env` 做变量替换，所以 `docker compose config`
会把替换后的值打出来。为了不让宿主的真实 Key 出现在 `config` / `inspect` / 截图里：

- compose 里**不引用** `DEEPSEEK_API_KEY`，而是引用容器专用变量 `LLM_API_KEY`；
- 宿主本地跑测试仍用 `.env` 里的 `DEEPSEEK_API_KEY`（pydantic-settings 自己读）；
- 复核：`docker compose config | grep -c 'sk-'` 应为 0。

## 3. 对外部署前必须改

| 配置 | 默认值 | 为什么必须改 |
|---|---|---|
| `AUTH_SECRET_KEY` | `dev-only-change-me-in-production` | 用默认值签发的 JWT 可被伪造（拿到源码即可自签） |
| `BOOTSTRAP_ADMIN_PASSWORD` | `admin12345` | 仓库公开 = 管理员口令公开；仅在首次启动、用户表为空时生效 |
| `CORS_ORIGINS` | `*` | 任意站点可跨域调用；生产应写具体域名 |
| `SQL_ALLOW_WRITE_FOR_ADMIN` | `false` | 保持 `false`；改成 `true` 会打开写 SQL 能力 |

```bash
# 生成随机密钥
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

代码侧已有一层兜底：`APP_ENV=prod` 且仍是默认 `AUTH_SECRET_KEY` 时，启动日志会打 warning
（`app/config.py`）。

## 4. 扫描能覆盖什么、不能覆盖什么

- **能覆盖**：依赖清单漏洞（`pip-audit`、`trivy fs`）、运行镜像的 OS 包与依赖漏洞（`trivy image`）、
  被 git 跟踪的明文密钥模式。
- **不能覆盖**：`.env`、`data/` 等未提交文件；运行时注入的环境变量；业务逻辑漏洞（越权路径、
  SSRF、注入面）只能靠代码审查与测试覆盖（本项目的权限与 SQL 只读策略见
  `docs/architecture.md §3.2 / §3.8`）。
- Trivy 结果有有效期：CVE 会持续新增，需要 CI 定期跑，不是"扫过一次就安全"。
