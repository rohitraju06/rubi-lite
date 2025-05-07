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

# --- Configuration ---
QUEUE_FILE = Path("queue.json")
DATA_FOLDER = Path("data")
DATA_FOLDER.mkdir(exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_API", "http://localhost:11434")

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
        return data.get("response", "[No reply from model]")
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
        user = body.get("user")

        if not text:
            return JSONResponse(status_code=400, content={"error": "Missing 'text' in request body"})

        print(f"Received message from {user or 'anonymous'}: {text}")

        response_text = query_ollama(text)
        return {"response": response_text}

    except Exception as e:
        print("Error handling /message:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@app.post("/note")
async def add_note(item: NoteItem):
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
async def add_link(item: LinkItem):
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
async def upload_file(file: UploadFile = File(...), user: str = None):
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
            "user": user,
            "timestamp": datetime.utcnow().isoformat()
        }
        queue.append(entry)
        save_queue(queue)
        return {"status": "queued", "id": len(queue)-1}
    except Exception as e:
        print("Error handling /upload:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
