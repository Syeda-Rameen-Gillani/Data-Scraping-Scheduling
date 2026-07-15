import os

from fastapi import FastAPI, Query
from dotenv import load_dotenv

from generation import generate_answer

load_dotenv()

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chat")
def chat(q: str = Query(...)):
    response = generate_answer(q)

    return {
        "query": q,
        **response,
    }