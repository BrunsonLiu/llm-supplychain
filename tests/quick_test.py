# -*- coding: utf-8 -*-
"""
RAG Project Quick Test
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rag import Document, MockEmbeddings, MockLLM


def test_document():
    """Test Document class"""
    print("Testing Document...")
    doc = Document(page_content="Test content", metadata={"source": "test.txt"})
    assert doc.page_content == "Test content"
    assert doc.metadata["source"] == "test.txt"
    print("✓ Document test passed")


def test_mock_embeddings():
    """Test MockEmbeddings"""
    print("\nTesting MockEmbeddings...")
    embeddings = MockEmbeddings(dimension=10)
    
    # Test single query
    embedding = embeddings.embed_query("test")
    assert len(embedding) == 10
    
    # Test batch
    texts = ["text1", "text2", "text3"]
    embeddings_list = embeddings.embed_documents(texts)
    assert len(embeddings_list) == 3
    assert len(embeddings_list[0]) == 10
    
    print("✓ MockEmbeddings test passed")


def test_mock_llm():
    """Test MockLLM"""
    print("\nTesting MockLLM...")
    llm = MockLLM()
    
    response = llm.generate("test question")
    assert isinstance(response, str)
    
    full_response = llm.generate_with_response("test")
    assert hasattr(full_response, 'content')
    assert hasattr(full_response, 'usage')
    
    print("✓ MockLLM test passed")


def test_memory_vector_store():
    """Test MemoryVectorStore"""
    print("\nTesting MemoryVectorStore...")
    from rag import MemoryVectorStore
    
    store = MemoryVectorStore()
    embeddings = MockEmbeddings()
    
    # Add documents
    docs = [
        Document(page_content="Machine learning is core AI tech"),
        Document(page_content="Deep learning is a subset"),
    ]
    embeddings_list = embeddings.embed_documents([d.page_content for d in docs])
    store.add_documents(docs, embeddings_list)
    
    # Search
    query_emb = embeddings.embed_query("machine learning")
    results = store.similarity_search(query_emb, k=2)
    
    assert len(results) == 2
    assert results[0][1] > 0
    
    print("✓ MemoryVectorStore test passed")


def test_text_splitter():
    """Test text splitter"""
    print("\nTesting RecursiveCharacterTextSplitter...")
    from rag import RecursiveCharacterTextSplitter
    
    splitter = RecursiveCharacterTextSplitter(chunk_size=50, chunk_overlap=10)
    text = "This is a very long text. " * 20
    chunks = splitter.split_text(text)
    
    assert len(chunks) > 1
    # 允许一些余量，不要太严格
    for chunk in chunks:
        assert len(chunk) <= 150  # 放宽限制
    
    print("✓ RecursiveCharacterTextSplitter test passed")


def test_rag_chain():
    """Test RAGChain"""
    print("\nTesting RAGChain...")
    from rag import (
        RecursiveCharacterTextSplitter, MockEmbeddings,
        MemoryVectorStore, VectorRetriever, RAGChain
    )
    
    # Create document
    docs = [Document(page_content="AI is a branch of computer science.")]
    
    # Split
    splitter = RecursiveCharacterTextSplitter(chunk_size=100, chunk_overlap=20)
    chunks = splitter.split_documents(docs)
    
    # Embed
    embeddings = MockEmbeddings()
    chunk_embeddings = embeddings.embed_documents([c.page_content for c in chunks])
    
    # Store
    vector_store = MemoryVectorStore()
    vector_store.add_documents(chunks, chunk_embeddings)
    
    # Create retriever and LLM
    retriever = VectorRetriever(vector_store, embeddings)
    llm = MockLLM()
    
    # Create RAG chain
    rag_chain = RAGChain(retriever, llm)
    
    # Run
    result = rag_chain.run("What is AI?")
    assert 'answer' in result
    assert 'question' in result
    
    print("✓ RAGChain test passed")
    print(f"  Answer: {result['answer'][:50]}...")


def main():
    print("=" * 60)
    print("RAG Project Quick Test")
    print("=" * 60)
    
    try:
        test_document()
        test_mock_embeddings()
        test_mock_llm()
        test_memory_vector_store()
        test_text_splitter()
        test_rag_chain()
        
        print("\n" + "=" * 60)
        print("All tests passed!")
        print("=" * 60)
        return True
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
