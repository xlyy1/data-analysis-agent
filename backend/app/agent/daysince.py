"""时间上下文 — 为 Agent 注入当前真实日期

LLM 模型训练数据截止于 2024 年，不知道"今天"是什么日期。
当用户问"上个月""去年""本周"时，Agent 必须基于真实日期计算时间范围。
"""

from datetime import datetime, timedelta, timezone, tzinfo

# China Standard Time (UTC+8)
_CST = timezone(timedelta(hours=8))


def now_cst() -> datetime:
    """Return current datetime in China Standard Time (UTC+8)."""
    return datetime.now(timezone.utc).astimezone(_CST)


def today_context() -> str:
    """生成完整的时间上下文文本，注入到每个 LLM 提示词中"""
    now = now_cst()
    today_str = now.strftime("%Y年%m月%d日")
    weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]

    # 当前年、月
    current_year = now.year
    current_month = now.month

    # 上个月
    if current_month == 1:
        last_month_year = current_year - 1
        last_month_num = 12
    else:
        last_month_year = current_year
        last_month_num = current_month - 1

    # 上个月第一天和最后一天
    first_of_current = now.replace(day=1)
    last_of_last = first_of_current - timedelta(days=1)
    first_of_last = last_of_last.replace(day=1)

    # 去年
    last_year = current_year - 1

    # 本季度
    quarter_start_month = ((current_month - 1) // 3) * 3 + 1
    first_of_quarter = now.replace(month=quarter_start_month, day=1)

    # 本周一
    monday = now - timedelta(days=now.weekday())

    # 30 天前
    thirty_days_ago = now - timedelta(days=30)

    return f"""## 当前时间上下文（非常重要！必须据此计算时间范围）

今天是 {today_str}（{weekday}）。
当前年份: {current_year}年
当前月份: {current_year}年{current_month:02d}月

### 常见时间范围的精确日期
| 用户说法 | 精确日期范围 |
|---------|------------|
| "上个月" | {first_of_last.strftime('%Y-%m-%d')} 至 {last_of_last.strftime('%Y-%m-%d')}（{last_month_year}年{last_month_num}月） |
| "去年" / "去年同期" | {last_year}年全年，或 {last_year}年{current_month}月 |
| "本月" / "这个月" | {now.strftime('%Y-%m')}-01 至今 |
| "本季度" | {first_of_quarter.strftime('%Y-%m')}-01 至今 |
| "本周" | {monday.strftime('%Y-%m-%d')} 至今 |
| "最近30天" | {thirty_days_ago.strftime('%Y-%m-%d')} 至今 |
| "今年" | {current_year}年01月01日 至今 |

### 示例
- 用户说"查上个月的数据"，SQL 的 WHERE 条件应为:
  `WHERE date_column >= '{first_of_last.strftime('%Y-%m-%d')}' AND date_column <= '{last_of_last.strftime('%Y-%m-%d')}'`
- 用户说"今年销售额"，SQL 应为:
  `WHERE date_column >= '{current_year}-01-01'`
- 用户说"和去年对比"，应该查 {current_year} 年和 {last_year} 年同期数据

请用上述精确日期替换用户问题中的模糊时间表述。"""
