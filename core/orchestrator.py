import json
import sys
import re
import os
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from core.config_manager import load_config
from core.config import DB_PATH
from core.ingest_knowledge import run_incremental_sync
from core.spreadsheet_tool import (
    query_project_spreadsheets,
    is_quantitative_query,
    extract_project_name,
    extract_sheet_preview,
    search_sheet_for_terms,
)

from langchain_community.embeddings import HuggingFaceEmbeddings

# Instantiate embeddings once globally to prevent first-token latency
_embeddings_instance = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': False}
)

# Global query cache tracked for auto-search chaining
LATEST_USER_QUERY = ""


JARVIS_SYSTEM_PROMPT = """You are Jarvis QS, an expert Quantity Surveying AI assistant.

CRITICAL IDENTITY & ANTI-HALLUCINATION RULES:
1. STRICT VERIFICATION: Only answer using exact content returned by the `search_knowledge_vault` tool. Do not infer, embellish, or extrapolate project names, specifications, or figures that are not explicitly present in the retrieved documents.
2. TOOL-FIRST WORKFLOW: If the user asks about projects, specifications, contracts, or details, call `search_knowledge_vault` FIRST. Do not answer from memory or general knowledge.
3. HONEST NEGATIVE RESPONSE: If the tool returns no results or empty content, explicitly state that no relevant projects were found in the database. Do not fabricate project names or substitute unrelated numbers.
4. QUANTITATIVE VS CONCEPTUAL DUAL-ROUTING:
   - For quantitative queries (tonnages, reinforcement schedules, pricing, steel quantities, unit rates, costing, takeoff data), target specific spreadsheets. The system will auto-route to spreadsheet querying when quantitative keywords are detected.
   - For specifications, standards, codes of practice, workmanship descriptions, or contract terms, use vector search.

SUGGEST RETRIEVAL QUESTIONS:
At the absolute end of your response, always output exactly three bullet points starting with 'Suggested next questions:' suggesting related technical or retrieval queries the user might run next to verify or extract further information from the Knowledge Vault.
Keep each suggestion under 5 words.
"""

def format_final_response(content: str) -> str:
    if not content:
        return "I'm ready to help with your Quantity Surveying tasks. How can I assist you?"

    # If content is only a thinking block with no text after it, prompt or clean it
    if "<thinking>" in content and "</thinking>" in content:
        parts = content.split("</thinking>")
        thinking_part = parts[0].replace("<thinking>", "").strip()
        answer_part = parts[1].strip() if len(parts) > 1 else ""

        if answer_part:
            return f"*Thought Process: {thinking_part}*\n\n{answer_part}"
        else:
            # Model stopped after thinking block - use thought summary as fallback answer
            return f"{thinking_part}\n\n*How can I assist you further with this project?*"

    return content


def parse_raw_json_tool_calls(response: AIMessage) -> AIMessage:
    """Intercepts plaintext JSON tool calls from local models and sanitizes nested schema-style arguments."""
    # If native tool calls already exist, pass through unchanged
    if getattr(response, "tool_calls", None) and len(response.tool_calls) > 0:
        return response

    content = response.content or ""

    # Pattern 1: trailing JSON at end of response
    json_match = re.search(
        r'(\{\s*"name"\s*:\s*"search_knowledge_vault".*?\})\s*$',
        content,
        re.DOTALL,
    )
    # Pattern 2: markdown ```json {...} ``` blocks
    if not json_match:
        json_match = re.search(
            r'```(?:json)?\s*(\{.*?"name".*?search_knowledge_vault.*?\})\s*```',
            content,
            re.DOTALL,
        )
    # Pattern 3: bare JSON dict anywhere in content
    if not json_match:
        json_match = re.search(
            r'(\{\s*"name"\s*:\s*".*?"\s*,\s*"args"\s*:\s*\{.*?\}\s*\})',
            content,
            re.DOTALL,
        )

    if json_match:
        json_str = json_match.group(1).strip()
        try:
            parsed = json.loads(json_str)
            tool_name = parsed.get("name")
            tool_args = parsed.get("args") or parsed.get("arguments") or {}

            # Fallback format handling (e.g. if args is serialized as string)
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {"query": tool_args}

            if tool_name:
                response.tool_calls = [{
                    "name": tool_name,
                    "args": tool_args,
                    "id": "call_fallback_001",
                }]
        except Exception:
            pass

    return response


def _run_vector_search(query: str, db_path_resolved: str) -> str:
    try:
        if not os.path.exists(db_path_resolved):
            return f"Error: FAISS path '{db_path_resolved}' does not exist. Please run ingestion first."

        # Load config to determine Cloud/OmniRoute mode limits
        cfg = load_config()
        provider = cfg.get("provider_type", "omniroute")

        # Load FAISS index using cached embeddings
        vectorstore = FAISS.load_local(db_path_resolved, _embeddings_instance, allow_dangerous_deserialization=True)
        
        # Dynamic Retrieval k
        k = 150 if provider == "omniroute" else 40
        retriever = vectorstore.as_retriever(search_kwargs={"k": k})
        results = retriever.invoke(query)

        if not results:
            return f"No relevant information found in the Knowledge Vault for '{query}'."

        formatted_context = []
        for i, doc in enumerate(results):
            # Safely extract metadata dictionary
            meta = doc.metadata if isinstance(doc.metadata, dict) else {}
            source = meta.get("filename") or meta.get("source") or "Unknown Document"

            # Remove Retrieval Truncation in Cloud/OmniRoute mode
            if provider == "omniroute":
                content_snippet = doc.page_content
            else:
                content_snippet = doc.page_content[:1000]

            header = f"--- Result {i+1} (Source: {source}) ---"
            formatted_context.append(f"{header}\n{content_snippet}")

        return "\n\n".join(formatted_context)

    except Exception as e:
        error_msg = str(e)
        return f"❌ [SYSTEM OUTAGE]: The vector database or embedding API connection failed. Error details: {error_msg}. INSTRUCTION: Tell the user exactly this: 'My connection to the Knowledge Vault is temporarily unavailable due to a service outage. Please retry in a few moments.'"


# ── LangGraph Agent Tools ────────────────────────────────────────────────────

@tool
def search_knowledge_vault(query: str) -> str:
    """
    Searches the Knowledge Vault vector database for specifications, drawings indexes, 
    contracts, codes of practice, and architectural/civil standard requirements.
    """
    cfg = load_config()
    db_path_resolved = cfg.get("db_path", DB_PATH)
    return f"[VAULT SEARCH RESULTS]\n" + _run_vector_search(query, db_path_resolved)


@tool
def search_spreadsheet_data(query: str) -> str:
    """
    Searches project spreadsheets for quantitative/tabular data (steel tonnages, 
    reinforcement items, BoQ schedules, rates, costings, concrete volumes).
    Automatically routes the lookup to the appropriate project directory.
    """
    project_name = extract_project_name(query)
    if not project_name:
        return "Error: Could not identify which project you are asking about. Please specify the project name."

    # Parse search terms from the query
    clean_query = re.sub(r'[^\w\s]', ' ', query).lower()
    search_terms = []
    
    # Check for quantitative keywords to use as search terms
    for word in clean_query.split():
        if word in QUANTITATIVE_KEYWORDS or len(word) > 4:
            if word not in ["project", "excel", "sheet", "spreadsheet", "data", project_name.lower()]:
                search_terms.append(word)

    if not search_terms:
         search_terms = ["steel", "tonnage", "pricing", "reinforcement", "concrete"]

    # Deduplicate while preserving order
    seen = set()
    search_terms = [x for x in search_terms if not (x in seen or seen.add(x))]

    return query_project_spreadsheets(project_name, search_terms)


@tool
def sync_knowledge_vault() -> str:
    """
    Scans the inbox folder for new projects and PDF documents, processes them, 
    and updates the vector database. Automatically runs a follow-up vector search 
    to retrieve new additions instantly inside this transaction loop.
    """
    try:
        import contextlib
        import io
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            result = run_incremental_sync()
        sync_log = result
        
        # Immediately invoke a vector search with the user's latest query parameters
        cfg = load_config()
        db_path_resolved = cfg.get("db_path", DB_PATH)
        query = LATEST_USER_QUERY or "latest updates"
        search_result = _run_vector_search(query, db_path_resolved)
        
        return (
            f"{sync_log}\n\n"
            f"=== Auto-Search Chaining Results for '{query}' ===\n"
            f"{search_result}\n\n"
            f"[SYSTEM NOTICE]: Synchronization load complete and search has been executed. "
            f"Do not call sync_knowledge_vault or search_knowledge_vault again in this interaction loop. "
            f"Formulate your final response to the user's query now based on these results."
        )
    except Exception as e:
        return f"ERROR syncing workspace: {str(e)}"



def get_dynamic_agent():
    """Builds a fresh LangGraph agent from user_config.json on every invocation."""
    cfg = load_config()
    base_url = cfg.get("base_url", "https://omni.dhanrickeviota.com/v1")
    api_key = cfg.get("api_key", "sk-9e731d7385077d7e-2cbf0c-598b3170")
    ollama_base_url = cfg.get("ollama_base_url", "http://localhost:11434/v1")
    primary_model = cfg.get("primary_model", "jarvis_brain")
    fallback_model = cfg.get("fallback_model", "qwen2.5-coder:3b-instruct-q4_K_M")
    provider = cfg.get("provider_type", "omniroute")

    # ── Base LLMs ──────────────────────────────────────────────────────────────
    primary_llm = ChatOpenAI(
        model=primary_model,
        openai_api_base=base_url,
        openai_api_key=api_key or "sk-9e731d7385077d7e-2cbf0c-598b3170",
        temperature=0.1,
        max_retries=1,
        request_timeout=120 if provider == "omniroute" else 30,
        max_tokens=8192 if provider == "omniroute" else None,
    )
    fallback_llm = ChatOpenAI(
        model=fallback_model,
        openai_api_base=ollama_base_url,
        openai_api_key="ollama",
        temperature=0.1,
        request_timeout=30,
    )

    # Tools are now defined globally at the module level
    tools = [search_knowledge_vault, search_spreadsheet_data, sync_knowledge_vault]

    # ── STEP 1: Bind tools to each model individually ──────────────────────────
    primary_with_tools = primary_llm.bind_tools(tools)
    fallback_with_tools = fallback_llm.bind_tools(tools)

    # ── STEP 2: Combine into resilient fallback chain ──────────────────────────
    llm_with_fallbacks = primary_with_tools.with_fallbacks([fallback_with_tools])

    # ── STEP 3: Pipe through plaintext JSON tool-call interceptor ─────────────
    final_runnable = llm_with_fallbacks | parse_raw_json_tool_calls

    # ── STEP 4: Wrap in a callable selector so create_react_agent accepts it ──
    def model_callable(state, config=None):
        return final_runnable

    # ── STEP 5: Build and return the LangGraph agent ───────────────────────────
    return create_react_agent(
        model_callable,
        tools,
        prompt=JARVIS_SYSTEM_PROMPT,
    )


def run_cli() -> None:
    cfg = load_config()
    print("==============================================")
    print("🤖 JARVIS QS - RESILIENT ORCHESTRATOR ONLINE")
    print(f"Primary Brain  : {cfg.get('primary_model')}")
    print(f"Fallback Brain : {cfg.get('fallback_model')} (Local)")
    print("==============================================")
    agent = get_dynamic_agent()
    while True:
        try:
            query = input("\nUser > ").strip()
            if not query:
                continue
            if query.lower() in ["exit", "quit"]:
                break
            print("\nJarvis > Thinking...\n")
            global LATEST_USER_QUERY
            LATEST_USER_QUERY = query
            response = agent.invoke({"messages": [("user", query)]})
            messages = response.get("messages", [])
            if messages:
                print(f"Jarvis > {format_final_response(messages[-1].content)}")
            else:
                print("Jarvis > No response generated.")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    run_cli()
