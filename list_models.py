"""Lists Gemini models available to the key in .env, without printing the key."""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
key = os.environ.get("GEMINI_API_KEY", "").strip()
print("key length", len(key))
r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key}, timeout=30)
print("status", r.status_code)
if r.status_code != 200:
    print(r.text[:400])
else:
    for m in r.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m["name"]:
            print(m["name"])
