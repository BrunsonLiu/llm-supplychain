"""
OpenAI 兼容 LLM 实现

支持 OpenAI 官方 API 及任何 OpenAI 兼容端点（DeepSeek、Moonshot、vLLM、Ollama 等）：
- DeepSeek:   base_url="https://api.deepseek.com",  model="deepseek-chat"
- Moonshot:   base_url="https://api.moonshot.cn/v1", model="moonshot-v1-8k"
api_key / base_url 均支持从环境变量回退读取。
"""
import os
from typing import List, Dict, Any, Optional
from .base import BaseLLM, LLMResponse


class OpenAILLM(BaseLLM):
    """OpenAI 兼容 LLM 实现"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        **kwargs
    ):
        try:
            import openai
            self.openai = openai
        except ImportError:
            raise ImportError("Please install openai: pip install openai")
        
        # 环境变量回退：未显式传入时读取标准变量，便于接入 DeepSeek 等兼容服务
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.model = model
        
        # 创建客户端（OpenAI 兼容端点均可）
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, **kwargs)
    
    def generate(
        self, 
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """生成文本"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        return response.choices[0].message.content
    
    def generate_with_response(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """生成文本并返回完整响应"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        usage = {}
        if response.usage:
            usage = {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            }
        
        return LLMResponse(
            content=response.choices[0].message.content,
            usage=usage,
            metadata={'model': response.model}
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """聊天接口"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        return response.choices[0].message.content


class MockLLM(BaseLLM):
    """模拟LLM，用于测试"""
    
    def __init__(self, response_template: str = "这是对'{prompt}'的回答。"):
        self.response_template = response_template
    
    def generate(
        self, 
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """生成模拟响应"""
        return self.response_template.format(prompt=prompt[:50])
    
    def generate_with_response(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """生成模拟响应"""
        content = self.generate(prompt, temperature, max_tokens, **kwargs)
        return LLMResponse(
            content=content,
            usage={'prompt_tokens': len(prompt), 'completion_tokens': len(content), 'total_tokens': len(prompt) + len(content)}
        )
