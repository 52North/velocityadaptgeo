import json


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

