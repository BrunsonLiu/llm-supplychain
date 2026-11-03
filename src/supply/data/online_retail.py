"""Online Retail II: download, clean, and aggregate transactions to weekly SKU demand.

The public dataset has no inventory, lead-time, or warehouse-network fields.
Those belong to a documented assumption layer used by later optimization modules.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

DATASET_NAME = "online_retail_ii"
DATASET_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
DATASET_SOURCE = "UCI Machine Learning Repository, dataset 502"
MIN_ZIP_BYTES = 40_000_000
# Product codes are five digits with up to two letter suffixes (e.g. 85123A,
# 15056BL). This excludes postage (POST), discounts (D), manual entries (M),
# bank charges, gift vouchers, and other non-inventory rows.
PRODUCT_CODE_PATTERN = r"^\d{5}[A-Za-z]{0,2}$"

_COLUMN_MAP = {
    "Invoice": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "price",
    "Customer ID": "customer_id",
    "Country": "country",
}


def download_online_retail_ii(
    raw_dir: str | Path,
    force: bool = False,
    max_retries: int = 6,
) -> Path:
    """Download and extract ``online_retail_II.xlsx``; return its path.

    The UCI host does not support HTTP range requests, so a failed transfer
    restarts from byte zero. Existing complete files are reused.
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / "online_retail_ii.zip"
    xlsx_path = raw_dir / "online_retail_II.xlsx"

    if xlsx_path.exists() and xlsx_path.stat().st_size > MIN_ZIP_BYTES and not force:
        logger.info("复用已解压数据: %s", xlsx_path)
        return xlsx_path

    if force or not zip_path.exists() or zip_path.stat().st_size < MIN_ZIP_BYTES:
        _stream_download(DATASET_URL, zip_path, max_retries=max_retries)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise zipfile.BadZipFile(f"损坏的压缩成员: {bad_member}")
            members = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
            if not members:
                raise zipfile.BadZipFile("压缩包内未找到 xlsx 文件")
            with zf.open(members[0]) as src, open(xlsx_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile:
        zip_path.unlink(missing_ok=True)
        raise

    logger.info("数据已解压: %s (%.1f MB)", xlsx_path, xlsx_path.stat().st_size / 1e6)
    return xlsx_path


def _stream_download(url: str, dest: Path, max_retries: int = 6) -> Path:
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("下载数据集 (第 %d/%d 次): %s", attempt, max_retries, url)
            with requests.get(url, stream=True, timeout=(20, 180)) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                written = 0
                next_log = 5 * 1024 * 1024
                with open(tmp, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        written += len(chunk)
                        if written >= next_log:
                            if total:
                                logger.info(
                                    "下载进度: %.1f / %.1f MB",
                                    written / 1e6,
                                    total / 1e6,
                                )
                            else:
                                logger.info("下载进度: %.1f MB", written / 1e6)
                            next_log += 5 * 1024 * 1024

            if total and written < total:
                raise IOError(f"下载不完整: {written}/{total} bytes")
            if tmp.stat().st_size < MIN_ZIP_BYTES:
                raise IOError(f"文件过小: {tmp.stat().st_size} bytes")

            tmp.replace(dest)
            logger.info("下载完成: %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
            return dest
        except Exception as exc:  # noqa: BLE001 - retry any network/IO failure
            last_error = exc
            tmp.unlink(missing_ok=True)
            if attempt < max_retries:
                wait = min(30, 2 * attempt)
                logger.warning("下载失败 (%s)，%ds 后重试", exc, wait)
                time.sleep(wait)

    raise RuntimeError(f"下载失败，已重试 {max_retries} 次: {last_error}")


def load_online_retail_raw(
    xlsx_path: str | Path,
    cache_path: str | Path | None = None,
) -> pd.DataFrame:
    """Read both annual sheets and normalise column names.

    Reading the 45 MB workbook takes minutes; a parquet cache makes reruns fast.
    """
    xlsx_path = Path(xlsx_path)
    if cache_path:
        cache_path = Path(cache_path)
        cache_is_fresh = (
            cache_path.exists()
            and cache_path.stat().st_mtime >= xlsx_path.stat().st_mtime
        )
        if cache_is_fresh:
            logger.info("复用原始数据缓存: %s", cache_path)
            return pd.read_parquet(cache_path)

    logger.info("读取 Excel（约 1M 行，首次较慢）: %s", xlsx_path)
    sheets = pd.read_excel(xlsx_path, sheet_name=None, engine="openpyxl")
    frames = []
    for sheet_name, frame in sheets.items():
        frame = frame.copy()
        frame.columns = [str(col).strip() for col in frame.columns]
        frame["_sheet"] = sheet_name
        frames.append(frame)
    raw = pd.concat(frames, ignore_index=True)
    raw = raw.rename(columns=_COLUMN_MAP)

    missing = {"invoice", "stock_code", "quantity", "invoice_date", "price"} - set(raw.columns)
    if missing:
        raise ValueError(f"数据列缺失: {sorted(missing)}")

    # Invoice/stock codes mix integers and strings ("C489449"), which makes
    # pyarrow infer int64 and reject the text values when caching.
    for col in ("invoice", "stock_code", "description", "country"):
        if col in raw.columns:
            raw[col] = raw[col].astype("string")

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(cache_path, index=False)
        logger.info("原始数据缓存已写入: %s", cache_path)
    return raw


def clean_transactions(raw: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Filter cancellations, non-product codes, and non-positive values."""
    df = raw.copy()
    for col in ("invoice", "stock_code", "description", "country"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    # Numeric Excel cells stringify as "85123.0"; strip the float suffix so the
    # product-code pattern still matches.
    df["invoice"] = df["invoice"].str.replace(r"\.0$", "", regex=True).str.upper()
    df["stock_code"] = df["stock_code"].str.replace(r"\.0$", "", regex=True).str.upper()
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    required_valid = df[["invoice", "stock_code", "invoice_date", "quantity", "price"]].notna().all(axis=1)
    required_valid &= df["invoice"].str.len() > 0
    cancelled = df["invoice"].str.startswith("C")
    non_product = ~df["stock_code"].str.match(PRODUCT_CODE_PATTERN)
    non_positive = (df["quantity"] <= 0) | (df["price"] <= 0)

    keep = required_valid & ~cancelled & ~non_product & ~non_positive
    clean = df.loc[keep].copy()

    # The two annual sheets overlap in Dec 2010. Restrict deduplication to
    # invoices that appear in both sheets so legitimate repeated lines inside
    # a single sheet are not removed.
    key = ["invoice", "stock_code", "invoice_date", "quantity", "price"]
    duplicate = clean.duplicated(subset=key, keep="first")
    if "_sheet" in clean.columns:
        sheets_per_invoice = clean.groupby("invoice")["_sheet"].transform("nunique")
        duplicate &= sheets_per_invoice > 1
    before_dedup = len(clean)
    clean = clean.loc[~duplicate]
    dropped_duplicates = before_dedup - len(clean)

    clean["revenue"] = clean["quantity"] * clean["price"]
    clean["week"] = (
        clean["invoice_date"].dt.normalize()
        - pd.to_timedelta(clean["invoice_date"].dt.day_of_week, unit="D")
    )
    clean = clean.rename(columns={"stock_code": "sku"})

    stats = {
        "raw_rows": int(len(df)),
        "clean_rows": int(len(clean)),
        "dropped_invalid": int((~required_valid).sum()),
        "dropped_cancelled": int((required_valid & cancelled).sum()),
        "dropped_non_product": int((required_valid & ~cancelled & non_product).sum()),
        "dropped_non_positive": int(
            (required_valid & ~cancelled & ~non_product & non_positive).sum()
        ),
        "dropped_duplicates": int(dropped_duplicates),
        "unique_skus": int(clean["sku"].nunique()),
    }
    logger.info(
        "清洗完成: %d -> %d 行，SKU %d 个",
        stats["raw_rows"],
        stats["clean_rows"],
        stats["unique_skus"],
    )
    return clean[
        ["sku", "invoice", "week", "invoice_date", "quantity", "price", "revenue", "description", "country"]
    ], stats


def aggregate_weekly(
    clean: pd.DataFrame,
    start_week: pd.Timestamp | None = None,
    end_week: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Aggregate to a complete SKU x week panel, filling absent weeks with zero."""
    if clean.empty:
        raise ValueError("清洗后没有可用交易记录")

    min_date = clean["invoice_date"].min().normalize()
    max_date = clean["invoice_date"].max().normalize()
    first_full_week = min_date + pd.Timedelta(days=(7 - min_date.weekday()) % 7)
    last_monday = max_date - pd.Timedelta(days=max_date.weekday())
    if (max_date - last_monday).days < 6:
        last_monday -= pd.Timedelta(weeks=1)

    start = max(pd.Timestamp(start_week) if start_week is not None else first_full_week, first_full_week)
    end = min(pd.Timestamp(end_week) if end_week is not None else last_monday, last_monday)
    if start > end:
        raise ValueError(f"时间范围为空: {start.date()} -> {end.date()}")

    window = clean[(clean["week"] >= start) & (clean["week"] <= end)]
    grouped = (
        window.groupby(["sku", "week"], as_index=False)
        .agg(
            demand=("quantity", "sum"),
            revenue=("revenue", "sum"),
            orders=("invoice", "nunique"),
            description=("description", "first"),
            country=("country", "first"),
        )
    )
    grouped["avg_price"] = grouped["revenue"] / grouped["demand"].replace(0, np.nan)

    weeks = pd.date_range(start, end, freq="7D")
    skus = sorted(grouped["sku"].unique())
    full_index = pd.MultiIndex.from_product([skus, weeks], names=["sku", "week"])
    panel = grouped.set_index(["sku", "week"]).reindex(full_index)

    panel["demand"] = panel["demand"].fillna(0.0)
    panel["revenue"] = panel["revenue"].fillna(0.0)
    panel["orders"] = panel["orders"].fillna(0).astype(int)
    for col, fill in (("description", ""), ("country", "Unknown")):
        panel[col] = panel.groupby(level="sku")[col].ffill().bfill().fillna(fill)
    panel["avg_price"] = panel.groupby(level="sku")["avg_price"].ffill().bfill()
    panel["avg_price"] = (
        panel["avg_price"]
        .fillna(panel.groupby(level="sku")["avg_price"].transform("median"))
        .fillna(0.0)
    )

    panel = panel.reset_index().sort_values(["sku", "week"]).reset_index(drop=True)
    logger.info(
        "周度面板: %d SKU x %d 周 = %d 行，时间 %s -> %s",
        len(skus),
        len(weeks),
        len(panel),
        start.date(),
        end.date(),
    )
    return panel


def select_skus(
    panel: pd.DataFrame,
    top_n: int = 200,
    min_nonzero_weeks: int = 26,
    min_total_demand: float = 0.0,
    rank_by: str = "revenue",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Keep SKUs with enough non-zero history, ranked by revenue (ABC view)."""
    if rank_by not in {"revenue", "demand"}:
        raise ValueError("rank_by 必须是 'revenue' 或 'demand'")
    stats = (
        panel.groupby("sku", as_index=False)
        .agg(
            weeks=("week", "nunique"),
            nonzero_weeks=("demand", lambda s: int((s > 0).sum())),
            total_demand=("demand", "sum"),
            total_revenue=("revenue", "sum"),
        )
    )
    eligible = stats[
        (stats["nonzero_weeks"] >= min_nonzero_weeks)
        & (stats["total_demand"] > min_total_demand)
    ].sort_values(
        "total_revenue" if rank_by == "revenue" else "total_demand", ascending=False
    )
    selected = eligible.head(top_n)["sku"].tolist()
    filtered = panel[panel["sku"].isin(selected)].copy()
    logger.info(
        "SKU 筛选: %d -> %d（非零周 >= %d，按%s排序）",
        stats["sku"].nunique(),
        len(selected),
        min_nonzero_weeks,
        "销售额" if rank_by == "revenue" else "需求量",
    )
    return filtered, stats


def build_online_retail_panel(
    xlsx_path: str | Path,
    raw_cache: str | Path | None = None,
    top_n: int = 200,
    min_nonzero_weeks: int = 26,
    rank_by: str = "revenue",
    start_week: str | None = None,
    end_week: str | None = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Run the full ETL pipeline and return a weekly panel plus metadata."""
    raw = load_online_retail_raw(xlsx_path, cache_path=raw_cache)
    clean, clean_stats = clean_transactions(raw)
    panel = aggregate_weekly(
        clean,
        start_week=pd.Timestamp(start_week) if start_week else None,
        end_week=pd.Timestamp(end_week) if end_week else None,
    )
    total_skus = int(panel["sku"].nunique())
    panel, sku_stats = select_skus(
        panel, top_n=top_n, min_nonzero_weeks=min_nonzero_weeks, rank_by=rank_by
    )
    if panel.empty:
        raise ValueError(
            "筛选后没有 SKU，请降低 min_nonzero_weeks 或 top_n，或检查清洗过滤条件"
        )

    meta = {
        "dataset": DATASET_NAME,
        "source": DATASET_SOURCE,
        "source_url": DATASET_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clean_stats": clean_stats,
        "skus_before_filter": total_skus,
        "skus_selected": int(panel["sku"].nunique()),
        "weeks": int(panel["week"].nunique()),
        "rows": int(len(panel)),
        "start_week": str(panel["week"].min().date()) if len(panel) else None,
        "end_week": str(panel["week"].max().date()) if len(panel) else None,
        "total_demand": float(panel["demand"].sum()),
        "zero_share": float((panel["demand"] == 0).mean()) if len(panel) else None,
        "filters": {
            "top_n": top_n,
            "min_nonzero_weeks": min_nonzero_weeks,
            "rank_by": rank_by,
            "product_code_pattern": PRODUCT_CODE_PATTERN,
        },
    }
    meta["sku_stats"] = (
        sku_stats[sku_stats["sku"].isin(panel["sku"].unique())]
        .sort_values("total_demand", ascending=False)
        .head(50)
        .to_dict(orient="records")
    )
    return panel, meta


def save_panel(panel: pd.DataFrame, meta: Dict[str, Any], out_dir: str | Path) -> Tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panel_path = out_dir / f"{DATASET_NAME}_weekly.parquet"
    meta_path = out_dir / f"{DATASET_NAME}_weekly.meta.json"
    panel.to_parquet(panel_path, index=False)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    logger.info("面板已保存: %s", panel_path)
    return panel_path, meta_path


def load_panel(panel_path: str | Path, meta_path: str | Path | None = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    panel = pd.read_parquet(panel_path)
    panel["week"] = pd.to_datetime(panel["week"])
    meta: Dict[str, Any] = {}
    if meta_path and Path(meta_path).exists():
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    return panel, meta
