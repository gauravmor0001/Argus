from datetime import datetime
from langchain_core.tools import tool
from langchain_tavily import TavilySearch 
import wikipedia
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse, RetrievalMode
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder 
from langchain_core.runnables import RunnableConfig #secure back channel
from qdrant_client.http import models #we can not simply say filter using user_id to qdrant, so to make the format of the filter we require this.
from api.web_search import execute_web_research
from api.research import run_deep_research

embedding_model = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)
sparse_embedding_model = FastEmbedSparse(model_name="Qdrant/bm25")
reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2') #classification model (act as grader and gives score)

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

@tool
def search_knowledge_base(query: str, config: RunnableConfig):
    """
    Use this tool to search for information inside the uploaded PDF documents or text files.
    Input should be a specific search query related to the documents.
    Returns the relevant text snippets from the files using a Hybrid (Dense+BM25) Advanced RAG pipeline.
    """
    user_id = config.get("configurable", {}).get("user_id")
    target_file = config.get("configurable", {}).get("target_file", "all")
    
    print(f"DEBUG: Searching Knowledge Base for: '{query}', user: {user_id}, target_file: {target_file}")
    
    try:
        vector_db = QdrantVectorStore.from_existing_collection(
            embedding=embedding_model,
            sparse_embedding=sparse_embedding_model,
            retrieval_mode=RetrievalMode.HYBRID,
            url="http://localhost:6333",
            collection_name="learning-rag"
        )
        
        # 1. Build the mandatory conditions list (always filter by user_id!)
        must_conditions = [
            models.FieldCondition(
                key="metadata.user_id",
                match=models.MatchValue(value=user_id)
            )
        ]
        
        # 2. If a specific file is targeted, append it to the conditions
        if target_file != "all":
            must_conditions.append(
                models.FieldCondition(
                    key="metadata.filename",  # Make sure this matches the key you used when saving the document!
                    match=models.MatchValue(value=target_file)
                )
            )
            
        # 3. Construct the final Qdrant filter
        search_filter = models.Filter(must=must_conditions)

        # 4. Execute the search with the dynamic filter
        initial_results = vector_db.similarity_search(query, k=15, filter=search_filter)
        
        if not initial_results:
            return "No relevant information found in the documents."
        
        print(f"DEBUG: Stage 1 found {len(initial_results)} snippets. Re-ranking...")

        query_doc_pairs = [[query, doc.page_content] for doc in initial_results]
        scores = reranker.predict(query_doc_pairs)
        scored_docs = list(zip(initial_results, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        top_3_docs = scored_docs[:3]

        print(f"DEBUG: Top snippet score after re-ranking: {top_3_docs[0][1]:.2f}")
        context = "\n\n".join([f"Snippet: {doc[0].page_content}" for doc in top_3_docs])
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

tools_list = [get_current_time , web_search,search_knowledge_base,academic_research]

#we have not given user_id to llm as to protect from prompt injection attack.as llm fills out the parameter of search_knowledge_base when the tool is called.
#so we use config={"configurable": {"user_id": user_id}}