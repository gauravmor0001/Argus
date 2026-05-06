import os
import json
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from api.state import ArgusState
from tools import web_search, search_knowledge_base, academic_research

detector_llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=os.getenv("web_search"), temperature=0)

COMPLEXITY_PROMPT = """You are a query classifier for an AI assistant that has these tools:
- search_knowledge_base: searches user's uploaded documents
- web_search: searches the internet for real-time info
- academic_research: finds research papers and literature reviews
- get_current_time: gets current date/time

Classify the user's query as either SIMPLE or COMPLEX.

SIMPLE = can be fully answered by calling ONE tool once, or needs no tool at all.
Examples:
- "what time is it" → simple
- "search my notes for transformers" → simple  
- "find papers on LLMs" → simple
- "what is machine learning" → simple (no tool needed)

COMPLEX = requires calling MULTIPLE different tools and then combining their results.
Examples:
- "compare what my notes say vs recent papers on transformers" → complex (needs knowledge_base + academic_research)
- "search my docs and also check latest news on this topic" → complex (needs knowledge_base + web_search)
- "find papers on X and compare with what I uploaded" → complex

Respond with ONLY valid JSON, no extra text:
{
  "classification": "simple" or "complex",
  "reason": "one sentence explanation"
}
"""

def complexity_detector(state: ArgusState) -> dict:
    """
    Entry point of the graph.
    Classifies the query and sets original_query and is_complex in state.
    """

    user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    print(f"[Complexity Detector] Analyzing: '{user_message}'")

    try:
        response = detector_llm.invoke([
            SystemMessage(content=COMPLEXITY_PROMPT),
            HumanMessage(content=user_message)
        ])

        result = json.loads(response.content.strip()) #we got string that contain json:'{"name": "Gaurav", "age": 20}' now json.loads convert that into python obj like {"name": "Gaurav","age": 20}
        classification = result.get("classification", "simple").lower()
        reason = result.get("reason", "")
        is_complex = classification == "complex"

        print(f"[Complexity Detector] → {classification.upper()} | {reason}")

        return {
            "original_query": user_message,
            "is_complex": is_complex,
            "current_step_index": 0,
            "step_results": [],   # initialize empty — operator.add will append to this
            "plan": []        
        }

    except (json.JSONDecodeError, Exception) as e:
        print(f"[Complexity Detector] Failed to parse, defaulting to simple. Error: {e}")
        return {
            "original_query": user_message,
            "is_complex": False,
            "current_step_index": 0,
            "step_results": [],
            "plan": []
        }


def route_after_detection(state: ArgusState) -> str:
    """
    Conditional edge after complexity_detector.
    Tells LangGraph which node to go to next.
    """
    if state.get("is_complex"):
        print("[Router] Complex query → sending to Planner")
        return "planner"
    else:
        print("[Router] Simple query → sending to existing Reasoner")
        return "agent" 
    


PLANNER_PROMPT = """You are a task planner for an AI assistant. Your job is to break down a complex user query into an ordered sequence of tool calls.

Available tools:
- search_knowledge_base: searches the user's uploaded documents/notes/PDFs
- web_search: searches the internet for real-time info and news
- academic_research: searches multiple academic databases for research papers
- synthesize: NOT a real tool — use this as the LAST step to signal "now combine all results and answer"

Rules:
1. Only use tools that are actually needed for the query
2. "synthesize" must always be the last step
3. Maximum 5 steps including synthesize
4. Keep queries in each step specific and focused
5. Each step must have a clear purpose that explains what it contributes to the final answer

Respond with ONLY valid JSON, no extra text:
{
  "steps": [
    {
      "step_id": 1,
      "tool": "tool_name_here",
      "query": "specific query to pass into the tool",
      "purpose": "what this step contributes to the final answer"
    },
    {
      "step_id": 2,
      "tool": "synthesize",
      "query": "",
      "purpose": "compare both sources and answer the user's question"
    }
  ]
}

Examples:

User: "compare what my notes say vs recent papers on transformers"
{
  "steps": [
    {"step_id": 1, "tool": "search_knowledge_base", "query": "transformers attention mechanism", "purpose": "get what user's uploaded notes say about transformers"},
    {"step_id": 2, "tool": "academic_research", "query": "transformer architecture recent advances 2024", "purpose": "get latest research findings on transformers"},
    {"step_id": 3, "tool": "synthesize", "query": "", "purpose": "compare user notes vs research papers and highlight differences"}
  ]
}

User: "search my docs and find latest news about the same topic"
{
  "steps": [
    {"step_id": 1, "tool": "search_knowledge_base", "query": "main topic from user docs", "purpose": "retrieve relevant content from uploaded documents"},
    {"step_id": 2, "tool": "web_search", "query": "latest news on that topic 2025", "purpose": "get current real-world developments"},
    {"step_id": 3, "tool": "synthesize", "query": "", "purpose": "combine document knowledge with latest news"}
  ]
}
"""

def planner_node(state: ArgusState) -> dict:
    """
    Takes the original query and produces an ordered plan of tool calls.
    """
    original_query = state["original_query"]
    print(f"[Planner] Building plan for: '{original_query}'")

    try:
        response = detector_llm.invoke([
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=original_query)
        ])

        # Strip markdown fences if LLM wraps in ```json
        raw = response.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        result = json.loads(raw)
        plan = result.get("steps", [])

        if not plan or plan[-1]["tool"] != "synthesize":
            plan.append({
                "step_id": len(plan) + 1,
                "tool": "synthesize",
                "query": "",
                "purpose": "combine all gathered information and answer the user"
            })

        print(f"[Planner] Plan created with {len(plan)} steps:")
        for step in plan:
            print(f"  Step {step['step_id']}: {step['tool']} — {step['purpose']}")

        return {"plan": plan}

    except (json.JSONDecodeError, Exception) as e:
        print(f"[Planner] Failed to build plan: {e}")
        # Safe fallback — single knowledge base search + synthesize
        return {
            "plan": [
                {"step_id": 1, "tool": "search_knowledge_base", "query": original_query, "purpose": "search documents"},
                {"step_id": 2, "tool": "synthesize", "query": "", "purpose": "answer the user"}
            ]
        }
    
TOOL_MAP = {
    "web_search": web_search,
    "search_knowledge_base": search_knowledge_base,
    "academic_research": academic_research,
}

def executor_node(state: ArgusState, config: RunnableConfig) -> dict:
    """
    Reads the current step from the plan, executes its tool, 
    stores the result, and increments the step index.
    """
    plan = state["plan"]
    current_index = state["current_step_index"]
    current_step = plan[current_index]

    tool_name = current_step["tool"]
    query = current_step["query"]
    purpose = current_step["purpose"]

    print(f"[Executor] Running step {current_step['step_id']}: {tool_name}")
    print(f"[Executor] Purpose: {purpose}")

    try:
        tool_fn = TOOL_MAP[tool_name]

        # search_knowledge_base needs config for user_id — others don't
        if tool_name == "search_knowledge_base":
            result = tool_fn.invoke({"query": query}, config=config)
        else:
            result = tool_fn.invoke({"query": query} if tool_name != "academic_research" else {"topic": query})

        print(f"[Executor] Step {current_step['step_id']} complete.")

    except Exception as e:
        result = f"Step failed: {str(e)}"
        print(f"[Executor] Step {current_step['step_id']} failed: {e}")

    # Store result — operator.add in state means this APPENDS, not overwrites
    step_result = {
        "step_id": current_step["step_id"],
        "tool": tool_name,
        "purpose": purpose,
        "result": result
    }

    return {
        "step_results": [step_result],       
        "current_step_index": current_index + 1 
    }


def route_after_executor(state: ArgusState) -> str:
    """
    Conditional edge after executor.
    Keeps looping until we hit the synthesize step.
    """
    plan = state["plan"]
    current_index = state["current_step_index"]

    # All tool steps done — check if next step is synthesize
    if current_index >= len(plan):
        print("[Router] All steps complete → Synthesizer")
        return "synthesizer"

    next_step = plan[current_index]
    if next_step["tool"] == "synthesize":
        print("[Router] Next step is synthesize → Synthesizer")
        return "synthesizer"

    print(f"[Router] More steps remain → looping back to Executor")
    return "executor"  # loop back


SYNTHESIZER_PROMPT = """You are an expert AI assistant. You have been given a user's original question and the results from multiple tools that were run to answer it.

Your job is to synthesize all the gathered information into a single, coherent, well-structured answer.

Rules:
1. Directly address the user's original question
2. Clearly distinguish between different sources (e.g. "According to your uploaded notes..." vs "Recent research papers show...")
3. Highlight agreements AND contradictions between sources if they exist
4. Do NOT mention tool names like "search_knowledge_base" or "web_search" — refer to them naturally as "your documents", "recent research", "current news" etc.
5. If a step failed or returned no results, acknowledge the gap briefly and move on
6. Be concise but complete — do not pad the answer unnecessarily
"""

def synthesizer_node(state: ArgusState) -> dict:
    """
    Takes all step_results + original_query and produces the final answer.
    """
    original_query = state["original_query"]
    step_results = state["step_results"]

    print(f"[Synthesizer] Combining {len(step_results)} results for: '{original_query}'")

    # Build a structured context block from all step results
    context_blocks = []
    for step in step_results:
        context_blocks.append(
            f"--- Source {step['step_id']}: {step['purpose']} ---\n{step['result']}"
        )
    
    full_context = "\n\n".join(context_blocks)

    synthesis_prompt = f"""User's Original Question:
{original_query}

Information Gathered:
{full_context}

Now write a complete, well-structured answer to the user's question using all the above information.
"""

    try:
        pure_llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=os.getenv("web_search"),
            temperature=0.3
        )

        response = pure_llm.invoke([
            SystemMessage(content=SYNTHESIZER_PROMPT),
            HumanMessage(content=synthesis_prompt)
        ])

        print("[Synthesizer] Final answer generated.")

        # Return as a proper AI message so it fits into existing messages flow
        return {"messages": [response]}

    except Exception as e:
        print(f"[Synthesizer] Failed: {e}")
        from langchain_core.messages import AIMessage
        return {
            "messages": [AIMessage(content=f"I gathered the information but failed to synthesize it. Error: {str(e)}")]
        }