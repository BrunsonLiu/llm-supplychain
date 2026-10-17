import logging
import math
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ForecastModel:
    """预测模型基类"""
    
    name = "base"
    
    def fit(self, historical_data: List[float]) -> None:
        raise NotImplementedError
    
    def predict(self, horizon: int) -> List[float]:
        raise NotImplementedError
    
    def get_metrics(self) -> Dict[str, float]:
        return {}


class MovingAverageModel(ForecastModel):
    """移动平均模型"""
    
    name = "moving_average"
    
    def __init__(self, window: int = 4):
        self.window = window
        self.last_values = []
    
    def fit(self, historical_data: List[float]) -> None:
        self.last_values = historical_data[-self.window:] if len(historical_data) >= self.window else historical_data[:]
    
    def predict(self, horizon: int) -> Dict[str, Any]:
        if not self.last_values:
            return {"predictions": [], "confidence_interval": None}
        
        avg = sum(self.last_values) / len(self.last_values)
        predictions = [round(avg, 2)] * horizon
        
        std = math.sqrt(sum((x - avg) ** 2 for x in self.last_values) / max(len(self.last_values) - 1, 1)) if len(self.last_values) > 1 else avg * 0.1
        
        return {
            "predictions": predictions,
            "confidence_lower": [round(avg - 1.96 * std, 2)] * horizon,
            "confidence_upper": [round(avg + 1.96 * std, 2)] * horizon,
            "metrics": {"mape": self._calculate_mape(historical_data=self.last_values, predictions=predictions)}
        }
    
    def _calculate_mape(self, historical_data: List[float], predictions: List[float]) -> float:
        if not historical_data or not predictions:
            return 0.0
        avg_pred = sum(predictions) / len(predictions)
        avg_actual = sum(historical_data) / len(historical_data)
        if avg_actual == 0:
            return 0.0
        return abs((avg_pred - avg_actual) / avg_actual) * 100


class ExponentialSmoothingModel(ForecastModel):
    """指数平滑模型"""
    
    name = "exponential_smoothing"
    
    def __init__(self, alpha: float = 0.3, beta: float = 0.1):
        self.alpha = alpha
        self.beta = beta
        self.level = None
        self.trend = None
    
    def fit(self, historical_data: List[float]) -> None:
        if len(historical_data) < 2:
            self.level = historical_data[0] if historical_data else 0
            self.trend = 0
            return
        
        self.level = historical_data[0]
        self.trend = historical_data[1] - historical_data[0] if len(historical_data) > 1 else 0
        
        for i in range(1, len(historical_data)):
            prev_level = self.level
            self.level = self.alpha * historical_data[i] + (1 - self.alpha) * (self.level + self.trend)
            self.trend = self.beta * (self.level - prev_level) + (1 - self.beta) * self.trend
    
    def predict(self, horizon: int) -> Dict[str, Any]:
        if self.level is None:
            return {"predictions": [], "confidence_interval": None}
        
        predictions = []
        for h in range(1, horizon + 1):
            pred = self.level + h * self.trend
            predictions.append(round(max(0, pred), 2))
        
        residuals_std = 0.1 * self.level
        return {
            "predictions": predictions,
            "confidence_lower": [round(p - 1.96 * residuals_std, 2) for p in predictions],
            "confidence_upper": [round(p + 1.96 * residuals_std, 2) for p in predictions],
            "metrics": {}
        }


class TrendModel(ForecastModel):
    """线性趋势模型"""
    
    name = "linear_trend"
    
    def __init__(self):
        self.slope = 0
        self.intercept = 0
        self.last_value = 0
    
    def fit(self, historical_data: List[float]) -> None:
        self._historical_data = historical_data
        if len(historical_data) < 2:
            self.last_value = historical_data[0] if historical_data else 0
            return
        
        n = len(historical_data)
        x = list(range(n))
        y = historical_data
        
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        
        if denominator != 0:
            self.slope = numerator / denominator
            self.intercept = y_mean - self.slope * x_mean
        else:
            self.slope = 0
            self.intercept = y_mean
        
        self.last_value = y[-1]
    
    def predict(self, horizon: int) -> Dict[str, Any]:
        n = len(self._historical_data) if hasattr(self, '_historical_data') and self._historical_data else 0
        if n < 2:
            return {"predictions": [self.last_value] * horizon, "confidence_lower": [], "confidence_upper": [], "metrics": {}}
        
        predictions = []
        for h in range(horizon):
            pred = self.slope * (n + h) + self.intercept
            predictions.append(round(max(0, pred), 2))
        
        return {
            "predictions": predictions,
            "confidence_lower": [round(p * 0.9, 2) for p in predictions],
            "confidence_upper": [round(p * 1.1, 2) for p in predictions],
            "metrics": {"slope": round(self.slope, 4), "intercept": round(self.intercept, 4)}
        }


class EnsembleModel:
    """集成模型：组合多个预测器"""
    
    def __init__(self, models: List[ForecastModel] = None):
        self.models = models or [
            MovingAverageModel(window=4),
            ExponentialSmoothingModel(alpha=0.3, beta=0.1),
            TrendModel()
        ]
    
    def fit(self, historical_data: List[float]) -> None:
        for model in self.models:
            try:
                model.fit(historical_data)
            except Exception as e:
                logger.warning(f"模型 {model.name} 训练失败: {e}")
    
    def predict(self, horizon: int) -> Dict[str, Any]:
        all_predictions = []
        for model in self.models:
            try:
                result = model.predict(horizon)
                if result["predictions"]:
                    all_predictions.append(result["predictions"])
            except Exception as e:
                logger.warning(f"模型 {model.name} 预测失败: {e}")
        
        if not all_predictions:
            return {"predictions": [], "confidence_lower": [], "confidence_upper": [], "metrics": {}}
        
        ensemble_preds = []
        for h in range(horizon):
            values = [preds[h] for preds in all_predictions if h < len(preds)]
            if values:
                ensemble_preds.append(round(sum(values) / len(values), 2))
        
        stds = []
        for h in range(horizon):
            values = [preds[h] for preds in all_predictions if h < len(preds)]
            if len(values) > 1:
                mean = sum(values) / len(values)
                std = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
                stds.append(std)
            else:
                stds.append(ensemble_preds[h] * 0.1 if ensemble_preds[h] else 0)
        
        return {
            "predictions": ensemble_preds,
            "confidence_lower": [round(ensemble_preds[h] - 1.96 * stds[h], 2) for h in range(horizon)],
            "confidence_upper": [round(ensemble_preds[h] + 1.96 * stds[h], 2) for h in range(horizon)],
            "metrics": {"models_used": len(all_predictions), "method": "ensemble"}
        }


class ForecastEngine:
    """预测引擎：管理数据加载、模型训练和预测"""
    
    def __init__(self):
        self.model = EnsembleModel()
    
    def prepare_data(self, historical_data: List[Dict[str, Any]]) -> Dict[str, List[float]]:
        """按产品分组数据"""
        by_product = {}
        for record in historical_data:
            pid = record['product_id']
            demand = record['demand']
            by_product.setdefault(pid, []).append(demand)
        return by_product
    
    def forecast(self, historical_data: List[Dict[str, Any]], 
                horizon: int = 12) -> Dict[str, Dict[str, Any]]:
        """
        执行预测
        
        Returns:
        {
            "product_id": {
                "predictions": [...],
                "confidence_lower": [...],
                "confidence_upper": [...],
                "metrics": {...}
            }
        }
        """
        by_product = self.prepare_data(historical_data)
        results = {}
        
        for product_id, demands in by_product.items():
            try:
                self.model.fit(demands)
                result = self.model.predict(horizon)
                results[product_id] = result
                logger.info(f"产品 {product_id} 预测完成: {horizon} 期")
            except Exception as e:
                logger.error(f"产品 {product_id} 预测失败: {e}")
                results[product_id] = {
                    "predictions": [],
                    "confidence_lower": [],
                    "confidence_upper": [],
                    "metrics": {"error": str(e)}
                }
        
        return results
