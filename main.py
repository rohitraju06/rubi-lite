# main.py
from fastapi import FastAPI, Request
from pydantic import BaseModel

app = FastAPI()

class Message(BaseModel):
    text: str

@app.get("/")
def root():
    return {"message": "Hello world! From FastAPI running on Uvicorn with Gunicorn. Using Python 3.10"}

@app.post("/message")
def message(msg: Message):
    return {"response": f"Rubi got it: '{msg.text}'"}