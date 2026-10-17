# -*- coding: utf-8 -*-
"""
供应链智能体 API（FastAPI 统一入口）

合并自两个源项目的 API：
- 原 LLMandagentt/app/main.py：/run 决策流程、/data 数据操作
- 原 RAG项目/src/api/server.py 的定位由 /ask 知识问答端点承接

运行：
  PYTHONPATH=src;. uvicorn app.main:app --reload --port 8000
文档：http://localhost:8000/docs
"""
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Literal, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from supply import SupplyChainAgent, Database, I18n
from rag import OpenAILLM

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_ = I18n.t

app = FastAPI(
    title=_("api_title"),
    description=_("api_desc"),
    version="3.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局单例 Agent（工具无状态、Database 按需连接）
_agent: Optional[SupplyChainAgent] = None


def get_agent() -> SupplyChainAgent:
    global _agent
    if _agent is None:
        _agent = SupplyChainAgent()
    return _agent


def build_llm():
    """配置了 API Key 才启用真实 LLM"""
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAILLM(api_key=api_key,
                         base_url=os.environ.get("OPENAI_BASE_URL"),
                         model=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    except Exception as e:
        logger.warning(f"LLM 初始化失败，使用 Mock: {e}")
        return None


class RunRequest(BaseModel):
    horizon: int = Field(default=12, ge=1, le=52)
    generate_data: bool = True
    use_llm: bool = True
    lang: Literal["zh", "en"] = "zh"


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    lang: Literal["zh", "en"] = "zh"


@app.get("/")
def read_root():
    return {"msg": _("api_running"), "version": "3.0.0", "docs": "/docs"}


@app.post("/run")
def run_pipeline(req: RunRequest):
    """一键决策流程：数据 -> 预测 -> 库存 -> 报告 -> (可选) LLM 摘要"""
    try:
        agent = get_agent()
        llm = build_llm() if req.use_llm else None
        prompt = f"{_('data_generate') if req.generate_data else ''}; 预测周期={req.horizon}; 库存周期={req.horizon}; 报告"
        report = agent.decision_report(horizon=req.horizon, llm=llm)
        return {"status": "success", "lang": req.lang, **report}
    except Exception as e:
        logger.error(f"API执行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ask")
def ask_knowledge(req: AskRequest):
    """RAG 知识库问答"""
    try:
        agent = get_agent()
        rag_tool = agent.tools.get("rag")
        if rag_tool is None:
            raise HTTPException(status_code=400, detail="RAG 工具未启用")
        result = rag_tool.run(req.question, top_k=req.top_k)
        return {"status": "success", "question": result["question"],
                "answer": result["answer"], "sources": result["sources"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"知识问答失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/data")
def data_operations(action: Literal["generate", "import", "stats"],
                    weeks: int = 104, csv_path: Optional[str] = None):
    """数据操作：生成模拟数据 / 导入CSV / 统计"""
    try:
        db = Database()
        agent = get_agent()
        if action == "generate":
            result = agent.tools["data"].run(f"生成数据 周期={weeks}")
        elif action == "import":
            if not csv_path:
                raise HTTPException(status_code=400, detail="请提供 csv_path")
            result = agent.tools["data"].run(f"导入数据 路径={csv_path}")
        else:
            result = {"status": "success", "stats": db.get_data_stats()}
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"数据操作失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health_check():
    try:
        db = Database()
        return {"status": "healthy", "stats": db.get_data_stats()}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
