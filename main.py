# main.py
import os
from dotenv import load_dotenv
load_dotenv()
print("DEBUG: Loaded OLLAMA_API =", os.getenv("OLLAMA_API"))
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import json
import requests  # add this import at the top with the others
from fastapi import Depends
from auth import router as auth_router, require_user


# --- Configuration ---
QUEUE_FILE = Path("queue.json")
DATA_FOLDER = Path("data")
DATA_FOLDER.mkdir(exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_API", "http://localhost:11434")
RAG_URL    = os.getenv("RAG_API", "http://localhost:8001")

# --- Helper functions ---
def load_queue():
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return []

def save_queue(queue):
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))

def query_ollama(prompt):
    try:
        payload = {
            "model": "phi",
            "prompt": prompt,
            "stream": False
        }

        print(f"Querying Ollama at: {OLLAMA_URL}")
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        response.raise_for_status()
        data = response.json()
        print("Ollama responded with:", data)
        return data.get("response").strip() or "Rubi chooses to ignore your query."
    except Exception as e:
        print("Error querying Ollama:", e)
        return "[Error querying LLM]"

# --- API Setup ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this later to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

# --- Data models ---
class NoteItem(BaseModel):
    text: str
    user: str = None

class LinkItem(BaseModel):
    url: str
    user: str = None

# --- Endpoints ---
@app.post("/message")
async def handle_message(request: Request):
    try:
        body = await request.json()
        text = body.get("text")

        if not text:
            return JSONResponse(status_code=400, content={"error": "Missing 'text' in request body"})

        print(f"Received message: {text}")

        # 1) classify intent
        classify_prompt = (
            "You are an assistant that extracts user intent from a message. "
            "If the user is asking to save a note, respond with INTENT:save_note. "
            "If saving a link, respond with INTENT:save_link. "
            "If retrieving, respond with INTENT:retrieve. "
            "Otherwise respond with INTENT:general.\n"
            f"Message: {text}\n"
            "Reply with only the intent."
        )
        intent = query_ollama(classify_prompt).strip()

        if intent == "INTENT:save_note":
            # forward to local note-queue
            resp = requests.post(f"http://localhost:8000/note", json={"text": text})
            return {"response": "Saved note.", "detail": resp.json()}

        elif intent == "INTENT:save_link":
            resp = requests.post(f"http://localhost:8000/link", json={"url": text})
            return {"response": "Saved link.", "detail": resp.json()}

        elif intent == "INTENT:retrieve":
            # call your RAG backend
            resp = requests.post(f"{RAG_URL}/query", json={"prompt": text})
            results = resp.json().get("results", [])
            # optionally summarize
            summary_prompt = "Summarize these results:\n" + "\n".join([d["text"] for d in results])
            summary = query_ollama(summary_prompt)
            return {"response": summary, "results": results}

        # fallback: general chat
        response_text = query_ollama(text)
        return {"response": response_text}

    except Exception as e:
        print("Error handling /message:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@app.post("/note")
async def add_note(item: NoteItem, user: dict = Depends(require_user)):
    try:
        text = item.text
        user = item.user
        if not text or not text.strip():
            return JSONResponse(status_code=400, content={"error": "Missing 'text' in request body"})
        queue = load_queue()
        entry = {
            "type": "note",
            "text": text,
            "user": user,
            "timestamp": datetime.utcnow().isoformat()
        }
        queue.append(entry)
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}
    except Exception as e:
        print("Error handling /note:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@app.post("/link")
async def add_link(item: LinkItem, user: dict = Depends(require_user)):
    try:
        url = item.url
        user = item.user
        if not url or not url.strip():
            return JSONResponse(status_code=400, content={"error": "Missing 'url' in request body"})
        queue = load_queue()
        entry = {
            "type": "link",
            "url": url,
            "user": user,
            "timestamp": datetime.utcnow().isoformat()
        }
        queue.append(entry)
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}
    except Exception as e:
        print("Error handling /link:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(require_user)):
    try:
        if not file:
            return JSONResponse(status_code=400, content={"error": "Missing file in request"})
        contents = await file.read()
        file_path = DATA_FOLDER / file.filename
        file_path.write_bytes(contents)

        queue = load_queue()
        entry = {
            "type": "upload",
            "filename": file.filename,
            "path": str(file_path),
            "user": user.get("user"),
            "timestamp": datetime.utcnow().isoformat()
        }
        queue.append(entry)
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}
    except Exception as e:
        print("Error handling /upload:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
