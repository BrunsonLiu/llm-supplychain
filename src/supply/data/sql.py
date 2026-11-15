"""DuckDB/SQL access for the weekly demand panel.

This is a small, honest SQL layer: it reads the parquet panel with DuckDB and
exposes the queries used by planning benchmarks. It does not pretend to replace
the ingestion pipeline; it replaces pandas-only slicing where SQL is clearer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

import pandas as pd

try:  # optional at import time; declared in project dependencies
    import duckdb
except Exception:  # pragma: no cover - depends on environment
    duckdb = None


class SQLWarehouseError(ValueError):
    """Raised for missing files or invalid SQL requests."""


class DemandWarehouse:
    """Read-only DuckDB view over a weekly demand parquet."""

    def __init__(self, parquet_path: str | Path, read_only: bool = True) -> None:
        if duckdb is None:
            raise SQLWarehouseError("duckdb 不可用")
        path = Path(parquet_path)
        if not path.exists():
            raise SQLWarehouseError(f"parquet 不存在: {path}")
        self.path = path.resolve()
        self.conn = duckdb.connect(database=":memory:")
        # DuckDB cannot bind a parameter inside CREATE VIEW in this version;
        # use a single-quoted SQL literal with quote escaping.
        escaped = str(self.path).replace("\\", "/").replace("'", "''")
        self.conn.execute(
            f"CREATE VIEW panel AS SELECT * FROM read_parquet('{escaped}')"
        )
        self._read_only = read_only

    def query(self, sql: str, params: Optional[Sequence[Any]] = None) -> pd.DataFrame:
        """Run a read query and return a DataFrame."""
        if not sql.strip():
            raise SQLWarehouseError("SQL 不能为空")
        try:
            return self.conn.execute(sql, list(params or [])).df()
        except Exception as exc:  # noqa: BLE001
            raise SQLWarehouseError(f"SQL 执行失败: {exc}") from exc

    def weekly_demand(self) -> pd.DataFrame:
        return self.query(
            """
            SELECT CAST(week AS DATE) AS week,
                   SUM(demand) AS demand,
                   SUM(orders) AS orders
            FROM panel
            GROUP BY week
            ORDER BY week
            """
        )

    def top_skus(self, limit: int = 20) -> pd.DataFrame:
        if limit < 1:
            raise SQLWarehouseError("limit 必须为正")
        return self.query(
            """
            SELECT CAST(sku AS VARCHAR) AS sku,
                   SUM(demand) AS demand,
                   SUM(orders) AS orders
            FROM panel
            GROUP BY sku
            ORDER BY demand DESC, sku
            LIMIT ?
            """,
            [int(limit)],
        )

    def demand_for_week(self, week: str | pd.Timestamp) -> pd.DataFrame:
        return self.query(
            """
            SELECT CAST(sku AS VARCHAR) AS sku,
                   SUM(demand) AS demand,
                   SUM(orders) AS orders
            FROM panel
            WHERE CAST(week AS DATE) = CAST(? AS DATE)
            GROUP BY sku
            ORDER BY demand DESC, sku
            """,
            [str(pd.Timestamp(week).date())],
        )

    def demand_long(self) -> pd.DataFrame:
        return self.query(
            """
            SELECT CAST(week AS DATE) AS week,
                   CAST(sku AS VARCHAR) AS sku,
                   SUM(demand) AS demand
            FROM panel
            GROUP BY week, sku
            ORDER BY week, sku
            """
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "DemandWarehouse":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
