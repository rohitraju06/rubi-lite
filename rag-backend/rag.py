from fastapi import FastAPI, Request
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, util
import json
import os
from pathlib import Path

app = FastAPI()

# Load embedding model
model = SentenceTransformer("all-MiniLM-L6-v2")

# Store for documents and vectors
DATA_PATH = Path("rag_memory.json")
if not DATA_PATH.exists():
    DATA_PATH.write_text("[]")

def load_memory():
    return json.loads(DATA_PATH.read_text())

def save_memory(data):
    DATA_PATH.write_text(json.dumps(data, indent=2))

# Pydantic model for queries
class Query(BaseModel):
    prompt: str

@app.post("/query")
async def query_rag(q: Query):
    memory = load_memory()
    if not memory:
        return {"response": "No memory available."}

    prompt_embedding = model.encode(q.prompt, convert_to_tensor=True)
    scored = [
        (util.cos_sim(prompt_embedding, model.encode(doc["text"], convert_to_tensor=True)).item(), doc)
        for doc in memory
    ]
    scored.sort(reverse=True)
    top = scored[:10]
    return {"results": [doc for score, doc in top]}

@app.post("/add")
async def add_doc(q: Query):
    memory = load_memory()
    memory.append({"text": q.prompt})
    save_memory(memory)
    return {"status": "added", "count": len(memory)}