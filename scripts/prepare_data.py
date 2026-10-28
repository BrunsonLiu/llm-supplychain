# -*- coding: utf-8 -*-
"""Download Online Retail II and build the weekly SKU demand panel.

Examples:
  python scripts/prepare_data.py
  python scripts/prepare_data.py --xlsx data/raw/online_retail_II.xlsx --top-n 100
  python scripts/prepare_data.py --skip-download --start-week 2010-12-06
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.data import (  # noqa: E402
    build_online_retail_panel,
    download_online_retail_ii,
    save_panel,
)


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and prepare Online Retail II weekly panel")
    parser.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"), help="原始数据目录")
    parser.add_argument("--out-dir", default=str(ROOT / "data" / "processed"), help="面板输出目录")
    parser.add_argument("--xlsx", default=None, help="已有 xlsx 路径（跳过下载）")
    parser.add_argument("--cache", default=None, help="原始数据 parquet 缓存路径")
    parser.add_argument("--top-n", type=int, default=200, help="保留的 SKU 数（ABC 分析）")
    parser.add_argument("--min-nonzero-weeks", type=int, default=26, help="最少非零需求周数")
    parser.add_argument(
        "--rank-by", default="revenue", choices=["revenue", "demand"], help="SKU 排序依据"
    )
    parser.add_argument("--start-week", default=None, help="面板起始周（YYYY-MM-DD，周一）")
    parser.add_argument("--end-week", default=None, help="面板结束周（YYYY-MM-DD，周一）")
    parser.add_argument("--skip-download", action="store_true", help="不下载，必须已有 --xlsx")
    parser.add_argument("--force-download", action="store_true", help="强制重新下载")
    return parser.parse_args()


def main() -> None:
    _configure_stdout()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    raw_dir = Path(args.raw_dir)
    if args.xlsx:
        xlsx_path = Path(args.xlsx)
    else:
        if args.skip_download:
            xlsx_path = raw_dir / "online_retail_II.xlsx"
        else:
            xlsx_path = download_online_retail_ii(raw_dir, force=args.force_download)
    if not xlsx_path.exists():
        raise SystemExit(
            f"找不到数据文件: {xlsx_path}\n"
            "请先运行下载，或用 --xlsx 指向已解压的 online_retail_II.xlsx。"
        )

    cache_path = Path(args.cache) if args.cache else xlsx_path.with_suffix(".raw.parquet")
    print(f"[1/3] 读取并清洗 {xlsx_path}")
    panel, meta = build_online_retail_panel(
        xlsx_path,
        raw_cache=cache_path,
        top_n=args.top_n,
        min_nonzero_weeks=args.min_nonzero_weeks,
        rank_by=args.rank_by,
        start_week=args.start_week,
        end_week=args.end_week,
    )

    print(f"[2/3] 面板: {meta['skus_selected']} SKU x {meta['weeks']} 周 = {meta['rows']} 行")
    print(f"      时间范围: {meta['start_week']} -> {meta['end_week']}")
    print(f"      零需求占比: {meta['zero_share']:.2%}")
    print("      清洗统计:", json.dumps(meta["clean_stats"], ensure_ascii=False))

    panel_path, meta_path = save_panel(panel, meta, args.out_dir)
    print(f"[3/3] 已写入: {panel_path}")
    print(f"      元数据: {meta_path}")


if __name__ == "__main__":
    main()
