# -*- coding: utf-8 -*-
"""Streamlit UI smoke tests using AppTest (no browser required).

Run: PYTHONPATH=src;. python tests/test_ui_smoke.py
Requires the optional UI extra: pip install "streamlit>=1.49"
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

APP = ROOT / "app" / "streamlit_app.py"


def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_app_renders_controls():
    at = _app()
    assert at.title[0].value == "📦 供应链智能体"
    assert len(at.chat_input) == 1
    assert len(at.toggle) == 1
    assert at.toggle[0].label == "允许写操作"
    assert len(at.slider) == 1
    print("[OK] 页面渲染：标题、聊天输入、写操作开关、步数滑块")


def test_knowledge_answer_renders_citations():
    at = _app()
    at.chat_input[0].set_value("什么是安全库存？").run()
    assert not at.exception, [e.value for e in at.exception]
    metrics = {item.label: item.value for item in at.metric}
    assert metrics["规划器"] == "rules"
    assert "3" in metrics["步数 / 引用"]
    text = "\n".join(item.value for item in at.markdown)
    assert "参考来源" in text, text[:400]
    assert len(at.dataframe) >= 2, "工具轨迹与引用表应各有一个 dataframe"
    print("[OK] 知识问答渲染引用与工具轨迹")


def test_read_only_mode_blocks_writes():
    at = _app()
    at.toggle[0].set_value(False).run()
    assert not at.exception, [e.value for e in at.exception]
    at.chat_input[0].set_value("生成 8 周、3 个产品的数据").run()
    assert not at.exception, [e.value for e in at.exception]
    warnings = [item.value for item in at.warning]
    assert any("护栏拦截" in text for text in warnings), warnings
    metrics = {item.label: item.value for item in at.metric}
    assert "已拦截" in metrics["状态"], metrics
    print("[OK] 只读模式拦截写操作并提示原因")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print("[SKIP] 未安装 streamlit（pip install \"streamlit>=1.49\"）")
        return
    print("=" * 56)
    print("Streamlit UI smoke tests")
    print("=" * 56)
    for test in (
        test_app_renders_controls,
        test_knowledge_answer_renders_citations,
        test_read_only_mode_blocks_writes,
    ):
        test()
    print("=" * 56)
    print("All UI smoke tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
