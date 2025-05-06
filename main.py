# main.py
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import json

# --- Configuration ---
QUEUE_FILE = Path("queue.json")
DATA_FOLDER = Path("data")
DATA_FOLDER.mkdir(exist_ok=True)

# --- Helper functions ---
def load_queue():
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return []

def save_queue(queue):
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))

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
    body = await request.json()
    return {"response": f"Rubi got it: {body.get('text')}"}

@app.post("/note")
async def add_note(item: NoteItem):
    queue = load_queue()
    entry = {
        "type": "note",
        "text": item.text,
        "user": item.user,
        "timestamp": datetime.utcnow().isoformat()
    }
    queue.append(entry)
    save_queue(queue)
    return {"status": "queued", "id": len(queue)-1}

@app.post("/link")
async def add_link(item: LinkItem):
    queue = load_queue()
    entry = {
        "type": "link",
        "url": item.url,
        "user": item.user,
        "timestamp": datetime.utcnow().isoformat()
    }
    queue.append(entry)
    save_queue(queue)
    return {"status": "queued", "id": len(queue)-1}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user: str = None):
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
