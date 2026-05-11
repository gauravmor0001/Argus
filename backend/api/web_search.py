import os
import json
from dotenv import load_dotenv

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_tavily import TavilySearch 
from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.prebuilt import ToolNode, tools_condition

from datetime import datetime

load_dotenv()
llm = ChatGroq(
    model="llama-3.3-70b-versatile", 
    api_key=os.getenv("web_search"),
    temperature=0.1, 
)

RESEARCHER_SYSTEM_PROMPT = """You are an elite, backend web research agent.
Today's exact date is: {current_date}

Your primary objective is to search the web, extract factual information, and compile a comprehensive, highly detailed report.

STRICT RULES:
1. QUERY REWRITING: Never search generic terms like "current price" or "latest match". You MUST rewrite the search query to include today's month and year to force the search engine to return fresh data (e.g., "USD to INR exchange rate {current_date}").
2. CROSS-CHECKING (VERIFICATION): For financial data, sports scores, and real-time facts, you MUST compare at least two different sources. Do not rely on just one website. If sources conflict, keep searching.
3. MAXIMUM 4 SEARCHES. If you do not have the perfect answer after your searches, synthesize the best answer you can from the data you found.
4. Write a comprehensive response. Include exact numbers, dates, and background context. Do NOT be brief.
5. IMPORTANT FORMATTING: At the very end of your final response, you MUST list EVERY SINGLE source URL you gathered data from using this exact format on new lines:
SOURCE_URL::https://example.com
6. Do NOT put URLs directly inside the text of your paragraphs.
CRITICAL RULE: Your answer must be based EXCLUSIVELY on the search results provided above.
Do NOT use your training knowledge to answer — even if you believe you know the answer.
If the search results say X, your answer must say X, regardless of what you were trained on.
Extract the answer directly from the retrieved content.
"""

@tool
def web_search(query: str):
    """
    Search the internet for real-time information, news, weather, or facts.
    """
    try:
        search_tool = TavilySearch(max_results=3)
        raw = search_tool.invoke({"query": query})

        print(f"[Web Agent] Executing search for: {query}")

        if isinstance(raw, dict):
            results = raw.get('results', [])
        elif isinstance(raw, list):
            results = raw
        else:
            return f"SOURCE_URL::unknown\nSNIPPET::{str(raw)[:500]}"

        if not results:
            return "No results found. Try a different search query."

        output = []
        for res in results:
            url = res.get('url', 'unknown')
            content = res.get('content', '')[:400]
            output.append(f"SOURCE_URL::{url}\nSNIPPET::{content}")

        return "\n\n---\n\n".join(output)

    except Exception as e:
        return f"Search failed: {str(e)}"

tools_list = [web_search]
llm_with_tools = llm.bind_tools(tools_list)

def researcher_node(state: MessagesState):
    """The thinking node for the Web Agent."""
    messages = state["messages"]
    
    if len(messages) > 0 and not isinstance(messages[0], SystemMessage):
        today_str = datetime.now().strftime("%B %d, %Y")
        formatted_prompt = RESEARCHER_SYSTEM_PROMPT.format(current_date=today_str)
        messages = [SystemMessage(content=formatted_prompt)] + messages

    tool_count = sum(1 for msg in messages if isinstance(msg, ToolMessage))
    
    if tool_count >= 4:
        print(f"[Web Agent] ⚠️ Max searches reached ({tool_count}). Forcing final synthesis...")
        response = llm.invoke(messages) 
    else:
        response = llm_with_tools.invoke(messages)
        
    return {"messages": [response]}

builder = StateGraph(MessagesState)
builder.add_node("web_researcher", researcher_node)
builder.add_node("tools", ToolNode(tools_list))

builder.set_entry_point("web_researcher")
builder.add_conditional_edges("web_researcher", tools_condition)
builder.add_edge("tools", "web_researcher")

web_research_app = builder.compile()

def execute_web_research(query: str) -> str:
    """
    This is the clean function, main chat.py will call.
    It hides all the graph complexity from the Manager.
    """
    print(f"\n[Web Agent] Waking up to research: '{query}'")
    
    try:
        final_state = web_research_app.invoke(
            {"messages": [HumanMessage(content=query)]}
        )
        final_answer = final_state["messages"][-1].content
        return final_answer
    except Exception as e:
        print(f"[Web Agent] Fatal Error: {e}")
        return "I apologize, but my research agent encountered a critical error while searching the web."