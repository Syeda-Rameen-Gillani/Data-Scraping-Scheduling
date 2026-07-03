import os

from fastapi import FastAPI, Query
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
import ollama
import re

from weaviate.classes.query import Filter
from weaviate_client import get_client

load_dotenv()

app = FastAPI()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")
TOP_K = int(os.getenv("TOP_K", "5"))
WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

embed_model = SentenceTransformer(EMBEDDING_MODEL)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/chat")
def chat(q: str = Query(..., description="Your question about the case law dataset")):
    client = get_client()
    WEAVIATE_COLLECTION = os.getenv("WEAVIATE_COLLECTION", "CaseChunk")

    # Detect case numbers like 68/2013
    case_match = re.search(r"\d+/\d{4}", q)

    if case_match:
        case_id = case_match.group()
        print(f"Case number detected: {case_id}")

        # Exact metadata lookup
        results = collection.query.fetch_objects(
            filters=Filter.by_property("case_no").like(f"*{case_id}*")
        )
        results.objects.sort(
            key=lambda obj: obj.properties.get("chunk_index", 0)
        )

    else:
        # Semantic search
        query_vector = embed_model.encode(q).tolist()

        results = collection.query.near_vector(
            near_vector=query_vector,
            limit=TOP_K,
        )

    client.close()

    if not results.objects:
        return {
            "query": q,
            "answer": "No relevant information found in the dataset.",
            "citations": [],
        }

    context_blocks = []
    citations = []
    seen_cases = set()

    for i, obj in enumerate(results.objects, start=1):
        props = obj.properties

        print(props.keys())
        context_blocks.append(
            f"[Source {i}]\n"
            f"Case No: {props.get('case_no')}\n"
            f"{props.get('text')}"
        )

        case_code = props.get("case_code")

        if case_code not in seen_cases:
            seen_cases.add(case_code)

            citations.append(
            {
                "case_code": case_code,
                "case_no": props.get("case_no"),
                "citation": props.get("citation"),
                "pdf_url": props.get("pdf_url"),
            }
        )
        

    context = "\n\n".join(context_blocks)
    
    prompt = f"""
You are a legal research assistant.

Answer ONLY using the information contained in the retrieved source excerpts.

If multiple source excerpts belong to the same case, combine them into one coherent answer instead of treating each excerpt independently.

When the user asks "What happened in this case?" or asks for a summary, provide:

1. Background facts
2. Main legal issue
3. Court's reasoning (if available)
4. Final decision or relief granted (if available)

Do NOT quote long passages unless necessary.
Do NOT answer using only one source if multiple excerpts are available.
Do NOT invent facts.

If the answer is not present in the sources, reply exactly:

"I don't have enough information to answer that."

At the end of your answer, cite the relevant source numbers, for example:
Sources: [Source 2], [Source 5]

Sources:
{context}

Question:
{q}

Answer:
"""
    

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    answer_text = response["message"]["content"]

    return {
        "query": q,
        "answer": answer_text,
        "citations": citations,
    }