"""用本机 Edge 抓 UI 截图（作品集用）。

为什么单独写脚本：ego 浏览器的 CDP 截图在本机超时（合成器问题），
而 headless Edge 能正常出图。这里用 Playwright + channel=msedge，
不下载额外浏览器。

用法：python tools/capture_screens.py --base-url http://127.0.0.1:18080 --out ../docs/images
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = [
    ("/", "02-chat.png"),
    ("/datasources", "03-datasources.png"),
    ("/reports", "04-reports.png"),
    ("/schedules", "05-schedules.png"),
]

QUESTION = "2026年各城市的销售额排名"


def login_tokens(page, base_url: str, username: str, password: str) -> dict:
    response = page.request.post(
        f"{base_url}/api/auth/login", data={"username": username, "password": password}
    )
    if not response.ok:
        raise SystemExit(f"login failed: {response.status} {response.text()}")
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--out", default="../docs/images")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin12345")
    parser.add_argument(
        "--only",
        default="",
        help="只抓指定页，逗号分隔（chat,datasources,reports,schedules）；默认全抓",
    )
    args = parser.parse_args()
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} or {
        "chat",
        "datasources",
        "reports",
        "schedules",
    }

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        # 相对 CWD 解析（默认 ../docs/images 是相对仓库根的 backend/ 也不对，
        # 所以这里要求显式传参或用下面的默认值）
        out_dir = (Path.cwd() / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000}, device_scale_factor=1
        )
        page = context.new_page()

        # 先落到同源页面，才能写 localStorage
        page.goto(f"{args.base_url}/login", wait_until="domcontentloaded")
        tokens = login_tokens(page, args.base_url, args.username, args.password)
        page.evaluate(
            """([access, refresh]) => {
                localStorage.setItem('data_agent_access_token', access);
                localStorage.setItem('data_agent_refresh_token', refresh);
            }""",
            [tokens["access_token"], tokens["refresh_token"]],
        )

        # 对话页：开一个新对话 → 发一个带时间范围的问题 → 等回答生成完再截图
        if "chat" in wanted:
            page.goto(f"{args.base_url}/", wait_until="networkidle")
            page.wait_for_selector(".chat-input", timeout=20000)
            new_chat = page.query_selector(".new-chat")
            if new_chat:
                new_chat.click()
                page.wait_for_timeout(600)
            page.fill(".chat-input", QUESTION)
            page.keyboard.press("Enter")
            try:
                # 等"生成结束"：输入框回到提问态 + 已有 SQL + 已有图表
                page.wait_for_function(
                    """() => {
                        const box = document.querySelector('.chat-input');
                        const idle = box && !box.placeholder.includes('正在生成');
                        const text = document.body.innerText || '';
                        const hasSql = text.includes('SELECT');
                        const hasCanvas = !!document.querySelector('canvas');
                        return idle && hasSql && hasCanvas;
                    }""",
                    timeout=120000,
                )
            except Exception as error:  # noqa: BLE001 - 没等到理想状态也要出图
                print(f"[warn] 等待回答生成结束超时：{error}", file=sys.stderr)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(out_dir / "02-chat.png"), full_page=False)
            print("captured 02-chat.png")

        for path, filename in PAGES[1:]:
            key = filename.split("-", 1)[1].rsplit(".", 1)[0]
            if key not in wanted:
                continue
            page.goto(f"{args.base_url}{path}", wait_until="networkidle")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out_dir / filename), full_page=False)
            print(f"captured {filename}")

        browser.close()
    print("done:", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
