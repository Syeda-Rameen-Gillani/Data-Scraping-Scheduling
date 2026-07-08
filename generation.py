"""
generation.py

Turns retrieval results into an LLM answer: builds the context blocks and
citation list from Weaviate result objects (new 33-field schema), then
prompts the local Ollama model for a grounded answer.
"""

import os

import ollama

LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")

PROMPT_TEMPLATE = """
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
{question}

Answer:
"""


def build_context_and_citations(objects):
    """
    Given a list of Weaviate result objects (each with .properties), build
    the numbered context blocks for the prompt and a de-duplicated citation
    list, using the new schema's field names.
    """
    context_blocks = []
    citations = []
    seen_files = set()

    for i, obj in enumerate(objects, start=1):
        props = obj.properties

        context_blocks.append(
            f"[Source {i}]\n"
            f"Case: {props.get('case_title')} ({props.get('case_number')})\n"
            f"{props.get('text')}"
        )

        file_name = props.get("file_name")
        if file_name and file_name not in seen_files:
            seen_files.add(file_name)
            citations.append({
                "file_name": file_name,
                "case_title": props.get("case_title"),
                "case_number": props.get("case_number"),
                "reference_url": props.get("reference_url"),
            })

    context = "\n\n".join(context_blocks)
    return context, citations


def generate_answer(question: str, objects) -> dict:
    """
    Full generation step: builds context/citations from retrieved objects,
    prompts the LLM, and returns {"answer": ..., "citations": ...}.
    Returns a "no information" response if there were no retrieved objects.
    """
    if not objects:
        return {
            "answer": "No relevant information found in the dataset.",
            "citations": [],
        }

    context, citations = build_context_and_citations(objects)

    prompt = PROMPT_TEMPLATE.format(context=context, question=question)

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )

    return {
        "answer": response["message"]["content"],
        "citations": citations,
    }