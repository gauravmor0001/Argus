import os
import requests
import arxiv
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage,ToolMessage
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.prebuilt import ToolNode, tools_condition
import re

load_dotenv()

@tool
def search_semantic_scholar(query: str, limit: int = 10) -> str:
    """Searches Semantic Scholar for highly cited, impactful papers."""
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {"query": query, "limit": limit, "fields": "title,authors,year,abstract,citationCount,url"}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "data" not in data or not data["data"]: return "No papers found on Semantic Scholar."
        
        results = ["--- SEMANTIC SCHOLAR RESULTS ---"]
        for paper in data["data"]:
            authors = paper.get("authors", [])
            author_text = authors[0]["name"] + " et al." if authors else "Unknown"
            results.append(
                f"Title: {paper.get('title')}\nYear: {paper.get('year')} | Citations: {paper.get('citationCount')}\n"
                f"Abstract: {paper.get('abstract', 'N/A')}\nURL: {paper.get('url')}\n"
            )
        return "\n".join(results)
    except Exception as e:
        return f"Semantic Scholar error: {str(e)}"

@tool
def search_arxiv(query: str, max_results: int = 10) -> str:
    """Searches ArXiv for the absolute latest, cutting-edge Computer Science and AI papers."""
    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        results = ["--- ARXIV (LATEST) RESULTS ---"]
        for paper in client.results(search):
            results.append(
                f"Title: {paper.title}\nPublished: {paper.published.date()}\n"
                f"Abstract: {paper.summary}\nURL: {paper.pdf_url}\n"
            )
        return "\n\n".join(results)
    except Exception as e:
        return f"ArXiv error: {str(e)}"


@tool
def search_crossref(query: str, limit: int = 10) -> str:
    """Searches CrossRef for foundational and interdisciplinary academic papers."""
    url = "https://api.crossref.org/works"
    params = {
        "query": query,
        "rows": limit,
        "select": "title,author,published-print,abstract,URL,is-referenced-by-count"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status() #give error if request failed
        items = response.json().get("message", {}).get("items", [])
        if not items:
            return "No papers found on CrossRef."

        results = ["--- CROSSREF RESULTS ---"]
        for item in items:
            title = item.get("title", ["N/A"])[0]
            authors = item.get("author", [])
            author_text = f"{authors[0].get('family', 'Unknown')} et al." if authors else "Unknown"
            year = item.get("published-print", {}).get("date-parts", [[None]])[0][0]
            abstract = item.get("abstract", "No abstract available.").replace("<jats:p>", "").replace("</jats:p>", "")
            citations = item.get("is-referenced-by-count", 0)
            url_link = item.get("URL", "N/A")
            results.append(
                f"Title: {title}\nAuthors: {author_text} | Year: {year} | Citations: {citations}\n"
                f"Abstract: {abstract}\nURL: {url_link}\n"
            )
        return "\n".join(results)
    except Exception as e:
        return f"CrossRef error: {str(e)}"


@tool
def search_openalex(query: str, limit: int = 10) -> str:
    """Searches OpenAlex for a wide range of academic papers with citation data."""
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "per-page": limit,
        "select": "title,authorships,publication_year,abstract_inverted_index,cited_by_count,primary_location"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        items = response.json().get("results", [])
        if not items:
            return "No papers found on OpenAlex."

        results = ["--- OPENALEX RESULTS ---"]
        for item in items:
            title = item.get("title", "N/A")
            year = item.get("publication_year", "N/A")
            citations = item.get("cited_by_count", 0)

            # Reconstruct abstract from inverted index
            inverted = item.get("abstract_inverted_index")
            if inverted:
                index_pairs = [(word, pos) for word, positions in inverted.items() for pos in positions]
                index_pairs.sort(key=lambda x: x[1])
                abstract = " ".join(word for word, _ in index_pairs)
            else:
                abstract = "No abstract available."

            # Get paper URL
            primary = item.get("primary_location") or {}
            paper_url = primary.get("landing_page_url", "N/A")

            results.append(
                f"Title: {title}\nYear: {year} | Citations: {citations}\n"
                f"Abstract: {abstract}\nURL: {paper_url}\n"
            )
        return "\n".join(results)
    except Exception as e:
        return f"OpenAlex error: {str(e)}"
    

research_tools = [search_semantic_scholar, search_arxiv,search_crossref,search_openalex]

def deduplicate_papers(raw_text: str) -> str:
    """
    Parses all tool result text, deduplicates papers by normalized title,
    and returns a cleaned string with unique papers only.
    """
    # Split into individual paper blocks by detecting 'Title:' entries
    blocks = re.split(r'(?=Title:)', raw_text)
    
    seen_titles = set()
    unique_blocks = []

    for block in blocks:
        block = block.strip()
        if not block or not block.startswith("Title:"):
            unique_blocks.append(block)  # keep headers like --- SOURCE ---
            continue

        # Extract title and normalize it
        title_match = re.search(r'Title:\s*(.+)', block)
        if not title_match:
            continue

        raw_title = title_match.group(1).strip()
        # Normalize: lowercase, remove punctuation and extra spaces
        normalized = re.sub(r'[^a-z0-9\s]', '', raw_title.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        if normalized not in seen_titles:
            seen_titles.add(normalized)
            unique_blocks.append(block)
        else:
            print(f"[Dedup] Removed duplicate: {raw_title}")

    return "\n\n".join(unique_blocks)

RESEARCHER_PROMPT = """You are a PhD-level Academic Research AI. Your job is to analyze literature and identify novel research opportunities.

STRICT RULE: Do NOT output any text or commentary before you have finished ALL your tool calls. Search all relevant databases first, then produce your final report.

Your final response MUST follow this structure EXACTLY, generated only ONCE:

[Write 3 to 4 lines introducing the topic, defining what it is, and summarizing the general current state of the research.]

### These are the most relevant papers found:

**1. [Paper Title]** ([Year]) - [Link to Paper](URL)
- **Covers:** [1-2 sentences explaining what this paper successfully achieved]

- **Lacks:** [1-2 sentences explaining the limitations, what it missed, or what it failed to solve]

[Repeat the paper block for the top papers found, up to a maximum of 10. Put a blank line between each paper block.]

### Conclusion & Novel Research Opportunities
[Write 1-2 paragraphs identifying the overarching gaps across all these papers. Conclude by suggesting 2 to 3 specific, actionable new ideas that the user can work upon for their own novel research paper.]
"""

research_llm = ChatGroq(
    model="llama-3.3-70b-versatile", 
    api_key=os.getenv("web_search"),
    temperature=0.2
).bind_tools(research_tools)

def research_node(state: MessagesState):
    """Only responsible for searching — never synthesizes."""
    messages = state["messages"]

    if len(messages) > 0 and not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=RESEARCHER_PROMPT)] + messages

    tool_count = sum(1 for msg in messages if isinstance(msg, AIMessage) and msg.tool_calls)
    if tool_count >= 4:
        # Signal to stop tool calling — return a plain message so tools_condition routes to END
        return {"messages": [AIMessage(content="__RESEARCH_COMPLETE__")]}

    print("[Research Agent] Fetching academic data...")
    return {"messages": [research_llm.invoke(messages)]}


def synthesis_node(state: MessagesState):
    """Always runs at the end to produce the clean formatted output."""
    messages = state["messages"]

    print("[Research Agent] Deduplicating and synthesizing final report...")
    all_tool_text = " ".join(
        msg.content for msg in messages if isinstance(msg, ToolMessage)
    )
    clean_context = deduplicate_papers(all_tool_text)

    dedup_message = HumanMessage(
        content=f"Here are the deduplicated research papers found. Now synthesize them per the required format:\n\n{clean_context}"
    )
    synthesis_messages = [SystemMessage(content=RESEARCHER_PROMPT), dedup_message]
    pure_llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.2)
    return {"messages": [pure_llm.invoke(synthesis_messages)]}


def route_after_agent(state: MessagesState):
    """Custom router: if research is complete, go to synthesis. Otherwise use tools."""
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage):
        if last_msg.content == "__RESEARCH_COMPLETE__":
            return "synthesize"
        if last_msg.tool_calls:
            return "tools"
    return "synthesize"  # LLM stopped calling tools on its own → still synthesize


research_graph = StateGraph(MessagesState)
research_graph.add_node("research_agent", research_node)
research_graph.add_node("tools", ToolNode(research_tools))
research_graph.add_node("synthesize", synthesis_node) 
research_graph.set_entry_point("research_agent")
research_graph.add_conditional_edges("research_agent", route_after_agent, {
    "tools": "tools",
    "synthesize": "synthesize"
})
research_graph.add_edge("tools", "research_agent")
research_graph.add_edge("synthesize", END)             
research_app = research_graph.compile()

def run_deep_research(topic: str) -> str:
    """Runs the full research graph and returns the final synthesized markdown string."""
    print(f"\n[Manager] Waking up Research Agent for topic: {topic}")
    
    state = research_app.invoke({"messages": [HumanMessage(content=topic)]})
    return state["messages"][-1].content