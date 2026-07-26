"""报告生成服务

支持 Markdown、PDF、HTML 格式的报告导出。
"""

import io
import json
import os
from datetime import datetime


class ReportService:
    """报告生成器"""

    @staticmethod
    def generate_markdown(
        question: str,
        analysis: str,
        causes: list[str],
        suggestions: list[str],
        sql: str,
        data_columns: list[str],
        data_rows: list[list],
    ) -> str:
        """生成 Markdown 报告"""
        lines = [
            f"# 数据分析报告",
            f"",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"## 原始问题",
            f"",
            f"> {question}",
            f"",
            f"## 分析结论",
            f"",
            f"{analysis}",
            f"",
        ]

        if causes:
            lines.append("## 原因诊断")
            lines.append("")
            for c in causes:
                lines.append(f"- {c}")
            lines.append("")

        if suggestions:
            lines.append("## 优化建议")
            lines.append("")
            for s in suggestions:
                lines.append(f"- {s}")
            lines.append("")

        if sql:
            lines.append("## 查询 SQL")
            lines.append("")
            lines.append(f"```sql\n{sql}\n```")
            lines.append("")

        if data_columns and data_rows:
            lines.append("## 数据表格")
            lines.append("")
            lines.append("| " + " | ".join(data_columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(data_columns)) + " |")
            for row in data_rows[:20]:
                lines.append("| " + " | ".join(str(v) if v is not None else "" for v in row) + " |")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_html(markdown_content: str) -> str:
        """将 Markdown 转为 HTML"""
        import markdown

        md = markdown.Markdown(extensions=["tables", "fenced_code"])
        body = md.convert(markdown_content)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>数据分析报告</title>
    <style>
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; color: #333; }}
        h1 {{ border-bottom: 2px solid #1a73e8; padding-bottom: 10px; }}
        h2 {{ color: #1a73e8; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
        th {{ background: #f5f5f5; }}
        blockquote {{ border-left: 4px solid #1a73e8; padding: 10px 20px; background: #f8f9fa; margin: 15px 0; }}
        pre {{ background: #f4f4f4; padding: 15px; border-radius: 6px; overflow-x: auto; }}
    </style>
</head>
<body>
{body}
</body>
</html>"""

    @staticmethod
    def generate_pdf(html_content: str) -> bytes:
        """将 HTML 转为 PDF"""
        try:
            from weasyprint import HTML
            return HTML(string=html_content).write_pdf()
        except ImportError:
            pass

        # Fallback: simple PDF with system CJK font or ASCII-only
        from fpdf import FPDF

        pdf = FPDF()
        pdf.add_page()

        # Try to find a usable CJK font on the current system
        font_path = None
        font_name = "Helvetica"

        if os.name == "nt":
            # Windows: try Microsoft YaHei (installed by default)
            candidates = [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/msyh.ttf",
                "C:/Windows/Fonts/simsun.ttc",
                "C:/Windows/Fonts/simhei.ttf",
            ]
        else:
            candidates = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            ]

        for candidate in candidates:
            if os.path.isfile(candidate):
                font_path = candidate
                font_name = "CJK"
                break

        if font_path:
            pdf.add_font(font_name, "", font_path, uni=True)
            pdf.set_font(font_name, "", 12)
        else:
            pdf.set_font(font_name, "", 12)

        # Strip HTML tags for plain text
        import re
        text = re.sub(r"<[^>]+>", "", html_content)
        text = re.sub(r"\n{3,}", "\n\n", text)

        for line in text.split("\n"):
            safe_line = line[:120]
            if font_path:
                pdf.cell(0, 8, safe_line, ln=True)
            else:
                # No CJK font: strip non-ASCII to avoid encoding errors
                pdf.cell(0, 8, safe_line.encode("ascii", errors="replace").decode(), ln=True)

        # fpdf2 newer versions return bytes directly from output(dest="S")
        result = pdf.output(dest="S")
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        return result.encode("latin-1")
