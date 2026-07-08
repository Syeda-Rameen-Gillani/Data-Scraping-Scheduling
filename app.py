import os

from fastapi import FastAPI, Query
from dotenv import load_dotenv

from retrieval import retrieve
from generation import generate_answer
from classification import classify_query, should_answer

load_dotenv()

app = FastAPI()

DECLINE_MESSAGES = {
    "other": (
        "This looks like a legal question, but outside the Sindh High Court "
        "case law covered by this dataset. I can't answer it from what I have."
    ),
    "irrelevant": (
        "This assistant only answers questions about Sindh High Court case "
        "law available in this dataset."
    ),
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chat")
def chat(q: str = Query(..., description="Your question about the case law dataset")):
    label = classify_query(q)

    if not should_answer(label):
        return {
            "query": q,
            "classification": label,
            "answer": DECLINE_MESSAGES[label],
            "citations": [],
        }

    results = retrieve(q)
    response = generate_answer(q, results.objects)

    return {
        "query": q,
        "classification": label,
        **response,
    }