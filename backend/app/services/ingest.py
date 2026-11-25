"""数据接入：上传文件的清洗与增量落库。

流程：上传 → 解析 → 清洗 → 落一个 SQLite 库 → 之后所有查询都走这个库。

为什么落库而不是每次查内存 DataFrame：Excel 数据源原来的实现是"每次查询都把
DataFrame 重新灌进 :memory: 再执行"，10 万行时单次查询要几秒；落库一次后查询
走索引，并且天然支持增量追加和去重。

清洗规则（都可解释、都可关）：
1. 列名去首尾空白、换行归一化成空格、空列名补名为 `col_N`、重名加后缀；
2. 丢弃整行全空的记录（Excel 常见的尾部空行）；
3. 字符串列去首尾空白，并把 "" 视作缺失；
4. 数值列尝试转 numeric（超过 90% 可解析就转，否则保持文本，避免把"0012"变 12）；
5. 完全重复的行去重；
6. 追加模式下按全行内容哈希去重（`_row_hash` 唯一索引 + INSERT OR IGNORE），
   所以重复上传同一份文件不会产生重复数据。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

HASH_COLUMN = "_row_hash"
SUPPORTED_SUFFIXES = {".xlsx", ".xls", ".csv"}
NUMERIC_PARSE_THRESHOLD = 0.9


@dataclass
class IngestResult:
    table: str
    db_path: str
    rows_in: int
    rows_written: int
    dropped_blank: int
    dropped_duplicate: int
    columns: list[str] = field(default_factory=list)
    dtypes: dict[str, str] = field(default_factory=dict)
    encoding: str = ""
    sheet: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "table": self.table,
            "db_path": self.db_path,
            "rows_in": self.rows_in,
            "rows_written": self.rows_written,
            "dropped_blank": self.dropped_blank,
            "dropped_duplicate": self.dropped_duplicate,
            "columns": self.columns,
            "dtypes": self.dtypes,
            "encoding": self.encoding,
            "sheet": self.sheet,
            "notes": self.notes,
        }


def safe_table_name(filename: str) -> str:
    """文件名 → 合法表名：保留中英文数字下划线，其余转下划线。"""
    stem = Path(filename).stem
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "_", stem).strip("_")
    return (cleaned or "data")[:64]


def _normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    seen: dict[str, int] = {}
    renamed: list[str] = []
    for index, column in enumerate(df.columns):
        name = str(column).replace("\r", " ").replace("\n", " ").strip()
        if not name or name.lower().startswith("unnamed"):
            name = f"col_{index + 1}"
            notes.append(f"第 {index + 1} 列没有列名，已命名为 {name}")
        if name in seen:
            seen[name] += 1
            new_name = f"{name}_{seen[name]}"
            notes.append(f"列名重复：{name} → {new_name}")
            name = new_name
        else:
            seen[name] = 0
        renamed.append(name)
    df.columns = renamed
    return df, notes


def _coerce_numeric(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    notes: list[str] = []
    for column in df.columns:
        if df[column].dtype.kind in "if":
            continue
        series = df[column]
        non_null = series.notna().sum()
        if non_null == 0:
            continue
        candidate = pd.to_numeric(series, errors="coerce")
        parsed = candidate.notna().sum()
        if parsed / non_null >= NUMERIC_PARSE_THRESHOLD:
            # 保留前导零的编码类字段（如 "0012"、"0301"）不转数字
            sample = series.dropna().astype(str).head(50)
            if sample.str.match(r"^0\d+$").any():
                notes.append(f"列 {column} 存在前导零，保持文本类型")
                continue
            df[column] = candidate
            notes.append(f"列 {column} 已转为数值")
    return df, notes


def clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], int, int]:
    """返回 (清洗后的 df, 备注, 丢弃空行数, 丢弃重复行数)。"""
    df, notes = _normalize_columns(df.copy())

    # 读取阶段用 keep_default_na=False 保留"0012"这类编码，代价是空单元格变成 ""；
    # 先统一成缺失值，后面的空行/唯一性判断才准。
    df = df.replace({"": None})

    blank = int(df.isna().all(axis=1).sum()) if len(df) else 0
    if blank:
        df = df[~df.isna().all(axis=1)]
        notes.append(f"丢弃 {blank} 行全空记录")

    for column in df.columns:
        # pandas 2.x 里字符串列是 object，3.x 默认是 str（StringDtype），两种都要认
        if df[column].dtype.kind in ("O", "U", "S") or pd.api.types.is_string_dtype(df[column]):
            df[column] = df[column].map(
                lambda value: value.strip() if isinstance(value, str) else value
            )
            df[column] = df[column].replace({"": None})

    df, numeric_notes = _coerce_numeric(df)
    notes.extend(numeric_notes)

    before = len(df)
    df = df.drop_duplicates()
    duplicates = before - len(df)
    if duplicates:
        notes.append(f"丢弃 {duplicates} 行完全重复记录")

    return df.reset_index(drop=True), notes, blank, duplicates


def read_table(content: bytes, filename: str) -> tuple[pd.DataFrame, str, str]:
    """解析上传内容。返回 (df, 使用的编码或 sheet, 备注)。

    统一用 `dtype=str` 读入：pandas 的类型推断会把 "0012" 变成 12.0，把长订单号
    变成科学计数法，这类编码字段一旦被"聪明地"转成数字就再也救不回来了。
    真正的数值列由 `_coerce_numeric` 在清洗阶段按 90% 可解析率重新推断。
    """
    suffix = Path(filename).suffix.lower()
    read_kwargs = {"dtype": str, "keep_default_na": False}
    if suffix == ".csv":
        last_error: Exception | None = None
        for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1"):
            try:
                df = pd.read_csv(io.BytesIO(content), encoding=encoding, **read_kwargs)
                return df, encoding, ""
            except UnicodeDecodeError as error:
                last_error = error
                continue
        raise ValueError(f"CSV 编码无法识别：{last_error}")
    if suffix in (".xlsx", ".xlsm", ".xls"):
        book = pd.ExcelFile(io.BytesIO(content))
        sheet = book.sheet_names[0]
        note = ""
        if len(book.sheet_names) > 1:
            note = f"文件含 {len(book.sheet_names)} 个 sheet，只导入第一个：{sheet}"
        return book.parse(sheet, **read_kwargs), sheet, note
    raise ValueError(f"不支持的文件类型：{suffix}")


def _row_hashes(df: pd.DataFrame) -> list[str]:
    hashes: list[str] = []
    blank_tokens = {"nan", "<na>", "none", "nat", ""}
    for row in df.astype(str).itertuples(index=False, name=None):
        raw = "\u0001".join(
            "" if str(value).lower() in blank_tokens else value for value in row
        )
        hashes.append(hashlib.sha1(raw.encode("utf-8")).hexdigest())
    return hashes


def ingest_frame(
    df: pd.DataFrame,
    *,
    db_path: Path,
    table: str,
    append: bool = False,
    notes: list[str] | None = None,
) -> IngestResult:
    import sqlite3

    cleaned, clean_notes, blank, duplicates = clean_frame(df)
    all_notes = list(notes or []) + clean_notes

    cleaned = cleaned.copy()
    cleaned[HASH_COLUMN] = _row_hashes(cleaned)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    index_name = f"ux_{table}_rowhash"
    conn = sqlite3.connect(db_path)
    try:
        existing_rows = 0
        if append:
            try:
                existing_rows = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
            except sqlite3.OperationalError:
                existing_rows = 0
            # 先摘掉唯一索引再写入，否则重复行会在插入阶段就撞约束；
            # 插完按 row_hash 去重后再把索引建回来，保证长期不变量。
            conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')
        else:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')

        cleaned.to_sql(table, conn, index=False, if_exists="append")
        if append:
            conn.execute(
                f'DELETE FROM "{table}" WHERE rowid NOT IN '
                f'(SELECT MIN(rowid) FROM "{table}" GROUP BY "{HASH_COLUMN}")'
            )
        conn.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}" ON "{table}"("{HASH_COLUMN}")'
        )
        conn.commit()
        total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        written = max(0, total - existing_rows) if append else total
    finally:
        conn.close()

    return IngestResult(
        table=table,
        db_path=str(db_path),
        # rows_in 是"文件里读到多少行"，不要把 blank 再加一次（它已经包含在 len(df) 里）
        rows_in=len(df),
        rows_written=written,
        dropped_blank=blank,
        dropped_duplicate=duplicates,
        columns=[c for c in cleaned.columns if c != HASH_COLUMN],
        dtypes={c: str(cleaned[c].dtype) for c in cleaned.columns if c != HASH_COLUMN},
        notes=all_notes,
    )


def ingest_bytes(
    content: bytes,
    filename: str,
    *,
    db_path: Path,
    table: str | None = None,
    append: bool = False,
) -> IngestResult:
    table = table or safe_table_name(filename)
    frame, encoding_or_sheet, note = read_table(content, filename)
    notes = [note] if note else []
    if Path(filename).suffix.lower() == ".csv":
        result = ingest_frame(frame, db_path=db_path, table=table, append=append, notes=notes)
        result.encoding = encoding_or_sheet
        return result
    result = ingest_frame(frame, db_path=db_path, table=table, append=append, notes=notes)
    result.sheet = encoding_or_sheet
    return result


def file_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
