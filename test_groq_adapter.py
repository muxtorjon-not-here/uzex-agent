"""Checks the Groq message translation without a network call."""
import agent

contents = [
    {"role": "user", "parts": [{"text": "savol"}]},
    {"role": "model", "parts": [{"functionCall": {"name": "run_sql", "args": {"sql": "select 1"}}, "thoughtSignature": "x"}]},
    {"role": "user", "parts": [{"functionResponse": {"name": "run_sql", "response": {"result": {"rows": [[1]]}}}}]},
    {"role": "model", "parts": [{"text": "javob"}]},
    {"role": "user", "parts": [{"text": "VERIFIER"}]},
]
m = agent._groq_messages(contents)
print([x["role"] for x in m])
assert [x["role"] for x in m] == ["system", "user", "assistant", "tool", "assistant", "user"]
assert m[3]["tool_call_id"] == m[2]["tool_calls"][0]["id"]
back = agent._from_groq({"choices": [{"message": {"content": None, "tool_calls": [{"function": {"name": "run_sql", "arguments": "{\"sql\": \"select 1\"}"}}]}}]})
assert back["parts"][0]["functionCall"]["args"]["sql"] == "select 1"
print(agent._groq_tools()[0]["function"]["parameters"])
print("adapter OK; models:", agent.MODELS)
