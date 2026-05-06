from typing import TypedDict, Annotated, Optional
from langgraph.graph import MessagesState
import operator

class PlanStep(TypedDict):
    step_id:  int
    tool:     str   
    query:    str     
    purpose:  str   

class ArgusState(MessagesState): #this class is inherting from MessageState class
    original_query:    str                       
    is_complex:        bool                     
    plan:              list[PlanStep]             # ordered steps the planner generates
    current_step_index: int                    
    
    # Annotated with operator.add so results ACCUMULATE across node calls
    # instead of overwriting each other
    step_results: Annotated[list[dict], operator.add]