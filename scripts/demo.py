# -*- coding: utf-8 -*-
"""
一键演示：供应链智能体完整流程

演示内容：
  1. 生成模拟需求数据（含季节性/趋势/促销/节假日）
  2. 需求预测（移动平均 + 指数平滑 + 线性趋势集成）
  3. 库存优化（安全库存 + EOQ + 目标库存补货）
  4. 生成决策报告
  5. RAG 知识库问答（默认 Mock 组件，无需 API Key）
  6. 如配置 OPENAI_API_KEY（或兼容端点），追加 LLM 决策摘要

运行：
  PYTHONPATH=src;. python scripts/demo.py        # Windows
  PYTHONPATH=src:. python scripts/demo.py        # Linux/macOS
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply import SupplyChainAgent, I18n
from rag import OpenAILLM, OpenAIEmbeddings

_ = I18n.t


def build_llm():
    """配置了 API Key 才启用真实 LLM，否则返回 None（走 Mock）"""
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY"):
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL")
        return OpenAILLM(api_key=api_key, base_url=base_url,
                         model=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    return None


def main():
    print("=" * 62)
    print(_("demo_title"))
    print("=" * 62)

    llm = build_llm()
    embeddings = None
    if os.environ.get("OPENAI_API_KEY"):
        try:
            embeddings = OpenAIEmbeddings()
        except Exception:
            embeddings = None

    agent = SupplyChainAgent(enable_rag=True, llm=llm, embeddings=embeddings)

    # 步骤 1-4：数据 -> 预测 -> 库存 -> 报告
    print("\n" + _("step_data"))
    print(_("step_forecast", 12))
    print(_("step_inventory", 12))
    print(_("step_report"))
    report = agent.decision_report(horizon=12, llm=llm)

    print("\n--- 预测结果（前 3 个产品）---")
    for pid, data in list(report["forecast"].items())[:3]:
        preds = data["predictions"]
        print(f"  {pid}: 首期={preds[0]}, 期末={preds[-1]}")

    print("\n--- 库存建议（产品 A 前 3 期）---")
    for order in report["orders"].get("A", [])[:3]:
        print(f"  第{order['period']}期: 订货量={order['order_quantity']}, "
              f"安全库存={order['safety_stock']}, EOQ={order['eoq']}")

    print("\n--- 决策报告（前 300 字）---")
    print(report["report"][:300])

    # 步骤 5：RAG 知识问答
    print("\n" + "=" * 62)
    print("RAG 知识库问答演示")
    print("=" * 62)
    for q in ["什么是安全库存？", "如何计算经济订货批量？", "什么是牛鞭效应？"]:
        print(f"\n问：{q}")
        result = agent.tools["rag"].run(q)
        print(f"答：{result['answer'][:150]}")

    # 步骤 6：LLM 摘要（可选）
    if llm is not None:
        print("\n" + _("step_summary"))
        print(report.get("llm_summary", "")[:300])
    else:
        print("\n[提示] 未配置 OPENAI_API_KEY，跳过 LLM 摘要；"
              "RAG 问答使用 Mock 组件（演示检索流程）。")

    print("\n" + _("step_stats"), report["stats"])
    print("\n" + _("demo_complete"))


if __name__ == "__main__":
    main()
