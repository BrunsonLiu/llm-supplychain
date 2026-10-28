import os
import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    """SQLite数据库管理类"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "supply_chain.db")
        
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
        logger.info(f"数据库初始化: {db_path}")
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接上下文管理器"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        """初始化数据库表"""
        with self.get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT UNIQUE NOT NULL,
                    product_name TEXT,
                    category TEXT,
                    unit_cost REAL DEFAULT 0.0,
                    lead_time INTEGER DEFAULT 7,
                    service_level REAL DEFAULT 0.95,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS demand_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    date DATE NOT NULL,
                    demand REAL NOT NULL,
                    price REAL,
                    promotion INTEGER DEFAULT 0,
                    is_holiday INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(product_id, date),
                    FOREIGN KEY (product_id) REFERENCES products(product_id)
                );
                
                CREATE TABLE IF NOT EXISTS forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    forecast_date DATE NOT NULL,
                    predicted_demand REAL NOT NULL,
                    model_name TEXT DEFAULT 'baseline',
                    confidence_lower REAL,
                    confidence_upper REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products(product_id)
                );
                
                CREATE TABLE IF NOT EXISTS inventory_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL,
                    order_date DATE NOT NULL,
                    order_quantity REAL NOT NULL,
                    safety_stock REAL,
                    target_stock REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products(product_id)
                );
                
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_type TEXT NOT NULL,
                    report_content TEXT,
                    summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_demand_product ON demand_data(product_id);
                CREATE INDEX IF NOT EXISTS idx_demand_date ON demand_data(date);
                CREATE INDEX IF NOT EXISTS idx_forecast_product ON forecasts(product_id);
            """)
    
    def insert_product(self, product_id: str, product_name: str = None, 
                      category: str = None, unit_cost: float = 0.0,
                      lead_time: int = 7, service_level: float = 0.95):
        """插入产品信息"""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO products 
                (product_id, product_name, category, unit_cost, lead_time, service_level)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (product_id, product_name, category, unit_cost, lead_time, service_level))
    
    def insert_demand_data(self, product_id: str, date: str, demand: float,
                          price: float = None, promotion: int = 0, is_holiday: int = 0):
        """插入需求数据"""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO demand_data 
                (product_id, date, demand, price, promotion, is_holiday)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (product_id, date, demand, price, promotion, is_holiday))
    
    def get_demand_data(self, product_id: str = None, 
                       start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
        """获取需求数据"""
        with self.get_connection() as conn:
            query = "SELECT * FROM demand_data WHERE 1=1"
            params = []
            
            if product_id:
                query += " AND product_id = ?"
                params.append(product_id)
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += " ORDER BY date"
            
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    def get_products(self) -> List[Dict[str, Any]]:
        """获取所有产品"""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM products ORDER BY product_id").fetchall()
            return [dict(row) for row in rows]
    
    def save_forecast(self, product_id: str, forecast_date: str, 
                     predicted_demand: float, model_name: str = 'baseline',
                     confidence_lower: float = None, confidence_upper: float = None):
        """保存预测结果（同产品/日期/模型重复写入时覆盖，保证重跑幂等）"""
        with self.get_connection() as conn:
            conn.execute(
                "DELETE FROM forecasts WHERE product_id = ? AND forecast_date = ? AND model_name = ?",
                (product_id, forecast_date, model_name),
            )
            conn.execute("""
                INSERT INTO forecasts 
                (product_id, forecast_date, predicted_demand, model_name, confidence_lower, confidence_upper)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (product_id, forecast_date, predicted_demand, model_name, confidence_lower, confidence_upper))
    
    def get_forecasts(self, product_id: str = None, model_name: str = None) -> List[Dict[str, Any]]:
        """获取预测结果"""
        with self.get_connection() as conn:
            query = "SELECT * FROM forecasts WHERE 1=1"
            params = []
            
            if product_id:
                query += " AND product_id = ?"
                params.append(product_id)
            if model_name:
                query += " AND model_name = ?"
                params.append(model_name)
            
            query += " ORDER BY forecast_date"
            
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    def save_order(self, product_id: str, order_date: str, order_quantity: float,
                  safety_stock: float = None, target_stock: float = None):
        """保存订单建议（同产品/日期重复写入时覆盖，保证重跑幂等）"""
        with self.get_connection() as conn:
            conn.execute(
                "DELETE FROM inventory_orders WHERE product_id = ? AND order_date = ?",
                (product_id, order_date),
            )
            conn.execute("""
                INSERT INTO inventory_orders 
                (product_id, order_date, order_quantity, safety_stock, target_stock)
                VALUES (?, ?, ?, ?, ?)
            """, (product_id, order_date, order_quantity, safety_stock, target_stock))
    
    def get_product_config(self, product_id: str) -> Optional[Dict[str, Any]]:
        """获取产品配置"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM products WHERE product_id = ?", 
                (product_id,)
            ).fetchone()
            return dict(row) if row else None
    
    def clear_data(self):
        """清空需求/预测/订单/报告数据"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM demand_data")
            conn.execute("DELETE FROM forecasts")
            conn.execute("DELETE FROM inventory_orders")
            conn.execute("DELETE FROM reports")

    def clear_products(self):
        """清空产品主数据（生成新数据集时使用）"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM products")
    
    def get_data_stats(self) -> Dict[str, Any]:
        """获取数据统计信息"""
        with self.get_connection() as conn:
            return {
                "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                "demand_records": conn.execute("SELECT COUNT(*) FROM demand_data").fetchone()[0],
                "forecasts": conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0],
                "orders": conn.execute("SELECT COUNT(*) FROM inventory_orders").fetchone()[0],
            }
