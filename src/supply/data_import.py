import os
import csv
import json
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from .database import Database

logger = logging.getLogger(__name__)


class DataImporter:
    """数据导入工具类，支持CSV导入和真实数据生成"""
    
    def __init__(self, db: Database = None):
        self.db = db or Database()
    
    def import_csv(self, csv_path: str, product_column: str = 'product_id',
                  date_column: str = 'date', demand_column: str = 'demand',
                  batch_size: int = 1000) -> int:
        """
        从CSV文件导入需求数据
        
        支持的CSV格式：
        - product_id: 产品ID
        - date: 日期 (YYYY-MM-DD)
        - demand: 需求量
        - price: 价格 (可选)
        - promotion: 是否促销 (0/1, 可选)
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV文件不存在: {csv_path}")
        
        count = 0
        products = set()
        
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            batch = []
            
            for row in reader:
                try:
                    product_id = row[product_column].strip()
                    date = row[date_column].strip()
                    demand = float(row[demand_column])
                    price = float(row.get('price', 0)) if 'price' in row else None
                    promotion = int(row.get('promotion', 0))
                    is_holiday = int(row.get('is_holiday', 0))
                    
                    products.add(product_id)
                    batch.append({
                        'product_id': product_id,
                        'date': date,
                        'demand': demand,
                        'price': price,
                        'promotion': promotion,
                        'is_holiday': is_holiday
                    })
                    
                    if len(batch) >= batch_size:
                        self._insert_batch(batch)
                        count += len(batch)
                        batch = []
                        
                except Exception as e:
                    logger.warning(f"跳过无效行: {e}")
                    continue
            
            if batch:
                self._insert_batch(batch)
                count += len(batch)
        
        for product_id in products:
            self.db.insert_product(product_id, product_name=f"产品{product_id}")
        
        logger.info(f"成功导入 {count} 条数据，{len(products)} 个产品")
        return count
    
    def _insert_batch(self, batch: List[Dict]):
        """批量插入数据"""
        for item in batch:
            self.db.insert_demand_data(**item)
    
    def import_from_json(self, json_path: str) -> int:
        """从JSON文件导入数据"""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        count = 0
        for record in data:
            try:
                self.db.insert_demand_data(
                    product_id=record['product_id'],
                    date=record['date'],
                    demand=record['demand'],
                    price=record.get('price'),
                    promotion=record.get('promotion', 0),
                    is_holiday=record.get('is_holiday', 0)
                )
                count += 1
            except Exception as e:
                logger.warning(f"跳过无效记录: {e}")
        
        logger.info(f"从JSON导入 {count} 条数据")
        return count
    
    def generate_realistic_data(self, products: List[Dict] = None, 
                               weeks: int = 104, start_date: str = None) -> int:
        """
        生成更真实的模拟数据，包含：
        - 季节性波动
        - 随机噪声
        - 趋势变化
        - 促销效应
        - 节假日效应
        """
        if products is None:
            products = [
                {'product_id': 'A', 'base_demand': 20, 'volatility': 0.15, 'seasonal_strength': 0.3},
                {'product_id': 'B', 'base_demand': 35, 'volatility': 0.20, 'seasonal_strength': 0.4},
                {'product_id': 'C', 'base_demand': 25, 'volatility': 0.18, 'seasonal_strength': 0.25},
                {'product_id': 'D', 'base_demand': 50, 'volatility': 0.25, 'seasonal_strength': 0.5},
                {'product_id': 'E', 'base_demand': 15, 'volatility': 0.12, 'seasonal_strength': 0.2},
            ]
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(weeks=weeks)).strftime('%Y-%m-%d')
        
        start = datetime.strptime(start_date, '%Y-%m-%d')
        count = 0
        
        for product in products:
            product_id = product['product_id']
            base = product['base_demand']
            vol = product['volatility']
            seasonal_str = product['seasonal_strength']
            
            self.db.insert_product(
                product_id=product_id,
                product_name=f"产品{product_id}",
                category='标准产品',
                unit_cost=random.uniform(5, 50),
                lead_time=random.randint(3, 14),
                service_level=random.uniform(0.90, 0.98)
            )
            
            for week in range(weeks):
                date = start + timedelta(weeks=week)
                week_of_year = date.isocalendar()[1]
                
                seasonal = seasonal_str * base * (
                    0.3 * (1 - abs(week_of_year - 26) / 26) +
                    0.2 * (1 if week_of_year in [12, 13, 24, 25, 50, 51] else 0)
                )
                
                trend = 0.001 * week * base
                
                noise = random.gauss(0, vol * base)
                
                promotion = 1 if random.random() < 0.15 else 0
                promo_effect = 0.2 * base if promotion else 0
                
                holiday = 1 if week_of_year in [1, 2, 12, 24, 50] else 0
                holiday_effect = 0.15 * base if holiday else 0
                
                demand = base + seasonal + trend + noise + promo_effect + holiday_effect
                demand = max(0, demand)
                
                price = random.uniform(10, 100)
                
                self.db.insert_demand_data(
                    product_id=product_id,
                    date=date.strftime('%Y-%m-%d'),
                    demand=round(demand, 2),
                    price=round(price, 2),
                    promotion=promotion,
                    is_holiday=holiday
                )
                count += 1
        
        logger.info(f"生成 {count} 条模拟数据，{len(products)} 个产品")
        return count
    
    def export_to_csv(self, output_path: str, product_id: str = None) -> int:
        """导出数据到CSV"""
        data = self.db.get_demand_data(product_id=product_id)
        
        if not data:
            logger.warning("没有数据可导出")
            return 0
        
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'product_id', 'date', 'demand', 'price', 'promotion', 'is_holiday'
            ])
            writer.writeheader()
            writer.writerows(data)
        
        logger.info(f"导出 {len(data)} 条数据到 {output_path}")
        return len(data)
