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

JARVIS_SYSTEM_PROMPT = """You are Jarvis QS, an expert Quantity Surveying AI assistant.

CRITICAL IDENTITY & ANTI-HALLUCINATION RULES:
1. STRICT VERIFICATION: Only answer using exact content returned by the `search_knowledge_vault` tool. Do not infer, embellish, or extrapolate project names, specifications, or figures that are not explicitly present in the retrieved documents.
2. TOOL-FIRST WORKFLOW: If the user asks about projects, specifications, contracts, or details, call `search_knowledge_vault` FIRST. Do not answer from memory or general knowledge.
3. HONEST NEGATIVE RESPONSE: If the tool returns no results or empty content, explicitly state that no relevant projects were found in the database. Do not fabricate project names or substitute unrelated projects.
4. ERROR HANDLING: If the database search tool fails or returns an error (e.g. "Error executing search: ..."), you must output exactly: "The database search could not be completed due to a connection error."
5. RESPONSE FORMATTING: You may think inside a brief <thinking>...</thinking> block, but you MUST ALWAYS write your final response to the user AFTER </thinking>. NEVER end your message without providing a direct response to the user.

TOOL USAGE GUIDELINES:
- `search_knowledge_vault`: Use to answer questions about past construction projects, specifications, BoQs, and rates.
- `sync_knowledge_vault`: Use this immediately if the user mentions adding new files, updating old spreadsheets, adding variations to past projects, or asks you to "sync" or "learn" the workspace.

At the very end of your final response, you MUST provide 2 to 3 short, relevant follow-up actions or questions the user might want to ask next based on your findings.
Format them strictly on a new line using this exact syntax:
[SUGGESTIONS: Short Action 1 | Short Action 2 | Short Action 3]
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
            r'(\{\s*"name"\s*:\s*"search_knowledge_vault".*?\})',
            content,
            re.DOTALL,
        )

    if json_match:
        try:
            tool_data = json.loads(json_match.group(1))
            tool_name = tool_data.get("name")
            raw_args = tool_data.get("arguments", tool_data.get("args", {}))

            # Sanitize: unwrap schema-style {"type": "string", "value": "X"} -> "X"
            sanitized_args = {}
            if isinstance(raw_args, dict):
                for key, val in raw_args.items():
                    if isinstance(val, dict) and "value" in val:
                        sanitized_args[key] = str(val["value"])
                    else:
                        sanitized_args[key] = val
            elif isinstance(raw_args, str):
                sanitized_args = {"query": raw_args}

            if tool_name in ["search_knowledge_vault", "sync_knowledge_vault"]:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": tool_name,
                        "args": sanitized_args,
                        "id": "call_fallback_001",
                    }],
                )
        except Exception:
            pass

    return response


def get_dynamic_agent():
    """Builds a fresh LangGraph agent from user_config.json on every invocation."""
    cfg = load_config()
    base_url = cfg.get("base_url", "https://omni.dhanrickeviota.com/v1")
    api_key = cfg.get("api_key", "sk-9e731d7385077d7e-2cbf0c-598b3170")
    ollama_base_url = cfg.get("ollama_base_url", "http://localhost:11434/v1")
    primary_model = cfg.get("primary_model", "jarvis_brain")
    fallback_model = cfg.get("fallback_model", "qwen2.5-coder:3b-instruct-q4_K_M")
    # ── Decoupled Embeddings ──────────────────────────────────────────────────
    # Langchain OpenAIEmbeddings replaced with local HuggingFaceEmbeddings inside the tool

    # ── Base LLMs ──────────────────────────────────────────────────────────────
    primary_llm = ChatOpenAI(
        model=primary_model,
        openai_api_base=base_url,
        openai_api_key=api_key or "sk-9e731d7385077d7e-2cbf0c-598b3170",
        temperature=0.1,
        max_retries=1,
        request_timeout=30,
    )
    fallback_llm = ChatOpenAI(
        model=fallback_model,
        openai_api_base=ollama_base_url,
        openai_api_key="ollama",
        temperature=0.1,
        request_timeout=30,
    )

    # ── Knowledge Vault Tool ───────────────────────────────────────────────────
    db_path_resolved = cfg.get("db_path", DB_PATH)

    @tool
    def search_knowledge_vault(query: str) -> str:
        """
        Searches the Jarvis QS Knowledge Vault (PDFs, Excel files, Specs).
        Use this tool whenever you need to look up standard drawings, building codes,
        contract clauses, or project-specific documents.
        """
        try:
            if not os.path.exists(db_path_resolved):
                return f"Error: FAISS path '{db_path_resolved}' does not exist. Please run ingestion first."

            # Load FAISS index
            from langchain_community.embeddings import HuggingFaceEmbeddings
            from langchain_community.vectorstores import FAISS
            embeddings = HuggingFaceEmbeddings(
                model_name="all-MiniLM-L6-v2",
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': False}
            )
            vectorstore = FAISS.load_local(db_path_resolved, embeddings, allow_dangerous_deserialization=True)
            retriever = vectorstore.as_retriever(search_kwargs={"k": 15})
            results = retriever.invoke(query)

            if not results:
                return "No relevant information found in the Knowledge Vault."

            formatted_context = []
            for i, doc in enumerate(results):
                # Safely extract metadata dictionary
                meta = doc.metadata if isinstance(doc.metadata, dict) else {}
                source = meta.get("filename") or meta.get("source") or "Unknown Document"

                content_snippet = doc.page_content[:1000]
                header = f"--- Result {i+1} (Source: {source}) ---"
                formatted_context.append(f"{header}\n{content_snippet}")

            return "\n\n".join(formatted_context)

        except Exception as e:
            error_msg = str(e)
            # Return a distinct prompt injection to the LLM so it knows it's a system outage, not an empty search
            return f"❌ [SYSTEM OUTAGE]: The vector database or embedding API connection failed. Error details: {error_msg}. INSTRUCTION: Tell the user exactly this: 'My connection to the Knowledge Vault is temporarily down. I cannot search your projects right now.'"

    @tool
    def sync_knowledge_vault() -> str:
        """
        Triggers an incremental sync of the local workspace.
        Call this tool whenever the user states they have added a NEW project,
        added ADDITIONAL files to an old project, or UPDATED/modified an existing spreadsheet or document.
        """
        try:
            import contextlib
            import io
            f = io.StringIO()
            with contextlib.redirect_stdout(f):
                result = run_incremental_sync()
            return result
        except Exception as e:
            return f"ERROR syncing workspace: {str(e)}"

    tools = [search_knowledge_vault, sync_knowledge_vault]

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
