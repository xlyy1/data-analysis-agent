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

QUESTION = "各城市的销售额排名"


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
    args = parser.parse_args()

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

        # 对话页：真的发一个问题，等图表渲染出来再截图
        page.goto(f"{args.base_url}/", wait_until="networkidle")
        page.wait_for_selector(".chat-input", timeout=20000)
        page.fill(".chat-input", QUESTION)
        page.keyboard.press("Enter")
        try:
            # 等 SQL 代码块或图表出现，最多 40s
            page.wait_for_function(
                """() => {
                    const text = document.body.innerText || '';
                    const hasSql = text.includes('SELECT') || text.toLowerCase().includes('limit');
                    const hasCanvas = !!document.querySelector('canvas');
                    return hasSql && hasCanvas;
                }""",
                timeout=40000,
            )
        except Exception as error:  # noqa: BLE001 - 截不到理想状态也要出图
            print(f"[warn] 等待答案渲染超时：{error}", file=sys.stderr)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out_dir / "02-chat.png"), full_page=False)
        print("captured 02-chat.png")

        for path, filename in PAGES[1:]:
            page.goto(f"{args.base_url}{path}", wait_until="networkidle")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out_dir / filename), full_page=False)
            print(f"captured {filename}")

        browser.close()
    print("done:", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
