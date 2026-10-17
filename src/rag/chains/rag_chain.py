"""
RAG链 - 核心RAG流程实现
"""
from typing import List, Dict, Any, Optional
from ..retrievers.base import BaseRetriever
from ..llms.base import BaseLLM
from .. import Document
from ..utils import get_logger, PerformanceLogger, CacheManager, generate_cache_key
from ..utils import (
    ChainError,
    RetrievalError,
    LLMError,
    retry_with_state,
)

logger = get_logger(__name__)


class RAGChain:
    """RAG链 - 将检索和生成结合起来"""
    
    DEFAULT_TEMPLATE = """基于以下上下文信息回答问题。如果上下文信息不足以回答问题，请说明无法回答。

上下文信息：
{context}

问题：{question}

请基于以上上下文回答问题："""

    def __init__(
        self,
        retriever: BaseRetriever,
        llm: BaseLLM,
        prompt_template: str = None,
        return_source_documents: bool = False,
        enable_cache: bool = True,
        cache_ttl: int = 3600
    ):
        self.retriever = retriever
        self.llm = llm
        self.prompt_template = prompt_template or self.DEFAULT_TEMPLATE
        self.return_source_documents = return_source_documents
        self.enable_cache = enable_cache
        self.cache = CacheManager(enable_memory_cache=enable_cache, default_ttl=cache_ttl) if enable_cache else None
        logger.info(f"RAGChain 初始化, prompt_template: {self.prompt_template[:50]}...")
    
    def _format_documents(self, documents: List[Document]) -> str:
        """将文档格式化为上下文字符串"""
        contexts = []
        for i, doc in enumerate(documents, 1):
            context = f"[文档 {i}]\n{doc.page_content}"
            contexts.append(context)
        return "\n\n".join(contexts)
    
    def _build_prompt(self, question: str, documents: List[Document]) -> str:
        """构建提示词"""
        context = self._format_documents(documents)
        return self.prompt_template.format(
            context=context,
            question=question
        )
    
    def run(self, question: str, k: int = 4) -> Dict[str, Any]:
        """运行RAG流程"""
        with PerformanceLogger(logger, f"RAGChain.run: {question[:30]}"):
            # 检查缓存
            if self.enable_cache:
                cache_key = generate_cache_key("rag_chain", question=question, k=k)
                cached_result = self.cache.get(cache_key)
                if cached_result is not None:
                    logger.info(f"缓存命中，直接返回结果")
                    return cached_result
            
            try:
                # 1. 检索相关文档
                logger.info(f"开始检索相关文档, k={k}")
                retrieved_docs = self.retriever.retrieve(question, k=k)
                logger.info(f"检索到 {len(retrieved_docs)} 个文档")
                
                if not retrieved_docs:
                    logger.warning("未检索到相关文档")
                    result = {
                        'question': question,
                        'answer': "抱歉，未找到相关信息来回答您的问题。",
                        'source_documents': []
                    }
                    if self.enable_cache:
                        self.cache.set(cache_key, result)
                    return result
                
                # 2. 构建提示词
                prompt = self._build_prompt(question, retrieved_docs)
                logger.debug(f"构建提示词，长度: {len(prompt)}")
                
                # 3. 生成回答
                logger.info("开始生成回答")
                answer = self.llm.generate(prompt)
                logger.info(f"回答生成完成，长度: {len(answer)}")
                
                # 4. 构建结果
                result = {
                    'question': question,
                    'answer': answer,
                }
                
                if self.return_source_documents:
                    result['source_documents'] = retrieved_docs
                
                # 缓存结果
                if self.enable_cache:
                    self.cache.set(cache_key, result)
                
                return result
            
            except Exception as e:
                logger.error(f"RAG流程执行失败: {e}", exc_info=True)
                raise ChainError(f"RAG流程执行失败: {e}", chain_type="rag") from e
    
    def __call__(self, question: str, k: int = 4) -> str:
        """便捷调用方式"""
        result = self.run(question, k=k)
        return result['answer']


class ConversationalRAGChain(RAGChain):
    """对话式RAG链 - 支持多轮对话"""
    
    DEFAULT_CHAT_TEMPLATE = """基于以下上下文信息和对话历史回答当前问题。如果上下文信息不足以回答问题，请说明无法回答。

对话历史：
{chat_history}

上下文信息：
{context}

当前问题：{question}

请基于以上信息回答当前问题："""

    def __init__(
        self,
        retriever: BaseRetriever,
        llm: BaseLLM,
        prompt_template: str = None,
        return_source_documents: bool = False,
        memory_key: str = "chat_history"
    ):
        super().__init__(retriever, llm, prompt_template, return_source_documents)
        self.prompt_template = prompt_template or self.DEFAULT_CHAT_TEMPLATE
        self.memory_key = memory_key
        self.chat_history: List[Dict[str, str]] = []
    
    def _format_chat_history(self) -> str:
        """格式化对话历史"""
        formatted = []
        for msg in self.chat_history:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if role == 'user':
                formatted.append(f"用户: {content}")
            elif role == 'assistant':
                formatted.append(f"助手: {content}")
        return "\n".join(formatted) if formatted else "（无对话历史）"
    
    def _build_prompt(self, question: str, documents: List[Document]) -> str:
        """构建提示词（包含对话历史）"""
        context = self._format_documents(documents)
        chat_history = self._format_chat_history()
        
        return self.prompt_template.format(
            chat_history=chat_history,
            context=context,
            question=question
        )
    
    def run(self, question: str, k: int = 4) -> Dict[str, Any]:
        """运行对话式RAG流程"""
        result = super().run(question, k=k)
        
        # 更新对话历史
        self.chat_history.append({'role': 'user', 'content': question})
        self.chat_history.append({'role': 'assistant', 'content': result['answer']})
        
        return result
    
    def clear_history(self):
        """清空对话历史"""
        self.chat_history = []


class DecisionRAGChain(RAGChain):
    """
    决策型RAG链 - 专门用于决策支持
    提供决策建议、分析选项、评估风险等
    """
    
    DEFAULT_DECISION_TEMPLATE = """你是一位专业的决策顾问。基于以下背景信息，帮助用户做出明智的决策。

背景信息：
{context}

用户的决策问题：{question}

请提供：
1. 可选方案分析
2. 每个方案的优缺点
3. 潜在风险
4. 推荐方案及理由

决策建议："""

    def __init__(
        self,
        retriever: BaseRetriever,
        llm: BaseLLM,
        prompt_template: str = None,
        return_source_documents: bool = False,
        provide_analysis: bool = True
    ):
        super().__init__(retriever, llm, prompt_template, return_source_documents)
        self.prompt_template = prompt_template or self.DEFAULT_DECISION_TEMPLATE
        self.provide_analysis = provide_analysis
    
    def analyze_options(self, question: str, options: List[str], k: int = 4) -> Dict[str, Any]:
        """分析多个选项"""
        # 检索相关信息
        retrieved_docs = self.retriever.retrieve(question, k=k)
        context = self._format_documents(retrieved_docs)
        
        # 构建分析提示
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
        
        analysis_prompt = f"""基于以下背景信息，分析各个选项：

背景信息：
{context}

决策问题：{question}

待分析的选项：
{options_text}

请提供详细的分析，包括每个选项的优缺点和风险评估。"""
        
        analysis = self.llm.generate(analysis_prompt)
        
        result = {
            'question': question,
            'options': options,
            'analysis': analysis
        }
        
        if self.return_source_documents:
            result['source_documents'] = retrieved_docs
        
        return result
    
    def evaluate_risk(self, decision: str, k: int = 4) -> Dict[str, Any]:
        """评估决策风险"""
        retrieved_docs = self.retriever.retrieve(f"风险分析 {decision}", k=k)
        context = self._format_documents(retrieved_docs)
        
        risk_prompt = f"""基于以下背景信息，评估该决策的风险：

背景信息：
{context}

待评估的决策：{decision}

请分析：
1. 主要风险点
2. 风险等级（高/中/低）
3. 风险缓解建议
4. 最坏情况预案"""
        
        risk_analysis = self.llm.generate(risk_prompt)
        
        return {
            'decision': decision,
            'risk_analysis': risk_analysis
        }


class AgenticRAGChain:
    """
    Agentic RAG链 - 具有自主决策能力的RAG
    可以根据情况决定是否需要检索，检索多少次等
    """
    
    def __init__(
        self,
        retriever: BaseRetriever,
        llm: BaseLLM,
        max_iterations: int = 3,
        return_source_documents: bool = False,
        confidence_threshold: float = 0.7,
        enable_cache: bool = True
    ):
        self.retriever = retriever
        self.llm = llm
        self.max_iterations = max_iterations
        self.return_source_documents = return_source_documents
        self.confidence_threshold = confidence_threshold
        self.enable_cache = enable_cache
        self.cache = CacheManager(enable_memory_cache=enable_cache) if enable_cache else None
        logger.info(f"AgenticRAGChain 初始化, max_iterations={max_iterations}, confidence_threshold={confidence_threshold}")
    
    def _should_retrieve(self, question: str, current_context: str = "") -> bool:
        """判断是否需要检索"""
        if not current_context:
            logger.info("无上下文，需要检索")
            return True
        
        prompt = f"""基于当前已有的信息，判断是否需要检索更多资料来回答问题。

问题：{question}

当前已有信息：
{current_context if current_context else "（无）"}

请回答：是否需要检索更多信息？只回答"是"或"否"。"""
        
        response = self.llm.generate(prompt).strip().lower()
        should_retrieve = "是" in response or "yes" in response or "需要" in response
        logger.info(f"检索决策: {'需要' if should_retrieve else '不需要'}检索")
        return should_retrieve
    
    def _generate_search_query(self, question: str, current_context: str = "") -> str:
        """生成搜索查询"""
        if not current_context:
            return question
        
        prompt = f"""基于问题和当前信息，生成一个更具体的搜索查询来获取缺失的信息。

问题：{question}

当前已有信息：
{current_context}

请生成一个具体的搜索查询："""
        
        search_query = self.llm.generate(prompt).strip()
        logger.info(f"生成搜索查询: {search_query}")
        return search_query
    
    def _can_answer(self, question: str, context: str) -> bool:
        """判断是否可以回答问题"""
        prompt = f"""基于以下信息，判断是否足以回答用户的问题。

问题：{question}

可用信息：
{context}

请回答：现有信息是否足以回答问题？只回答"是"或"否"。"""
        
        response = self.llm.generate(prompt).strip().lower()
        can_answer = "是" in response or "yes" in response or "可以" in response
        logger.info(f"回答能力评估: {'可以' if can_answer else '不足以'}回答问题")
        return can_answer
    
    def _calculate_confidence(self, question: str, context: str, docs: List[Document]) -> float:
        """
        计算回答置信度
        
        Args:
            question: 问题
            context: 上下文
            docs: 检索到的文档
            
        Returns:
            置信度分数 (0.0 - 1.0)
        """
        confidence = 0.0
        
        # 基于文档数量
        doc_count_score = min(len(docs) / 5.0, 1.0)  # 最多5个文档
        confidence += doc_count_score * 0.3
        
        # 基于上下文长度
        context_length_score = min(len(context) / 1000.0, 1.0)  # 最多1000字符
        confidence += context_length_score * 0.3
        
        # 基于LLM评估
        prompt = f"""请评估以下信息对于回答问题的充分程度，给出0-1的分数。

问题：{question}

可用信息：
{context}

请只给出一个0-1之间的数字，不要解释。"""
        
        try:
            llm_score = float(self.llm.generate(prompt).strip())
            llm_score = max(0.0, min(llm_score, 1.0))  # 限制在0-1之间
            confidence += llm_score * 0.4
        except:
            confidence += 0.5 * 0.4  # 默认分数
        
        logger.info(f"置信度计算: {confidence:.2f} (文档: {doc_count_score:.2f}, 上下文: {context_length_score:.2f})")
        return confidence
    
    def run(self, question: str, k: int = 4) -> Dict[str, Any]:
        """运行Agentic RAG流程"""
        with PerformanceLogger(logger, f"AgenticRAGChain.run: {question[:30]}"):
            # 检查缓存
            if self.enable_cache:
                cache_key = generate_cache_key("agentic_rag", question=question, k=k)
                cached_result = self.cache.get(cache_key)
                if cached_result is not None:
                    logger.info(f"缓存命中，直接返回结果")
                    return cached_result
            
            all_documents = []
            current_context = ""
            iteration = 0
            
            for iteration in range(self.max_iterations):
                logger.info(f"=== 第 {iteration + 1} 轮迭代 ===")
                
                # 判断是否需要检索
                if not self._should_retrieve(question, current_context):
                    logger.info("LLM判断不需要更多检索")
                    break
                
                # 生成搜索查询
                search_query = self._generate_search_query(question, current_context)
                
                # 检索文档
                try:
                    docs = self.retriever.retrieve(search_query, k=k)
                    logger.info(f"检索到 {len(docs)} 个文档")
                except Exception as e:
                    logger.error(f"检索失败: {e}", exc_info=True)
                    raise RetrievalError(f"检索失败: {e}", query=search_query) from e
                
                if not docs:
                    logger.warning("未检索到文档")
                    break
                
                all_documents.extend(docs)
                
                # 更新上下文
                new_context = "\n\n".join([doc.page_content for doc in docs])
                current_context = current_context + "\n\n" + new_context if current_context else new_context
                
                # 计算置信度
                confidence = self._calculate_confidence(question, current_context, all_documents)
                logger.info(f"当前置信度: {confidence:.2f}")
                
                # 判断是否可以回答且置信度足够
                if confidence >= self.confidence_threshold:
                    logger.info(f"置信度 {confidence:.2f} 达到阈值 {self.confidence_threshold}，停止检索")
                    break
            
            # 生成最终回答
            try:
                final_prompt = f"""基于以下信息回答问题：

{current_context}

问题：{question}

请提供详细回答："""
                
                answer = self.llm.generate(final_prompt)
            except Exception as e:
                logger.error(f"回答生成失败: {e}", exc_info=True)
                raise LLMError(f"回答生成失败: {e}") from e
            
            # 去重文档
            seen_contents = set()
            unique_docs = []
            for doc in all_documents:
                if doc.page_content not in seen_contents:
                    unique_docs.append(doc)
                    seen_contents.add(doc.page_content)
            
            result = {
                'question': question,
                'answer': answer,
                'iterations': iteration + 1,
                'confidence': confidence if 'confidence' in locals() else 0.0,
                'total_documents': len(unique_docs)
            }
            
            if self.return_source_documents:
                result['source_documents'] = unique_docs
            
            # 缓存结果
            if self.enable_cache:
                self.cache.set(cache_key, result)
            
            return result
    
    def __call__(self, question: str, k: int = 4) -> str:
        """便捷调用"""
        result = self.run(question, k=k)
        return result['answer']
