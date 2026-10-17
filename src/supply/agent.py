"""
供应链智能体统一入口

定位说明（诚实版）：
    本 Agent 是"规则路由的工具编排器"——按关键词把指令分发给对应工具
    （数据/预测/库存/报告/RAG检索），工具结果汇总后返回。
    它**不是** LLM 自主规划型 Agent（没有 ReAct/Function-Calling 循环）。
    如需升级，把 _route 换成 LLM function calling 即可，工具层无需改动。

典型用法：
    agent = SupplyChainAgent()
    agent.run("生成数据; 预测周期=12; 库存周期=12; 报告")
    agent.run("什么是安全库存？")        # 走 RAG 知识库
"""
from typing import Any, List, Tuple, Dict, Optional

from .tools import Tool, DataTool, ForecastTool, InventoryTool, ReportTool
from .rag_tool import RAGTool
from .database import Database
from .i18n import I18n

_ = I18n.t


class SupplyChainAgent:
    """供应链智能体：工具注册 + 规则路由 + 结果汇总"""

    def __init__(
        self,
        db: Database = None,
        documents_dir: str = None,
        enable_rag: bool = True,
        llm=None,
        embeddings=None,
    ):
        self.db = db or Database()
        self.tools: Dict[str, Tool] = {}

        # 注册 RAG 知识检索工具（来自原 RAG项目）——置于最前，
        # 保证问句（如"什么是安全库存"）优先走知识库，不被"库存"等关键词截走
        if enable_rag:
            self.register_tool(
                RAGTool(documents_dir=documents_dir, embeddings=embeddings, llm=llm)
            )

        # 注册供应链数值工具（来自原 LLMandagentt）
        self.register_tool(DataTool(self.db))
        self.register_tool(ForecastTool(self.db))
        self.register_tool(InventoryTool(self.db))
        self.register_tool(ReportTool(self.db))

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def _route(self, task: str) -> Optional[Tool]:
        """规则路由：返回第一个能处理该任务的工具（按注册顺序）"""
        for tool in self.tools.values():
            if tool.can_handle(task):
                return tool
        return None

    def run(self, prompt: str, max_steps: int = 6) -> List[Tuple[str, Any]]:
        """执行指令串：按分号切分，逐条路由到工具"""
        tasks = [t.strip() for t in prompt.split(";") if t.strip()]
        results: List[Tuple[str, Any]] = []
        for task in tasks[:max_steps]:
            tool = self._route(task)
            if tool is None:
                results.append((task, {"status": "error", "message": "没有工具能处理该指令"}))
            else:
                results.append((task, tool.run(task)))
        return results

    def ask(self, question: str, k: int = 3) -> str:
        """知识库问答便捷方法"""
        rag_tool = self.tools.get("rag")
        if rag_tool is None:
            return "RAG 工具未启用"
        return rag_tool.chain.run(question, k=k)["answer"]

    def decision_report(self, horizon: int = 12, llm=None) -> Dict[str, Any]:
        """一键决策报告：数据 -> 预测 -> 库存 -> 报告 -> (可选) LLM 摘要"""
        pipeline = self.run(f"生成数据; 预测周期={horizon}; 库存周期={horizon}; 报告")
        summary = {
            "forecast": pipeline[1][1].get("forecast", {}),
            "orders": pipeline[2][1].get("orders", {}),
            "report": pipeline[3][1].get("report", ""),
            "stats": self.db.get_data_stats(),
        }
        if llm is not None:
            summary["llm_summary"] = self._summarize(summary, llm)
        return summary

    @staticmethod
    def _summarize(context: Dict[str, Any], llm) -> str:
        """用 LLM 生成决策摘要（llm 需提供 generate(prompt) 接口）"""
        forecast_lines = []
        for pid, data in list(context.get("forecast", {}).items())[:5]:
            preds = data.get("predictions", [])
            if preds:
                forecast_lines.append(f"- {pid}: 首期={preds[0]:.1f}, 期末={preds[-1]:.1f}")
        prompt = _("llm_user_prompt",
                   "\n".join(forecast_lines) or "无预测数据",
                   "（见订单明细）",
                   context.get("report", "")[:500])
        try:
            return llm.generate(prompt)
        except Exception as e:
            return f"LLM 摘要生成失败: {e}"
