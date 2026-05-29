from datetime import datetime
from langchain_core.tools import tool
from langchain_tavily import TavilySearch 
import wikipedia
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from langchain_core.runnables import RunnableConfig  # secure back channel
from qdrant_client.http import models  # we can not simply say filter using user_id to qdrant, so to make the format of the filter we require this.
from api.web_search import execute_web_research
from api.research import run_deep_research
from pydantic import BaseModel, Field
import os

# --- LAZY MODEL SINGLETONS ---
# Models are NOT loaded at import time.
# They are loaded the first time they are actually needed (on first tool call).
# This allows uvicorn to bind the port instantly, fixing the Render deployment issue.

_embedding_model = None
_sparse_model = None
_reranker = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        print("[Models] Loading remote HF embedding model...")
        from langchain_huggingface import HuggingFaceEndpointEmbeddings
        _embedding_model = HuggingFaceEndpointEmbeddings(
            model="sentence-transformers/all-MiniLM-L6-v2",
            huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN")
        )
        print("[Models] Remote embedding model ready.")
    return _embedding_model

def get_sparse_model():
    global _sparse_model
    if _sparse_model is None:
        print("[Models] Loading sparse embedding model...")
        from langchain_qdrant import FastEmbedSparse
        _sparse_model = FastEmbedSparse(model_name="Qdrant/bm25")
        print("[Models] Sparse model ready.")
    return _sparse_model

# def get_reranker():
#     global _reranker
#     if _reranker is None:
#         print("[Models] Loading reranker model...")
#         from sentence_transformers import CrossEncoder
#         _reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')  # classification model (act as grader and gives score)
#         print("[Models] Reranker ready.")
#     return _reranker


class SearchKBInput(BaseModel):
    query: str = Field(description="The exact search query to look up in the documents.")

@tool
def get_current_time():
    """Get the current real-time date and time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def web_search(query: str):
    """
    Search the internet for real-time information, news, weather, or facts.
    Use this when the user asks about current events or topics you don't know.
    """
    print(f"[Manager] calling Researcher Agent...")
    
    research_report = execute_web_research(query)
    
    return research_report

@tool("search_knowledge_base", args_schema=SearchKBInput)
def search_knowledge_base(query: str, config: RunnableConfig):
    """
    Use this to search the user's uploaded documents.
    Pass only a search query string. Example: "main topics" or "key findings".
    DO NOT pass filenames or file paths as arguments.
    """
    user_id = config.get("configurable", {}).get("user_id")
    target_file = config.get("configurable", {}).get("target_file", "all")
    
    print(f"DEBUG: Searching Knowledge Base for: '{query}', user: {user_id}, target_file: {target_file}")
    
    try:
        # Models are fetched lazily here — loaded only on first actual search call
        vector_db = QdrantVectorStore.from_existing_collection(
            embedding=get_embedding_model(),
            sparse_embedding=get_sparse_model(),
            retrieval_mode=RetrievalMode.HYBRID,
            url=os.getenv("qdrant_url"),         
            api_key=os.getenv("qdrant_cloud_key"),
            collection_name="learning-rag"
        )
        
        must_conditions = [
            models.FieldCondition(
                key="metadata.user_id",
                match=models.MatchValue(value=user_id)
            )
        ]
        
        if target_file != "all":
            must_conditions.append(
                models.FieldCondition(
                    key="metadata.filename", 
                    match=models.MatchValue(value=target_file)
                )
            )
            
        search_filter = models.Filter(must=must_conditions)
        initial_results = vector_db.similarity_search(query, k=5, filter=search_filter)  # this also gives us the list[documents].
        
        if not initial_results:
            return "No relevant information found in the documents."

        print(f"DEBUG: Found {len(initial_results)} snippets. Returning top 5...")
        context = "\n\n".join([f"Snippet: {doc.page_content}" for doc in initial_results[:5]])
        return context

    except Exception as e:
        return f"Error searching documents: {str(e)}"

@tool
def academic_research(topic: str) -> str:
    """
    CRITICAL: Use this tool ONLY when the user explicitly asks about:
    - State-of-the-art (SOTA) in a field
    - Writing a research paper
    - Literature reviews
    - Finding "gaps" in current research
    
    Pass the user's research topic into this tool, and a specialized 
    Academic Agent will take over, search multiple databases, and write a full report.
    """
    report = run_deep_research(topic)
    return (
        "The Research Agent has compiled the following report. "
        "Your ONLY task is to present this exact report to the user. "
        "Do NOT add any greetings, summaries, or conclusions of your own. "
        f"Just output this text:\n\n{report}"
    )

tools_list = [get_current_time, web_search, search_knowledge_base, academic_research]

# we have not given user_id to llm as to protect from prompt injection attack. as llm fills out the parameter of search_knowledge_base when the tool is called.
# so we use config={"configurable": {"user_id": user_id}}