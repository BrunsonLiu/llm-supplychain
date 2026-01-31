from typing import Any


class Tool:
    name: str

    def can_handle(self, prompt: str) -> bool:
        # Base tool handles all prompts by default; override in subclasses
        return True

    def run(self, prompt: str) -> Any:
        raise NotImplementedError


class EchoTool(Tool):
    name = "echo"

    def can_handle(self, prompt: str) -> bool:
        return True

    def run(self, prompt: str) -> str:
        # Simple echo of the input prompt
        return prompt
