"""端到端自检脚本（不依赖任何付费 Key）。

用法：
    # 先起服务
    uvicorn app.main:app --port 8000        # LLM_PROVIDER=mock 时无需 API Key
    uvicorn worker_service.main:app --port 8001
    # 再跑自检
    python tools/smoke_e2e.py --base-url http://127.0.0.1:8000

覆盖：
1. /healthz /readyz /metrics
2. 登录 → 数据源列表
3. 2 个明确问题 + 1 个模糊问题（触发澄清）
4. SSE 流式（节点推进事件 + 文本 + 元数据）
5. 报告生成 + 下载（markdown / html / pdf）
6. viewer 越权：改数据源 403、建用户 403、只读问答 200
7. 恶意 SQL：注入 / 删表 / 超长 —— 全部被策略拒绝

退出码 0 表示全绿；任何一项失败都会打印原因并返回 1，可直接接进 CI。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS.append(name)
        print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", default="admin12345")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    client = httpx.Client(base_url=base, timeout=90.0)

    # ---------------------------------------------------------------- 1. 探针
    section("1. 探针 / 指标")
    health = client.get("/healthz")
    check("/healthz 200", health.status_code == 200, health.text[:120])
    ready = client.get("/readyz")
    check("/readyz 200", ready.status_code == 200, ready.text[:200])
    metrics = client.get("/metrics")
    check("/metrics 是 Prometheus 文本", metrics.status_code == 200 and "dsh_http_requests_total" in metrics.text)

    # ---------------------------------------------------------------- 2. 登录
    section("2. 登录 / 鉴权")
    unauth = client.get("/api/datasources")
    check("未带 token 访问被拒 401", unauth.status_code == 401, str(unauth.status_code))

    login = client.post(
        "/api/auth/login",
        json={"username": args.admin_user, "password": args.admin_password},
    )
    check("登录成功", login.status_code == 200, login.text[:160])
    if login.status_code != 200:
        return finish(client)
    tokens = login.json()
    admin = {"Authorization": f"Bearer {tokens['access_token']}"}
    check("拿到 access+refresh", bool(tokens.get("access_token")) and bool(tokens.get("refresh_token")))
    check("角色是 admin", tokens["user"]["role"] == "admin")

    me = client.get("/api/auth/me", headers=admin)
    check("/api/auth/me 200", me.status_code == 200 and me.json()["username"] == args.admin_user)

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    check("refresh 能换新 token", refreshed.status_code == 200)
    replay = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    check("旧 refresh token 已吊销", replay.status_code == 401, str(replay.status_code))

    # ---------------------------------------------------------------- 3. 数据源
    section("3. 数据源")
    listed = client.get("/api/datasources", headers=admin)
    check("数据源列表 200", listed.status_code == 200)
    items = listed.json().get("items", [])
    check("至少有一个数据源（样例已播种）", len(items) >= 1, f"{len(items)} 个")
    targets = [item for item in items if item.get("table_count", 0) > 0]
    check("数据源已算出 schema", bool(targets), f"{len(targets)} 个有表")
    if not items:
        return finish(client)
    ds_id = (targets or items)[0]["id"]

    profile = client.get(f"/api/datasources/{ds_id}/profile", headers=admin)
    check("数据质量画像可用", profile.status_code == 200 and "tables" in profile.json())

    # ---------------------------------------------------------------- 4. 问答
    section("4. 自然语言问答")
    questions = [
        ("各城市的销售额排名", False),
        ("哪个渠道的利润最低，为什么", False),
        ("帮我看看销售情况", True),  # 模糊 → 必须澄清
    ]
    conversation_id = None
    last_metadata: dict[str, Any] = {}
    for question, expect_clarify in questions:
        payload = {"message": question}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        response = client.post("/api/conversations/chat", headers=admin, json=payload)
        ok = response.status_code == 200
        body = response.json() if ok else {}
        conversation_id = body.get("conversation_id") or conversation_id
        if expect_clarify:
            check(
                f"模糊问题触发澄清：「{question}」",
                ok and body.get("needs_clarification") is True,
                str(body.get("clarification_question", ""))[:80],
            )
        else:
            metadata = body.get("metadata") or {}
            last_metadata = metadata or last_metadata
            check(
                f"回答问题：「{question}」",
                ok and bool(body.get("content")) and bool(metadata.get("sql")),
                (metadata.get("sql") or "").replace("\n", " ")[:100],
            )
            check(
                "返回了图表配置",
                bool(metadata.get("chart_config")),
                str((metadata.get("chart_config") or {}).get("chart_type", "")),
            )

    # ---------------------------------------------------------------- 5. SSE
    section("5. SSE 流式")
    events: list[str] = []
    with client.stream(
        "POST",
        "/api/conversations/chat/stream",
        headers=admin,
        json={"message": "各渠道销售额占比", "conversation_id": conversation_id},
    ) as stream:
        check("SSE 状态码 200", stream.status_code == 200)
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            chunk = line[6:]
            if chunk.strip() == "[DONE]":
                events.append("done")
                break
            try:
                events.append(json.loads(chunk).get("type", "?"))
            except json.JSONDecodeError:
                events.append("invalid")
    check("收到节点推进事件", "node" in events, ",".join(sorted(set(events))))
    check("收到文本增量", "text" in events)
    check("收到元数据事件", "metadata" in events)
    check("以 [DONE] 结束", "done" in events)

    # ---------------------------------------------------------------- 6. 报告
    section("6. 报告导出")
    report = client.post(
        "/api/reports/generate",
        headers=admin,
        json={"conversation_id": conversation_id, "format": "json"},
    )
    check("生成报告 200", report.status_code == 200, report.text[:160])
    report_body = report.json() if report.status_code == 200 else {}
    report_id = report_body.get("id")
    check("报告已落库有 id", bool(report_id))
    if report_id:
        for fmt in ("markdown", "html", "pdf"):
            download = client.get(f"/api/reports/{report_id}/download", headers=admin, params={"format": fmt})
            check(
                f"下载 {fmt}",
                download.status_code == 200 and len(download.content) > 50,
                f"{len(download.content)} bytes",
            )

    # ---------------------------------------------------------------- 7. 权限
    section("7. 权限（viewer 只读）")
    viewer_name = "smoke_viewer"
    client.post(
        "/api/auth/users",
        headers=admin,
        json={"username": viewer_name, "password": "viewer12345", "role": "viewer", "display_name": "只读用户"},
    )
    viewer_login = client.post(
        "/api/auth/login", json={"username": viewer_name, "password": "viewer12345"}
    )
    check("viewer 能登录", viewer_login.status_code == 200)
    if viewer_login.status_code == 200:
        viewer = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
        check("viewer 能列数据源", client.get("/api/datasources", headers=viewer).status_code == 200)
        create_ds = client.post(
            "/api/datasources",
            headers=viewer,
            json={"name": "x", "type": "sqlite", "config": {"db_path": "/tmp/x.db"}},
        )
        check("viewer 不能建数据源 403", create_ds.status_code == 403, str(create_ds.status_code))
        delete_ds = client.delete(f"/api/datasources/{ds_id}", headers=viewer)
        check("viewer 不能删数据源 403", delete_ds.status_code == 403, str(delete_ds.status_code))
        manage = client.post(
            "/api/auth/users",
            headers=viewer,
            json={"username": "hacker", "password": "hacker12345", "role": "admin"},
        )
        check("viewer 不能建用户 403", manage.status_code == 403, str(manage.status_code))
        viewer_chat = client.post(
            "/api/conversations/chat", headers=viewer, json={"message": "各城市销售额"}
        )
        check("viewer 仍可做只读问答", viewer_chat.status_code == 200)

    # ---------------------------------------------------------------- 8. 恶意 SQL
    section("8. 恶意 SQL")
    attacks = [
        ("SQL 注入（分号拼接删表）", "SELECT 1; DROP TABLE \"订单明细\""),
        ("删表", "DROP TABLE \"订单明细\""),
        ("删数据", "DELETE FROM \"订单明细\""),
        ("改数据", "UPDATE \"订单明细\" SET \"销售额\"=0"),
        ("读服务器文件", "SELECT load_file('/etc/passwd')"),
        ("超长查询", "SELECT 1" + " , 1" * 3000),
        ("PRAGMA 绕过", "PRAGMA table_info('订单明细')"),
    ]
    for label, sql in attacks:
        response = client.post("/api/sql/validate", headers=admin, json={"sql": sql})
        ok = response.status_code == 200 and response.json().get("allowed") is False
        check(f"拒绝 {label}", ok, (response.json().get("reason") or "")[:60])

    benign = client.post(
        "/api/sql/validate",
        headers=admin,
        json={"sql": "SELECT \"城市\", SUM(\"销售额\") FROM \"订单明细\" GROUP BY 1"},
    )
    benign_body = benign.json()
    check(
        "正常只读查询被放行且自动补 LIMIT",
        benign.status_code == 200
        and benign_body.get("allowed") is True
        and benign_body.get("applied_limit"),
        benign_body.get("normalized_sql", "").replace("\n", " ")[:80],
    )

    # ---------------------------------------------------------------- 9. 会话持久化
    section("9. 会话持久化")
    if conversation_id:
        messages = client.get(f"/api/conversations/{conversation_id}/messages", headers=admin)
        check("会话消息可回读", messages.status_code == 200 and len(messages.json()) >= 2, f"{len(messages.json())} 条")
        conversations = client.get("/api/conversations/", headers=admin)
        check("会话列表包含该会话", any(c["id"] == conversation_id for c in conversations.json()))

    return finish(client)


def finish(client: httpx.Client) -> int:
    print(f"\n{'=' * 60}")
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for name in FAIL:
            print(f"  - {name}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
