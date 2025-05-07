from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import json
from pathlib import Path
import threading
import time

# ---- CONFIG ----
EMBED_MODEL = 'all-MiniLM-L6-v2'
VECTOR_DIR = Path("data/vectors")
VECTOR_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = VECTOR_DIR / "faiss.index"
DOCS_FILE = VECTOR_DIR / "docs.json"

# ---- INITIALIZE FAISS & STORAGE ----
model = SentenceTransformer(EMBED_MODEL)
dim = model.get_sentence_embedding_dimension()

if INDEX_FILE.exists() and DOCS_FILE.exists():
    index = faiss.read_index(str(INDEX_FILE))
    with open(DOCS_FILE, "r") as f:
        docs_store = json.load(f)
else:
    index = faiss.IndexFlatL2(dim)
    docs_store = []
    faiss.write_index(index, str(INDEX_FILE))
    with open(DOCS_FILE, "w") as f:
        json.dump(docs_store, f)

router = APIRouter()

# ---- Helper: save state ----
def persist_index():
    faiss.write_index(index, str(INDEX_FILE))
    with open(DOCS_FILE, "w") as f:
        json.dump(docs_store, f)

# ---- Background worker for ingestion ----
def run_worker():
    def worker_loop():
        while True:
            # In a real setup, pull from a queue.json for unprocessed entries
            # For now, this is placeholder logic
            time.sleep(5)
    thread = threading.Thread(target=worker_loop, daemon=True)
    thread.start()

# ---- API Endpoints ----
@router.post("/add")
async def add_document(req: Request):
    data = await req.json()
    text = data.get("text")
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text'")
    emb = model.encode([text])[0]
    index.add(np.array([emb]))
    docs_store.append(text)
    persist_index()
    return {"status": "stored", "total": len(docs_store)}

@router.post("/query")
async def query_documents(req: Request):
    data = await req.json()
    query = data.get("text")
    if not query:
        raise HTTPException(status_code=400, detail="Missing 'text'")
    q_emb = model.encode([query])[0]
    distances, indices = index.search(np.array([q_emb]), k=10)
    results = [docs_store[i] for i in indices[0] if i < len(docs_store)]
    return {"results": results}
