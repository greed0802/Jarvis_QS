import os
import sys
import json
import warnings
import io
import time

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def main():
    if "--daemon" in sys.argv:
        # Load agent and warm up embeddings
        from core.orchestrator import get_dynamic_agent
        agent = get_dynamic_agent()
        
        # Flush the ready indicator
        print(json.dumps({"type": "info", "content": "Jarvis Daemon Ready"}), flush=True)

        def stream_content(event_type, full_text):
            if not full_text:
                return
            chunk_size = 12
            for i in range(0, len(full_text), chunk_size):
                chunk = full_text[i:i+chunk_size]
                print(json.dumps({"type": event_type, "content": chunk}), flush=True)
                time.sleep(0.01)

        while True:
            line = sys.stdin.readline()
            if not line:
                break
            
            line_str = line.strip()
            if not line_str:
                continue
                
            try:
                data = json.loads(line_str)
                user_prompt = data.get("prompt", "").strip()
                chat_history = data.get("history", [])
                
                # Update query tracker
                import core.orchestrator as orch
                orch.LATEST_USER_QUERY = user_prompt
                
                formatted_messages = []
                for msg in chat_history:
                    role = msg.get("role")
                    content = msg.get("content")
                    if role == "user":
                        formatted_messages.append(("user", content))
                    elif role == "assistant":
                        formatted_messages.append(("assistant", content))
                    elif role == "system":
                        formatted_messages.append(("system", content))

                formatted_messages.append(("user", user_prompt))

                events = agent.stream({"messages": formatted_messages}, stream_mode="updates")
                for event in events:
                    for node_name, node_update in event.items():
                        messages = node_update.get("messages", [])
                        for msg in messages:
                            if node_name == "agent":
                                if getattr(msg, "tool_calls", None):
                                    for tc in msg.tool_calls:
                                        print(json.dumps({
                                            "type": "tool_start",
                                            "name": tc.get("name"),
                                            "input": str(tc.get("args"))
                                        }), flush=True)

                                content = msg.content or ""
                                if content:
                                    if "<thinking>" in content and "</thinking>" in content:
                                        parts = content.split("</thinking>")
                                        thinking_part = parts[0].replace("<thinking>", "").strip()
                                        answer_part = parts[1].strip() if len(parts) > 1 else ""
                                        if thinking_part:
                                            stream_content("thought", thinking_part)
                                        if answer_part:
                                            stream_content("final_chunk", answer_part)
                                    elif "<thinking>" in content:
                                        thinking_part = content.replace("<thinking>", "").strip()
                                        stream_content("thought", thinking_part)
                                    else:
                                        stream_content("final_chunk", content)

                            elif node_name == "tools":
                                tool_name = getattr(msg, "name", "tool")
                                tool_content = msg.content or ""

                                chunk_count = tool_content.count("--- Result") or tool_content.count("Source:") or len(tool_content.split("\n\n"))
                                if chunk_count > 0 and "Result" in tool_content:
                                    summary = f"Retrieved {chunk_count} matching chunks"
                                elif "Successfully synced" in tool_content or "sync" in tool_content.lower():
                                    summary = "Sync complete"
                                else:
                                    summary = f"Processed {len(tool_content)} chars of data"

                                print(json.dumps({
                                    "type": "tool_end",
                                    "name": tool_name,
                                    "summary": summary
                                }), flush=True)

                print(json.dumps({"type": "done"}), flush=True)
            except Exception as e:
                print(json.dumps({"type": "error", "content": str(e)}), flush=True)
                print(json.dumps({"type": "done"}), flush=True)
        return

    if len(sys.argv) < 2:
        print(json.dumps({"type": "error", "content": "No prompt provided."}), flush=True)
        sys.exit(1)

    user_prompt = sys.argv[1].strip()

    chat_history = []
    if len(sys.argv) >= 3 and sys.argv[2].strip():
        try:
            chat_history = json.loads(sys.argv[2])
        except Exception:
            pass

    try:
        from core.orchestrator import get_dynamic_agent
        agent = get_dynamic_agent()

        def stream_content(event_type, full_text):
            if not full_text:
                return
            chunk_size = 12
            for i in range(0, len(full_text), chunk_size):
                chunk = full_text[i:i+chunk_size]
                print(json.dumps({"type": event_type, "content": chunk}), flush=True)
                time.sleep(0.01)

        formatted_messages = []
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user":
                formatted_messages.append(("user", content))
            elif role == "assistant":
                formatted_messages.append(("assistant", content))
            elif role == "system":
                formatted_messages.append(("system", content))

        formatted_messages.append(("user", user_prompt))

        # Capture latest user query parameter for auto-search chaining
        import core.orchestrator as orch
        orch.LATEST_USER_QUERY = user_prompt

        events = agent.stream({"messages": formatted_messages}, stream_mode="updates")
        for event in events:
            for node_name, node_update in event.items():
                messages = node_update.get("messages", [])
                for msg in messages:
                    if node_name == "agent":
                        if getattr(msg, "tool_calls", None):
                            for tc in msg.tool_calls:
                                print(json.dumps({
                                    "type": "tool_start",
                                    "name": tc.get("name"),
                                    "input": str(tc.get("args"))
                                }), flush=True)

                        content = msg.content or ""
                        if content:
                            if "<thinking>" in content and "</thinking>" in content:
                                parts = content.split("</thinking>")
                                thinking_part = parts[0].replace("<thinking>", "").strip()
                                answer_part = parts[1].strip() if len(parts) > 1 else ""
                                if thinking_part:
                                    stream_content("thought", thinking_part)
                                if answer_part:
                                    stream_content("final_chunk", answer_part)
                            elif "<thinking>" in content:
                                thinking_part = content.replace("<thinking>", "").strip()
                                stream_content("thought", thinking_part)
                            else:
                                stream_content("final_chunk", content)

                    elif node_name == "tools":
                        tool_name = getattr(msg, "name", "tool")
                        tool_content = msg.content or ""

                        chunk_count = tool_content.count("--- Result") or tool_content.count("Source:") or len(tool_content.split("\n\n"))
                        if chunk_count > 0 and "Result" in tool_content:
                            summary = f"Retrieved {chunk_count} matching chunks"
                        elif "Successfully synced" in tool_content or "sync" in tool_content.lower():
                            summary = "Sync complete"
                        else:
                            summary = f"Processed {len(tool_content)} chars of data"

                        print(json.dumps({
                            "type": "tool_end",
                            "name": tool_name,
                            "summary": summary
                        }), flush=True)

    except Exception as exc:
        print(json.dumps({"type": "error", "content": str(exc)}), flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

