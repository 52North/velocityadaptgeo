import json
from langchain_core.messages import ToolMessage


def all_tool_messages(messages):
    return [m for m in (messages or []) if isinstance(m, ToolMessage)]


def serialize_tool_messages(messages) -> str:
    tool_msgs = [m for m in (messages or []) if isinstance(m, ToolMessage)]
    packed = []
    for tm in tool_msgs:
        item = {"tool": getattr(tm, "name", None)}
        # Prefer structured artifacts if present
        art = getattr(tm, "artifact", None) or {}
        if isinstance(art, dict) and "structured_content" in art:
            item["structured_content"] = art["structured_content"]
        else:
            item["content"] = tm.content
        packed.append(item)

    return json.dumps(packed, ensure_ascii=False, indent=2)


def pretty_print_messages(messages):
    print("\n=== LangGraph Messages ===")

    for i, msg in enumerate(messages, start=1):
        print(f"\n--- Message {i} ---")
        print(f"Type: {msg.__class__.__name__}")

        if hasattr(msg, "content"):
            if isinstance(msg.content, (dict, list)):
                print("Content:")
                print(json.dumps(msg.content, indent=2))
            else:
                print(f"Content:\n{msg.content}")

        if getattr(msg, "tool_calls", None):
            print("\nTool Calls:")
            print(json.dumps(msg.tool_calls, indent=2))

        if getattr(msg, "response_metadata", None):
            print("\nMetadata:")
            print(json.dumps(msg.response_metadata, indent=2))

        if getattr(msg, "usage_metadata", None):
            print("\nUsage:")
            print(json.dumps(msg.usage_metadata, indent=2))

    print("\n==========================\n")

