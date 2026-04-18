from datetime import datetime
from langchain_core.tools import tool
# from langchain_community.tools import TavilySearchResults
from langchain_tavily import TavilySearch 
import wikipedia
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder 
from langchain_core.runnables import RunnableConfig #secure back channel
from qdrant_client.http import models #we can not simply say filter using user_id to qdrant, so to make the format of the filter we require this.


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
    try:
        search_tool = TavilySearch(max_results=3)
        raw = search_tool.invoke({"query": query})

        print(f"DEBUG: Result type: {type(raw)}")

        # TavilySearch returns a DICT like {'results': [...], 'answer': '...'}
        # NOT a list — extract the list first
        if isinstance(raw, dict):
            results = raw.get('results', [])
        elif isinstance(raw, list):
            results = raw
        else:
            # Fallback: plain string answer
            return f"SOURCE_URL::unknown\nSNIPPET::{str(raw)[:500]}"

        if not results:
            return "No results found."

        output = []
        for res in results:
            url = res.get('url', 'unknown')
            content = res.get('content', '')[:300]
            output.append(f"SOURCE_URL::{url}\nSNIPPET::{content}")

        print(f"DEBUG: Web search returned {len(results)} results")
        return "\n\n---\n\n".join(output)

    except Exception as e:
        return f"Search failed: {str(e)}"
@tool
def search_knowledge_base(query: str, config: RunnableConfig):
    """
    Use this tool to search for information inside the uploaded PDF documents or text files.
    Input should be a specific search query related to the documents.
    Returns the relevant text snippets from the files using a Hybrid (Dense+BM25) Advanced RAG pipeline.
    """
    user_id = config.get("configurable", {}).get("user_id")
    print(f"DEBUG: Searching Knowledge Base for: '{query}',user:{user_id}")
    try:
        vector_db = QdrantVectorStore.from_existing_collection(
            embedding=embedding_model,
            sparse_embedding=sparse_embedding_model,
            retrieval_mode="HYBRID",
            url="http://localhost:6333",
            collection_name="learning-rag"
        )
        user_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.user_id",
                    match=models.MatchValue(value=user_id)
                )
            ]
        )
        initial_results = vector_db.similarity_search(query, k=15,filter=user_filter)
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


tools_list = [get_current_time , web_search,search_knowledge_base]

#we have not given user_id to llm as to protect from prompt injection attack.as llm fills out the parameter of search_knowledge_base when the tool is called.
#so we use config={"configurable": {"user_id": user_id}}