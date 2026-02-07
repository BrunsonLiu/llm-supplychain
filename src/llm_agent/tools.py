from typing import Any


class Tool:
    name: str

    def can_handle(self, prompt: str) -> bool:
        # Base tool handles all prompts by default; override in subclasses
        return True

    def run(self, prompt: str) -> Any:
        raise NotImplementedError


class EchoTool(Tool):
    name = "echo"

    def can_handle(self, prompt: str) -> bool:
        return True

    def run(self, prompt: str) -> str:
        # Simple echo of the input prompt
        return prompt


# Lightweight in-memory data store for demo pipeline (no external deps)
from typing import List, Dict, Any
from .store import DataStore
import datetime


class DataTool(Tool):
    name = "data"

    def can_handle(self, prompt: str) -> bool:
        return "data" in prompt.lower() or "load" in prompt.lower()

    def run(self, prompt: str) -> List[Dict[str, Any]]:
        # Generate simple synthetic data if none exists
        ds = DataStore()
        if ds.get_data():
            return ds.get_data()
        # simple synthetic data: 3 products over 52 weeks
        products = ["A", "B", "C"]
        start_date = datetime.date.today() - datetime.timedelta(weeks=52)
        data = []
        for w in range(52):
            date = start_date + datetime.timedelta(weeks=w)
            for p in products:
                # simple seasonality + noise
                base = 20 if p == "A" else 30 if p == "B" else 25
                seasonal = 5 * ((w % 12) / 12.0)
                demand = max(0, base + seasonal + (w % 4) - (w // 13) + (0.5 - 0.1 * (ord(p) % 2)))
                data.append({"date": date, "product_id": p, "demand": float(demand)})
        ds.set_data(data)
        return data


class ForecastTool(Tool):
    name = "forecast"

    def can_handle(self, prompt: str) -> bool:
        l = prompt.lower()
        return "forecast" in l or "predict" in l or "horizon" in l

    def _parse_horizon(self, prompt: str) -> int:
        import re
        m = re.search(r"horizon\s*=\s*(\d+)", prompt, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return 12

    def run(self, prompt: str) -> Dict[str, List[float]]:
        ds = DataStore()
        data = ds.get_data()
        if not data:
            # generate if missing
            DataTool().run("load demo data")
            data = ds.get_data()
        horizon = self._parse_horizon(prompt)
        # group by product
        groups: Dict[str, List[float]] = {}
        # Collect last 6 weeks for trend estimate per product
        by_prod: Dict[str, List[float]] = {}
        for rec in data:
            pid = rec["product_id"]
            demand = rec["demand"]
            by_prod.setdefault(pid, []).append(demand)
        forecasts: Dict[str, List[float]] = {}
        for pid, arr in by_prod.items():
            # use last 4 weeks for trend; if less data, pad with last value
            last = arr[-4:] if len(arr) >= 4 else arr[:]
            last_vals = last if last else [0.0]
            last_mean = sum(last_vals) / max(len(last_vals), 1)
            # simple growth rate estimate from last 4 points
            growths = []
            for i in range(1, len(last_vals)):
                if last_vals[i-1] != 0:
                    growths.append((last_vals[i] - last_vals[i-1]) / last_vals[i-1])
            avg_growth = sum(growths) / max(len(growths), 1)
            if not isinstance(avg_growth, float) or avg_growth != avg_growth:
                avg_growth = 0.0
            # forecast horizon
            preds = []
            prev = last_mean
            for _ in range(horizon):
                prev = prev * (1.0 + avg_growth)
                preds.append(round(prev, 2))
            forecasts[pid] = preds
        ds.set_forecast(forecasts)
        return forecasts


class InventoryTool(Tool):
    name = "inventory"

    def can_handle(self, prompt: str) -> bool:
        return "inventory" in prompt.lower() or "order" in prompt.lower()

    def run(self, prompt: str) -> Dict[str, List[float]]:
        ds = DataStore()
        forecast = ds.get_forecast()
        data = ds.get_data()
        horizon = 12
        # get simple lead_time and costs from prompt if provided
        import re
        m = re.search(r"horizon\s*=\s*(\d+)", prompt, re.IGNORECASE)
        if m:
            horizon = int(m.group(1))
        # current inventory per product (assume 0 for MVP)
        current_inventory = {"A": 0, "B": 0, "C": 0}
        # compute safety stock: use std of last 4 actuals per product if available
        # estimate std via simple heuristic
        import math
        stds: Dict[str, float] = {}
        by_prod: Dict[str, List[float]] = {}
        for rec in data:
            pid = rec["product_id"]
            by_prod.setdefault(pid, []).append(rec["demand"])
        for pid, vals in by_prod.items():
            last = vals[-4:] if len(vals) >= 4 else vals[:]
            if len(last) < 2:
                stds[pid] = 1.0
            mean = sum(last) / max(len(last), 1)
            var = sum((v - mean) ** 2 for v in last) / max(len(last) - 1, 1)
            stds[pid] = max(0.0, var ** 0.5)
        # compute orders per horizon based on forecast
        orders: Dict[str, List[float]] = {}
        for pid, series in forecast.items():
            lead = 2
            safety = 1.65 * stds.get(pid, 1.0)
            mean_forecast = sum(series[:min(len(series), horizon)]) / max(len(series[:min(len(series), horizon)]), 1)
            target_stock = mean_forecast * lead + safety
            current = current_inventory.get(pid, 0)
            order_qtys = []
            for _ in range(len(series)):
                need = max(0.0, target_stock - current)
                order = round(need, 2)
                order_qtys.append(order)
                current = current + order - mean_forecast
            orders[pid] = order_qtys
        ds.set_forecast(forecast)  # keep forecast accessible
        return orders


class ReportTool(Tool):
    name = "report"

    def can_handle(self, prompt: str) -> bool:
        return "report" in prompt.lower() or "summary" in prompt.lower()

    def run(self, prompt: str) -> str:
        ds = DataStore()
        forecast = ds.get_forecast()
        report_lines = ["AI-Driven Supply Chain Report"]
        report_lines.append("Forecast per product:")
        for pid, series in forecast.items():
            report_lines.append(f"- {pid}: last={series[0] if series else 0.0} horizon={len(series)}")
        return "\n".join(report_lines)
