# -*- coding: utf-8 -*-
"""
供应链智能体测试：Agent 路由、工具链路、RAG 问答

运行：PYTHONPATH=src;. python tests/test_supply.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply import SupplyChainAgent, Database, ForecastEngine
from supply.tools import ForecastTool, InventoryTool


def test_agent_routing():
    """路由：问句走 RAG，指令走数值工具"""
    agent = SupplyChainAgent()
    cases = {
        "生成数据": "data",
        "预测周期=4": "forecast",
        "库存周期=4": "inventory",
        "报告": "report",
        "什么是安全库存？": "rag",
    }
    for prompt, expected in cases.items():
        tool = agent._route(prompt)
        assert tool is not None and tool.name == expected, f"{prompt} 路由错误: {tool}"
    print("[OK] 路由分发正确")


def test_pipeline():
    """完整链路：数据 -> 预测 -> 库存 -> 报告"""
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(db_path=str(Path(tmp) / "test.db"))
        agent = SupplyChainAgent(db=db, enable_rag=False)
        results = agent.run("生成数据; 预测周期=6; 库存周期=6; 报告")

        statuses = [r[1].get("status") for r in results]
        assert all(s == "success" for s in statuses), f"存在失败步骤: {statuses}"

        forecast = results[1][1]["forecast"]
        assert forecast, "预测结果为空"
        for pid, data in forecast.items():
            assert len(data["predictions"]) == 6, f"{pid} 预测期数不对"

        orders = results[2][1]["orders"]
        assert orders, "订单建议为空"
        print("[OK] 数据->预测->库存->报告 全链路成功")


def test_forecast_engine():
    """预测引擎：集成模型对平稳序列的预测应接近均值"""
    engine = ForecastEngine()
    data = [{"product_id": "X", "demand": 10.0 + (i % 3) * 0.1} for i in range(20)]
    result = engine.forecast(data, horizon=3)
    preds = result["X"]["predictions"]
    assert len(preds) == 3
    assert all(8 < p < 12 for p in preds), f"预测值偏离合理区间: {preds}"
    print("[OK] 预测引擎数值合理")


def test_rag_tool():
    """RAG 工具：能检索到知识库内容"""
    agent = SupplyChainAgent()
    result = agent.tools["rag"].run("什么是安全库存？")
    assert result["status"] == "success"
    assert result["answer"], "RAG 回答为空"
    print("[OK] RAG 检索问答可用")


def main():
    print("=" * 50)
    print("供应链智能体测试")
    print("=" * 50)
    tests = [test_agent_routing, test_pipeline, test_forecast_engine, test_rag_tool]
    for t in tests:
        t()
    print("=" * 50)
    print("全部测试通过")
    print("=" * 50)


if __name__ == "__main__":
    main()
