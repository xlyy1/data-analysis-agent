"""代码执行沙箱

使用 subprocess 在本地 Python 进程中执行 pandas 分析代码。
"""

import asyncio
import sys
from app.config import get_settings


class SandboxExecutor:
    """本地沙箱执行器"""

    def __init__(self):
        self.settings = get_settings()

    async def execute(self, code: str, timeout: int | None = None) -> dict:
        """执行 Python 代码

        Args:
            code: 要执行的 Python 代码
            timeout: 超时秒数，默认使用配置值

        Returns:
            {"success": bool, "output": str, "error": str}
        """
        timeout = timeout or self.settings.sandbox_timeout

        # 基础安全检查
        forbidden = [
            "import os",
            "import subprocess",
            "import socket",
            "__import__",
            "open(",
            "exec(",
            "eval(",
            "import shutil",
            "import sys",
        ]
        for kw in forbidden:
            if kw in code:
                return {
                    "success": False,
                    "output": "",
                    "error": f"Forbidden keyword: {kw}",
                }

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            if proc.returncode == 0:
                return {
                    "success": True,
                    "output": stdout.decode(errors="replace"),
                    "error": None,
                }
            else:
                return {
                    "success": False,
                    "output": stdout.decode(errors="replace"),
                    "error": stderr.decode(errors="replace"),
                }
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "success": False,
                "output": "",
                "error": "Code execution timed out",
            }
