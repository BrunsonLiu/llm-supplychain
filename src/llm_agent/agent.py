from typing import Any, List, Tuple, Dict

from .tools import Tool
from ..store import DataStore


class Agent:
    def __init__(self, name: str = "LLM-Agent"):
        self.name = name
        self.tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def run(self, prompt: str, steps: int = 3) -> List[Tuple[str, Any]]:
        # Very small planner: split on semicolons and run sequentially
        tasks = [t.strip() for t in prompt.split(";") if t.strip()]
        results: List[Tuple[str, Any]] = []
        for task in tasks[:steps]:
            handled = False
            for tool in self.tools.values():
                if tool.can_handle(task):
                    results.append((task, tool.run(task)))
                    handled = True
                    break
            if not handled:
                results.append((task, None))
        return results
