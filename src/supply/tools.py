import os
import re
import math
import logging
import json
from datetime import datetime, timedelta
from typing import Any, List, Dict, Optional

from .database import Database
from .data_import import DataImporter
from .forecast_models import ForecastEngine
from .i18n import I18n

_ = I18n.t

logger = logging.getLogger(__name__)


class Tool:
    name: str

    def can_handle(self, prompt: str) -> bool:
        return True

    def run(self, prompt: str) -> Any:
        raise NotImplementedError


class DataTool(Tool):
    name = "data"

    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.importer = DataImporter(self.db)

    def can_handle(self, prompt: str) -> bool:
        return "数据" in prompt or "加载" in prompt or "导入" in prompt or "data" in prompt.lower() or "load" in prompt.lower() or "import" in prompt.lower()

    def run(self, prompt: str) -> Dict[str, Any]:
        action = "generate"
        if "导入" in prompt or "import" in prompt.lower():
            action = "import"
        elif "生成" in prompt or "generate" in prompt.lower():
            action = "generate"
        
        try:
            if action == "generate":
                m = re.search(r"周期\s*=\s*(\d+)", prompt)
                weeks = int(m.group(1)) if m else 104
                m = re.search(r"产品\s*=\s*(\d+)", prompt)
                num_products = int(m.group(1)) if m else 5
                
                count = self.importer.generate_realistic_data(weeks=weeks)
                
                return {
                    "status": "success",
                    "action": "generate",
                    "records": count,
                    "message": f"生成{count}条模拟数据"
                }
            elif action == "import":
                m = re.search(r"路径\s*=\s*[\"']?([^\"'\s]+)[\"']?", prompt)
                if not m:
                    return {"status": "error", "message": "请提供文件路径"}
                csv_path = m.group(1)
                count = self.importer.import_csv(csv_path)
                return {
                    "status": "success",
                    "action": "import",
                    "records": count,
                    "message": f"从CSV导入{count}条数据"
                }
            
            stats = self.db.get_data_stats()
            return {
                "status": "info",
                "stats": stats,
                "message": f"数据库统计: {stats}"
            }
        except Exception as e:
            logger.error(f"数据工具执行失败: {e}")
            return {"status": "error", "message": str(e)}


class ForecastTool(Tool):
    name = "forecast"

    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.engine = ForecastEngine()

    def can_handle(self, prompt: str) -> bool:
        # 修复原版路由缺陷："库存周期=12" 含"周期"会被误路由到本工具。
        # "周期"仅在不含库存/订单语义时作为兜底关键词。
        if "预测" in prompt or "forecast" in prompt.lower():
            return True
        if "周期" in prompt and "库存" not in prompt and "订单" not in prompt:
            return True
        return False

    def _parse_horizon(self, prompt: str) -> int:
        m = re.search(r"周期\s*=\s*(\d+)", prompt)
        if m:
            return int(m.group(1))
        m = re.search(r"horizon\s*=\s*(\d+)", prompt, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return 12

    def run(self, prompt: str) -> Dict[str, Any]:
        horizon = self._parse_horizon(prompt)
        
        data = self.db.get_demand_data()
        if not data:
            return {"status": "error", "message": "没有历史数据，请先加载数据"}
        
        try:
            results = self.engine.forecast(data, horizon=horizon)
            
            for product_id, result in results.items():
                predictions = result.get("predictions", [])
                start_date = datetime.now()
                for i, pred in enumerate(predictions):
                    forecast_date = (start_date + timedelta(weeks=i)).strftime('%Y-%m-%d')
                    self.db.save_forecast(
                        product_id=product_id,
                        forecast_date=forecast_date,
                        predicted_demand=pred,
                        model_name="ensemble"
                    )
            
            summary = {}
            for pid, result in results.items():
                summary[pid] = {
                    "predictions": result["predictions"],
                    "confidence_lower": result.get("confidence_lower", []),
                    "confidence_upper": result.get("confidence_upper", []),
                    "metrics": result.get("metrics", {})
                }
            
            return {
                "status": "success",
                "horizon": horizon,
                "forecast": summary,
                "message": f"预测完成，{len(results)}个产品，{horizon}期"
            }
        except Exception as e:
            logger.error(f"预测失败: {e}")
            return {"status": "error", "message": str(e)}


class InventoryTool(Tool):
    name = "inventory"

    def __init__(self, db: Database = None):
        self.db = db or Database()

    def can_handle(self, prompt: str) -> bool:
        return "库存" in prompt or "订单" in prompt or "inventory" in prompt.lower() or "order" in prompt.lower()

    def run(self, prompt: str) -> Dict[str, Any]:
        m = re.search(r"周期\s*=\s*(\d+)", prompt)
        horizon = int(m.group(1)) if m else 12
        
        forecasts = self.db.get_forecasts()
        if not forecasts:
            return {"status": "error", "message": "没有预测数据，请先执行预测"}
        
        products = self.db.get_products()
        demand_data = self.db.get_demand_data()
        
        by_product_forecast = {}
        for fc in forecasts:
            by_product_forecast.setdefault(fc['product_id'], []).append(fc)
        
        by_product_demand = {}
        for dd in demand_data:
            by_product_demand.setdefault(dd['product_id'], []).append(dd['demand'])
        
        orders = {}
        for product in products:
            product_id = product['product_id']
            lead_time = product.get('lead_time', 7)
            service_level = product.get('service_level', 0.95)
            unit_cost = product.get('unit_cost', 10)
            
            forecast_list = by_product_forecast.get(product_id, [])
            if not forecast_list:
                continue
            
            demands = by_product_demand.get(product_id, [])
            
            if len(demands) > 1:
                mean_demand = sum(demands) / len(demands)
                variance = sum((d - mean_demand) ** 2 for d in demands) / max(len(demands) - 1, 1)
                std_demand = math.sqrt(max(0, variance))
            else:
                mean_demand = demands[0] if demands else 0
                std_demand = mean_demand * 0.1
            
            z_score = 1.65 if service_level == 0.95 else 1.96 if service_level >= 0.975 else 1.28
            
            safety_stock = z_score * std_demand * math.sqrt(lead_time)
            
            avg_forecast = sum(fc['predicted_demand'] for fc in forecast_list[:min(horizon, len(forecast_list))]) / min(horizon, len(forecast_list))
            target_stock = avg_forecast * lead_time + safety_stock
            
            ordering_cost = 50 + unit_cost * 0.1
            holding_cost = unit_cost * 0.2
            
            eoq = math.sqrt((2 * avg_forecast * ordering_cost) / max(holding_cost, 0.01))
            
            order_sequence = []
            current_inventory = 0
            for i in range(min(horizon, len(forecast_list))):
                period_demand = forecast_list[i]['predicted_demand']
                net_need = max(0, target_stock - current_inventory)
                order_qty = max(net_need, eoq) if net_need > 0 else 0
                order_qty = round(order_qty, 2)
                
                order_sequence.append({
                    "period": i + 1,
                    "order_quantity": order_qty,
                    "safety_stock": round(safety_stock, 2),
                    "target_stock": round(target_stock, 2),
                    "eoq": round(eoq, 2)
                })
                
                self.db.save_order(
                    product_id=product_id,
                    order_date=(datetime.now() + timedelta(weeks=i)).strftime('%Y-%m-%d'),
                    order_quantity=order_qty,
                    safety_stock=round(safety_stock, 2),
                    target_stock=round(target_stock, 2)
                )
                
                current_inventory = current_inventory + order_qty - period_demand
            
            orders[product_id] = order_sequence
        
        return {
            "status": "success",
            "horizon": horizon,
            "orders": orders,
            "message": f"库存优化完成，{len(orders)}个产品"
        }


class ReportTool(Tool):
    name = "report"

    def __init__(self, db: Database = None):
        self.db = db or Database()

    def can_handle(self, prompt: str) -> bool:
        return "报告" in prompt or "总结" in prompt or "report" in prompt.lower() or "summary" in prompt.lower()

    def run(self, prompt: str) -> Dict[str, Any]:
        try:
            stats = self.db.get_data_stats()
            forecasts = self.db.get_forecasts()
            orders = self.db.get_demand_data()
            
            report_lines = [I18n.t("report_title")]
            report_lines.append(I18n.t("report_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            report_lines.append("")
            report_lines.append(I18n.t("report_overview"))
            report_lines.append(I18n.t("report_products", stats.get('products', 0)))
            report_lines.append(I18n.t("report_records", stats.get('demand_records', 0)))
            report_lines.append(I18n.t("report_forecasts", stats.get('forecasts', 0)))
            report_lines.append("")
            
            by_product_forecast = {}
            for fc in forecasts:
                by_product_forecast.setdefault(fc['product_id'], []).append(fc)
            
            report_lines.append(I18n.t("report_forecast_per"))
            for pid, fcs in by_product_forecast.items():
                if fcs:
                    latest = fcs[0]['predicted_demand']
                    last = fcs[-1]['predicted_demand']
                    growth = ((last - latest) / max(latest, 0.01)) * 100
                    report_lines.append(I18n.t("report_item", pid, latest, last, growth))
            
            return {
                "status": "success",
                "report": "\n".join(report_lines),
                "stats": stats
            }
        except Exception as e:
            logger.error(f"报告生成失败: {e}")
            return {"status": "error", "message": str(e)}
