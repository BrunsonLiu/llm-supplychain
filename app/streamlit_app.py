# -*- coding: utf-8 -*-
"""Streamlit demo for the function-calling supply-chain agent.

Run:
  streamlit run app/streamlit_app.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st

from supply import Database, FunctionCallingAgent

EXAMPLES = [
    "查看数据统计",
    "生成 8 周、3 个产品的数据，再预测未来 6 周",
    "根据预测给出 6 周补货计划",
    "生成一份决策报告",
    "什么是安全库存？",
    "删除数据库",
]

STATUS_STYLE = {
    "success": ("✅", "成功"),
    "blocked": ("⛔", "已拦截"),
    "error": ("⚠️", "失败"),
    "no_match": ("❔", "未匹配"),
}


def build_llm():
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    try:
        from rag import OpenAILLM

        return OpenAILLM(
            api_key=api_key,
            base_url=os.environ.get("OPENAI_BASE_URL"),
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        )
    except Exception as exc:  # noqa: BLE001 - surface config errors in the UI
        st.sidebar.warning(f"LLM 初始化失败，已回退规则规划器：{exc}")
        return None


@st.cache_resource(show_spinner=False)
def get_agent(use_llm: bool, allow_writes: bool, max_steps: int) -> FunctionCallingAgent:
    return FunctionCallingAgent(
        llm=build_llm() if use_llm else None,
        allow_writes=allow_writes,
        max_steps=max_steps,
    )


@st.cache_resource(show_spinner=False)
def get_stats() -> dict:
    return Database().get_data_stats()


def trace_rows(trace):
    return [
        {
            "step": item["step"],
            "tool": item["name"],
            "arguments": json.dumps(item["arguments"], ensure_ascii=False),
            "status": item["status"],
        }
        for item in trace
    ]


def citation_rows(citations):
    return [
        {
            "#": item["id"],
            "source": item["source"],
            "title": item["title"],
            "score": round(item["score"], 3),
            "snippet": item["snippet"].replace("\n", " ")[:160],
        }
        for item in citations
    ]


def render_result(result):
    icon, label = STATUS_STYLE.get(result["status"], ("•", result["status"]))
    cols = st.columns(3)
    cols[0].metric("状态", f"{icon} {label}")
    cols[1].metric("规划器", result["planner"])
    cols[2].metric("步数 / 引用", f"{result['steps']} / {len(result['citations'])}")

    answer = result["answer"]
    if result["blocked"]:
        st.warning("护栏拦截：" + "；".join(result["blocked"]))
        # agent 会把拦截原因追加进回答，界面上已单独提示，这里去掉重复行
        answer = "\n".join(
            line for line in answer.splitlines() if not line.startswith("护栏拦截：")
        ).strip()

    if not answer and result["blocked"]:
        answer = "该请求已被护栏拒绝，未执行任何工具。"
    st.markdown(answer or "（无回答）")

    if result["tool_calls"]:
        st.markdown("**工具轨迹**")
        st.dataframe(trace_rows(result["tool_calls"]), width="stretch", hide_index=True)

    if result["citations"]:
        st.markdown("**引用来源**")
        st.dataframe(citation_rows(result["citations"]), width="stretch", hide_index=True)


st.set_page_config(
    page_title="供应链智能体",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.header("运行设置")
    has_key = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    )
    st.caption(
        "已检测到 LLM 配置，将由模型原生选择工具。"
        if has_key
        else "未配置 API Key：使用确定性规则规划器（离线可复现）。"
    )
    allow_writes = st.toggle("允许写操作", value=True)
    st.caption("关闭后 generate / forecast / inventory 会被护栏拦截，只留只读工具。")
    max_steps = st.slider("最大步数", 1, 12, 8)

    st.divider()
    stats = get_stats()
    st.markdown("**数据库概况**")
    st.write(
        f"产品 {stats['products']} · 需求 {stats['demand_records']} · "
        f"预测 {stats['forecasts']} · 订单 {stats['orders']}"
    )

    st.divider()
    if st.button("清空对话", use_container_width=True):
        st.session_state.history = []
        st.rerun()

    st.caption("写操作会持久化到 data/supply_chain.db。")

st.title("📦 供应链智能体")
st.caption("Function Calling + 护栏 + 引用 · 需求预测 / 补货 / 知识问答")

with st.expander("可用工具与示例指令", expanded=not st.session_state.history):
    st.markdown(
        "`get_data_stats` · `generate_data` · `forecast_demand` · "
        "`plan_inventory` · `build_report` · `search_knowledge`"
    )
    st.code("\n".join(EXAMPLES), language="text")

for prompt, result in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        render_result(result)

prompt = st.chat_input("例如：生成 8 周、3 个产品的数据，再预测未来 6 周")
if prompt:
    agent = get_agent(bool(has_key), allow_writes, max_steps)
    with st.spinner("Agent 正在调用工具..."):
        result = agent.run(prompt)
    st.session_state.history.append((prompt, result))
    get_stats.clear()
    st.rerun()
