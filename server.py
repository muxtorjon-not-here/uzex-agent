import os
import threading
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

load_dotenv()
import agent  # noqa: E402

app = FastAPI(title="UZEX Agent", docs_url=None, redoc_url=None)
PAGE = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
_cache = {}


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.get("/health")
def health():
    return {"ok": True, "v": 11}


@app.post("/api/ask")
async def ask(q: Ask):
    key = " ".join(q.question.split()).lower()
    if key in _cache:
        return _cache[key]
    res = await run_in_threadpool(agent.answer, q.question.strip())
    if res["status"] in ("verified", "no_data"):
        _cache[key] = res
    return res


def _keep_awake():
    """Render's free plan sleeps after 15 idle minutes; ping our public URL so judges never hit a cold start."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    while url:
        time.sleep(600)
        try:
            httpx.get(url + "/health", timeout=20)
        except httpx.HTTPError:
            pass


threading.Thread(target=_keep_awake, daemon=True).start()
