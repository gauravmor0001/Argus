from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
import os
from dotenv import load_dotenv

from database import UserDatabase
from api.auth import verify_token

import re #(regular expression)using it to find xml.
import json
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage  #systemMessage is instruction to the model.
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph,MessagesState, END
from api.state import ArgusState
from langgraph.prebuilt import ToolNode, tools_condition 
from mem0 import Memory
from tools import tools_list
from fastapi.responses import StreamingResponse 
import uuid
from langchain_core.runnables import RunnableConfig
from api.planner import complexity_detector, route_after_detection,planner_node, executor_node, synthesizer_node, route_after_executor


load_dotenv()

router = APIRouter()
db = UserDatabase()

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    tools_allowed: Optional[dict] = None
    target_file: Optional[str] = "all"

MODEL_NAME = "llama-3.3-70b-versatile"
llm = ChatGroq(
    model=MODEL_NAME, 
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.3,
)
llm_with_tools = llm.bind_tools(tools_list)

config = {
    "version": "v1.1",
    "custom_prompt": (
        "You are a memory extraction assistant. Analyze the conversation and extract "
        "important facts about the user. Focus strictly on: "
        "1. Personal details (name, location, occupation, academic details). "
        "2. Technical skills and programming languages they use. "
        "3. Current projects they are working on (e.g., 'building a RAG system'). "
        "4. Specific preferences (e.g., 'keep answers short', 'prefers dark mode'). "
        "Ignore general knowledge questions, greetings, and file summaries. "
        "Store the memories concisely in the third person (e.g., 'User is building an AI chatbot')."
    ),
    "embedder": {
        "provider": "huggingface",
        "config": {
            "api_key": os.getenv("HUGGINGFACEHUB_API_TOKEN"),
            "model": "sentence-transformers/all-MiniLM-L6-v2"
        }
    },
    "llm": { #decide what mem0 will remember about user and its prefrences.
        "provider": "groq",
        "config": {
            "api_key": os.getenv("GROQ_API_KEY"),
            "model": MODEL_NAME,
        }
    },
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "chat_memory",
            "path": "./memory_db" # This creates a folder named memory_db 
        }
    }
}

print("DEBUG: Connecting to Mem0 Memory...")
mem_client = Memory.from_config(config)
def normalize_tool_calls(state: MessagesState):
    """Fixes Groq's XML tool formatting to match LangChain's JSON expectation."""
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        return state

    content = last.content or ""

    # ── Groq hard failure: it literally says it failed ──
    # This happens when tool call JSON is so broken Groq gives up
    if "Failed to call a function" in content or "failed_generation" in content:
        print("DEBUG: Groq tool call generation failed — clearing bad tool_calls")
        # Replace with a clean message that tells the agent to answer directly
        state["messages"][-1] = AIMessage(
            content="I encountered an issue using my tools. Let me answer based on what I know.",
            tool_calls=[]
        )
        return {"messages": state["messages"]}

    match = re.search(r'<function=([a-zA-Z0-9_\-]+)\s*(\{[\s\S]*?\})?>', content)
    if not match:
        return state

    tool_name = match.group(1)
    args_raw = match.group(2)
    try:
        args = json.loads(args_raw) if args_raw else {}
    except:
        args = {}

    new_message = AIMessage(
        content=last.content,
        tool_calls=[{"name": tool_name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}]
    )
    print(f"DEBUG normalize: tool={tool_name}, args={args}")
    state["messages"][-1] = new_message
    return {"messages": state["messages"]}

def reasoner(state: MessagesState, config: RunnableConfig):
    """The main thinking node for the AI, with Dynamic Tool Binding."""
    tools_allowed = config.get("configurable", {}).get("tools_allowed", {})

    active_tools = []
    for tool in tools_list:
        if tools_allowed.get(tool.name, True):
            active_tools.append(tool)

    last_message = state["messages"][-1]
    
    # If the last message was a tool result, the Manager's only job is to synthesize.
    # but this does not help when we need to evaluate the tools response and try again so.
    if hasattr(last_message, 'type') and last_message.type == 'tool':
        print("DEBUG: Tools just finished. Disarming Manager for final text synthesis.")
        bound_llm = llm 
        
    elif active_tools:
        print(f"DEBUG: Binding tools: {[t.name for t in active_tools]}")
        bound_llm = llm.bind_tools(active_tools)
        
    else:
        print("DEBUG: No tools allowed. Running as pure text LLM.")
        bound_llm = llm

    response = bound_llm.invoke(state["messages"])
    
    return {"messages": [response]}


workflow = StateGraph(ArgusState)
workflow.add_node("agent", reasoner)
workflow.add_node("tools", ToolNode(tools_list))
workflow.add_node("normalize", normalize_tool_calls)

workflow.add_node("complexity_detector", complexity_detector)
workflow.add_node("planner", planner_node)
workflow.add_node("executor", executor_node)
workflow.add_node("synthesizer", synthesizer_node)

workflow.set_entry_point("complexity_detector")
workflow.add_conditional_edges("complexity_detector", route_after_detection, {
    "agent": "agent", 
    "planner": "planner"      
})

workflow.add_edge("agent", "normalize")
workflow.add_conditional_edges("normalize", tools_condition) #tools condition is pre defined if the normalize node send a tool call it understnand and call the tool.
workflow.add_edge("tools", "agent")

workflow.add_edge("planner", "executor")
workflow.add_conditional_edges("executor", route_after_executor, {
    "executor": "executor",     
    "synthesizer": "synthesizer" 
})
workflow.add_edge("synthesizer", END) 
agent_app = workflow.compile()

def extract_citations(tool_text: str):
    citations = []
    if not tool_text: return citations
    
    current_snippet = "Web Research Source"
    
    for line in tool_text.split('\n'):
        line = line.strip()
        if line.startswith('SNIPPET::'):
            current_snippet = line.replace('SNIPPET::', '').strip()
        elif line.startswith('SOURCE_URL::'):
            url = line.replace('SOURCE_URL::', '').strip()
            # Append immediately so we don't overwrite it!
            if url and not any(c['url'] == url for c in citations):
                citations.append({'url': url, 'snippet': current_snippet})
            current_snippet = "Web Research Source" # Reset for the next one
            
    return citations

def grade_answer(question: str, answer: str) -> str:
    grader_prompt = (
        f"You are a grader. A user asked a question and an AI gave an answer.\n\n"
        f"Question: {question}\n"
        f"Answer: {answer}\n\n"
        f"Does this answer address the question asked?\n"
        f"Reply with ONLY one word — either 'relevant' or 'not_relevant'. Nothing else."
    )
    try:
        result = llm.invoke([HumanMessage(content=grader_prompt)])
        verdict = result.content.strip().lower()
        print(f"DEBUG: Answer grader verdict: '{verdict}'")
        # Guard against the LLM adding extra words
        return 'relevant' if verdict == 'relevant' else 'not_relevant'
    except Exception as e:
        print(f"DEBUG: Grader failed: {e}")
        return 'relevant'
    
@router.get("/memories")
async def get_user_memories(authorization: Optional[str] = Header(None)):
    try:
        user_id, username = verify_token(authorization)
        memories_data = mem_client.get_all(user_id=user_id)
        
        # Mem0 returns a slightly complex dictionary. We just want to extract 
        # the ID, the readable text, and the date it was created.
        clean_memories = []
        
        # Handle different versions of Mem0 response formats
        raw_memories = memories_data.get("results", memories_data) if isinstance(memories_data, dict) else memories_data
        
        if raw_memories:
            for mem in raw_memories:
                clean_memories.append({
                    "id": mem.get("id"),
                    "text": mem.get("memory", "Unknown memory format"),
                    "date": mem.get("updated_at") or mem.get("created_at")
                })
                
        return {"status": "success", "memories": clean_memories}
        
    except Exception as e:
        print(f"DEBUG: Error fetching memories: {e}")
        return {"status": "error", "message": str(e)}


@router.delete("/memories/{memory_id}")
async def delete_user_memory(memory_id: str, authorization: Optional[str] = Header(None)):
    try:
        user_id, username = verify_token(authorization)
        mem_client.delete(memory_id=memory_id)
        return {"status": "success", "message": "Memory erased."}
        
    except Exception as e:
        print(f"DEBUG: Error deleting memory: {e}")
        return {"status": "error", "message": str(e)}
    

@router.get("/conversations")
async def get_conversations(authorization: Optional[str] = Header(None)): #telling that look only in header(header can be none too), it can be or can not be present. if not, dont crash.
    """Fetches a list of all chat histories for the logged-in user."""
    user_id, username = verify_token(authorization)
    conversations = db.get_conversations(user_id)
    return {"conversations": conversations}

@router.post("/conversations")
async def create_conversation(authorization: Optional[str] = Header(None)):
    """Creates a brand new, empty chat thread."""
    user_id, username = verify_token(authorization)
    conv_id = db.create_conversation(user_id)
    if conv_id:
        return {"conversation_id": conv_id, "message": "Conversation created"}
    raise HTTPException(status_code=500, detail="Failed to create conversation")
    
@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, authorization: Optional[str] = Header(None)):
    """Loads all the messages inside a specific chat thread."""
    user_id, username = verify_token(authorization)
    conversation = db.get_conversation(conversation_id, user_id)
    if conversation:
        return conversation
    raise HTTPException(status_code=404, detail="Conversation not found")

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, authorization: Optional[str] = Header(None)):
    """Deletes a specific chat thread from the database."""
    user_id, username = verify_token(authorization)
    success = db.delete_conversation(conversation_id, user_id)
    if success:
        return {"message": "Conversation deleted"}
    raise HTTPException(status_code=500, detail="Failed to delete conversation")

@router.post("/chat")
async def chat_endpoint(request: ChatRequest, authorization: Optional[str] = Header(None)):
    user_id, username = verify_token(authorization)
    user_query = request.message
    conv_id = request.conversation_id 

    if not conv_id:
        conv_id = db.create_conversation(user_id)
        if not conv_id:
            raise HTTPException(status_code=500, detail="Failed to create conversation")

    #  Memory Retrieval: Ask Mem0 if it knows anything relevant about this user
    memories = []
    try:
        search_results = mem_client.search(query=user_query, user_id=user_id, limit=3)
        if search_results:
            raw = search_results if isinstance(search_results, list) else search_results.get("results", [])
            for mem in raw:
                score = mem.get('score', 0)
                if score > 0.7:
                    text = mem.get('memory', str(mem))[:200]
                    memories.append(text)
    except Exception as e:
        print(f"DEBUG: Memory Error: {e}")

    # 1. Grab the user's toggles from the request (default to True if empty)
    tools_allowed = request.tools_allowed if hasattr(request, 'tools_allowed') and request.tools_allowed else {}
    kb_allowed = tools_allowed.get("search_knowledge_base", True)
    web_allowed = tools_allowed.get("web_search", True)

    # 2. Dynamically build the tool instructions list
    tool_instructions = []
    
    if kb_allowed:
        tool_instructions.append("- 'search_knowledge_base' — use this for ANY question about personal info, uploaded documents, or what you know about the user.")
    
    if web_allowed:
        tool_instructions.append("- 'web_search' — use ONLY for current events, news, real-time information, weather, prices.")
    
    # We will assume time is always available since it doesn't cost tokens/API limits
    tool_instructions.append("- 'get_current_time' — returns current date and time.")

    # 3. Construct the base prompt based on what is active
    if kb_allowed or web_allowed:
        base_prompt = (
            "You are a helpful assistant.\n"
            "You have the following tools available:\n"
            f"{chr(10).join(tool_instructions)}\n" # chr(10) is just a clean way to write '\n' inside an f-string
            "STRICT RULES:\n"
            "- Call each tool AT MOST ONCE per user question.\n"
            "- Once you have tool results, answer immediately. Do NOT search again."
        )
    else:
        # If the user turned EVERYTHING off, explicitly tell the AI to behave like a normal chatbot
        base_prompt = (
            "You are a helpful assistant.\n"
            "The user has explicitly DISABLED all external search tools and document retrieval.\n"
            "You must answer strictly based on your internal knowledge and the conversation history."
        )

    if memories:
        SYSTEM_PROMPT = f"{base_prompt}\n\nCONTEXT FROM PREVIOUS CONVERSATIONS:\n{chr(10).join('- ' + m for m in memories)}\n\nUse this context ONLY if relevant. DO NOT repeat old answers."
    else:
        SYSTEM_PROMPT = base_prompt

    input_messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_query)]
    
    # 5. Execution: Run the LangGraph AI (with the Secret Tunnel for Data Privacy!)
    try:
        final_state = agent_app.invoke(
            {"messages": input_messages},
            config={"configurable": {"user_id": user_id}} #this allows us to pass variables , we can use this in any tool without giving this info to llm.
        )
        
        ai_response = final_state["messages"][-1].content
        citations = extract_citations(final_state["messages"])
        quality = grade_answer(user_query, ai_response)
        print(f"DEBUG: Citations found: {len(citations)}, Quality: {quality}")

       
        try:
            db.add_message_to_conversation(conv_id, user_id, user_query, ai_response)
        except Exception as conv_err:
            print(f"DEBUG: Failed to save to SQL: {conv_err}")
        
        # Save Long-Term Memory (to Mem0/Qdrant for future AI context)
        try:
            mem_client.add(user_id=user_id, messages=[{"role": "user", "content": user_query}, {"role": "assistant", "content": ai_response}])
        except Exception as mem_err:
            print(f"DEBUG: Failed to save to Mem0: {mem_err}")
        
        return {"response": ai_response,
                 "conversation_id": conv_id,
                 "citations": citations,        # e.g. [{"url": "...", "snippet": "..."}]
                "quality": quality}
        
    except Exception as e:
        error_msg = str(e)
        if "rate_limit" in error_msg.lower() or "413" in error_msg:
            return {"response": "I am thinking too hard. Please wait 30 seconds."}
        return {"response": f"System Error: {error_msg}"}
    

@router.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, authorization: Optional[str] = Header(None)):
    user_id, username = verify_token(authorization)
    user_query = request.message
    conv_id = request.conversation_id

    # Create new conversation if none provided
    if not conv_id:
        conv_id = db.create_conversation(user_id)
        if not conv_id:
            raise HTTPException(status_code=500, detail="Failed to create conversation")

    memories = []
    try:
        search_results = mem_client.search(query=user_query, user_id=user_id, limit=3)
        if search_results:
            raw = search_results if isinstance(search_results, list) else search_results.get("results", [])
            for mem in raw:
                if mem.get('score', 0) > 0.7:
                    memories.append(mem.get('memory', str(mem))[:200])
    except Exception as e:
        print(f"DEBUG: Memory Error: {e}")

    tools_allowed = request.tools_allowed if hasattr(request, 'tools_allowed') and request.tools_allowed else {}
    kb_allowed = tools_allowed.get("search_knowledge_base", True)
    web_allowed = tools_allowed.get("web_search", True)

    tool_instructions = []
    
    if kb_allowed:
        tool_instructions.append("- 'search_knowledge_base' — use this for ANY question about personal info, uploaded documents, or what you know about the user.")
    
    if web_allowed:
        tool_instructions.append("- 'web_search' — use ONLY for current events, news, real-time information, weather, prices.")

    tool_instructions.append("- 'get_current_time' — returns current date and time.")

    if kb_allowed or web_allowed:
        base_prompt = (
            "You are a helpful assistant.\n"
            "You have the following tools available:\n"
            f"{chr(10).join(tool_instructions)}\n"
            "STRICT RULES:\n"
            "- Call each tool AT MOST ONCE per user question.\n"
            "- If you need to use a tool, DO NOT generate any conversational text before calling it. Output ONLY the tool call.\n"
            "- For highly volatile real-time data, ALWAYS use the web_search tool. Do NOT guess.\n"
            "- Once you have tool results, answer the user's question directly and concisely. Add a maximum of 1 or 2 lines of extra context. DO NOT write long essays or paragraphs.\n"
            "- CRITICAL: DO NOT output any raw 'SOURCE_URL::' tags or raw URLs in your response text. The system extracts those automatically in the background.\n"
            "- CRITICAL: When tool results are present in the conversation, you MUST base your answer ONLY on those results. NEVER override tool results with, your training knowledge. If a tool says X, your answer must say X."
            "- SUGGESTIONS: At the very end of your response, ALWAYS add exactly 1 suggested follow-up question. Format it EXACTLY like this (NO spaces inside the asterisks):\n\n"
            "**Try searching for:**\n"
            "[Your Question Here]\n"
        )
    else:
        base_prompt = (
            "You are a helpful assistant.\n"
            "The user has explicitly DISABLED all external search tools and document retrieval.\n"
            "You must answer strictly based on your internal knowledge and the conversation history."
        )


    SYSTEM_PROMPT = (
        f"{base_prompt}\n\nCONTEXT FROM PREVIOUS CONVERSATIONS:\n"
        + "\n".join("- " + m for m in memories) 
        + "\n\nUse this context ONLY if relevant. DO NOT repeat old answers."
        if memories else base_prompt
    )

    input_messages = [SystemMessage(content=SYSTEM_PROMPT)]
    if conv_id:
        try:
            conversation = db.get_conversation(conv_id, user_id)
            if conversation and "messages" in conversation:
                recent_messages = conversation["messages"][-10:]
                for msg in recent_messages:
                    if msg["role"] == "user":
                        input_messages.append(HumanMessage(content=msg["content"]))
                    elif msg["role"] == "assistant":
                        input_messages.append(AIMessage(content=msg["content"]))
        except Exception as e:
            print(f"DEBUG: Failed to load conversation history: {e}")

    input_messages.append(HumanMessage(content=user_query))

    # This is the generator function that generates SSE (Server-Sent Events)chunks
    async def generate():
        full_response = ""  # We accumulate the full response to save to DB after stream ends
        tool_outputs = {}
        try:
            tools_allowed = request.tools_allowed or {}
            target_file = getattr(request, 'target_file', 'all') or 'all'
            # astream_events fires events for EVERY node in the LangGraph
            async for event in agent_app.astream_events(
                {"messages": input_messages},
                config={
                    "configurable": {
                        "user_id": user_id,
                        "tools_allowed": tools_allowed,
                        "target_file": target_file
                    }
                },
                version="v2" 
            ):
                if event["event"] == "on_chain_start": #"on_chain_start" comes when a node start executing
                    node_name = event.get("name", "")

                    if node_name == "complexity_detector":
                        yield f"data: {json.dumps({'status': 'analyzing'})}\n\n"

                    elif node_name == "planner":
                        yield f"data: {json.dumps({'status': 'Thinking'})}\n\n"

                    elif node_name == "executor":
                        # Read which tool is about to run from the event's input state
                        input_data = event.get("data", {}).get("input", {})
                        plan = input_data.get("plan", [])
                        step_index = input_data.get("current_step_index", 0)

                        if plan and step_index < len(plan):
                            tool_name = plan[step_index].get("tool", "")
                            purpose = plan[step_index].get("purpose", "")
                            status_map = {
                                "search_knowledge_base": "searching_kb",
                                "web_search":            "searching_web",
                                "academic_research":     "researching_papers"
                            }
                            status = status_map.get(tool_name, "executing")
                            yield f"data: {json.dumps({'status': status, 'purpose': purpose})}\n\n"

                    elif node_name == "synthesizer":
                        yield f"data: {json.dumps({'status': 'synthesizing'})}\n\n"
                        
                # fires the moment a tool starts — before results come back ──
                if event["event"] == "on_tool_start":
                    full_response = ""
                    tool_name = event.get("name", "")

                    if tool_name == "web_search":
                        yield f"data: {json.dumps({'status': 'searching_web'})}\n\n" #its like yield sends what happend and then pauses until something happen again

                    elif tool_name == "search_knowledge_base":
                        yield f"data: {json.dumps({'status': 'searching_kb'})}\n\n"

                    elif tool_name == "get_current_time":
                        yield f"data: {json.dumps({'status': 'getting_time'})}\n\n"

                if event["event"] == "on_tool_end":
                    tool_name = event.get("name", "")
                    tool_output = event["data"].get("output", "")
                    if hasattr(tool_output, 'content'):
                        tool_output = tool_output.content
                    tool_outputs[tool_name] = tool_output 


                # on_chat_model_stream fires for every token the LLM generates,each event is type of dicteg.{"event": "on_chat_model_stream","data": {content,...}}
                if event["event"] == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node", "")
                    if node_name not in ("agent", "synthesizer"):
                        continue
                    chunk = event["data"]["chunk"]

                    # Skip tool-call chunks (when model is deciding to call a tool)
                    # tool_call_chunks are intermediate reasoning, not the final answer
                    if chunk.tool_call_chunks:
                        continue

                    # Only stream actual text tokens
                    if chunk.content:
                        token = chunk.content
                        full_response += token
                        yield f"data: {json.dumps({'token': token, 'conv_id': conv_id})}\n\n"


            citations = extract_citations(tool_outputs.get('web_search', ''))

            quality = grade_answer(user_query, full_response)

            yield f"data: {json.dumps({'done': True, 'conv_id': conv_id, 'citations': citations, 'quality': quality})}\n\n"

            try:
                db.add_message_to_conversation(conv_id, user_id, user_query, full_response)
            except Exception as e:
                print(f"DEBUG: Failed to save to SQL: {e}")

            try:
                mem_client.add(
                    user_id=user_id,
                    messages=[
                        {"role": "user", "content": user_query},
                        {"role": "assistant", "content": full_response}
                    ]
                )
            except Exception as e:
                print(f"DEBUG: Failed to save to Mem0: {e}")

        except Exception as e:
            # Send error to frontend so it doesn't hang forever
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",   # Disables nginx buffering (important for streaming)
            "Cache-Control": "no-cache", # Prevents browser from caching the stream
        }
    )