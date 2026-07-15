from retrieval import (
    retrieve as retrieve_semantic,
    retrieve_keyword,
    retrieve_hybrid
)

from classification import classify_query, should_answer


def search_judgments(
    query: str,
    strategy="hybrid",
    top_k=5,
    court=None,
    year=None,
    judge=None,
):

    label = classify_query(query)

    if not should_answer(label):
        return {
            "status": "not_applicable",
            "message":
            "This query does not appear related to Sindh High Court judgments."
        }


    if strategy == "keyword":
        results = retrieve_keyword(query, top_k=top_k)

    elif strategy == "semantic":
        results = retrieve_semantic(query, top_k=top_k)

    else:
        results = retrieve_hybrid(query, top_k=top_k)


    judgments = []

    for obj in results.objects:

        p = obj.properties

        judgments.append({
            "case_number": p.get("case_number"),
            "case_title": p.get("case_title"),
            "citation": p.get("citation"),
            "judge": p.get("judge"),
            "decision_date": p.get("decision_date"),
            "snippet": p.get("text","")[:500],
            "score": getattr(obj,"score",None),
            "source_url": p.get("source_url")
        })


    return judgments

tools = [
    {
        "function_declarations": [
            {
                "name": "search_judgments",
                "description": (
                    "Search Sindh High Court judgments by case number, "
                    "citation, case title, judge, statute, or natural "
                    "language legal query."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "The user's legal search query."
                        },
                        "strategy": {
                            "type": "STRING",
                            "enum": [
                                "keyword",
                                "semantic",
                                "hybrid"
                            ],
                            "description": "Retrieval strategy."
                        },
                        "top_k": {
                            "type": "INTEGER",
                            "description": "Maximum number of judgments."
                        },
                        "court": {
                            "type": "STRING",
                            "description": "Optional court filter."
                        },
                        "year": {
                            "type": "INTEGER",
                            "description": "Optional decision year filter."
                        },
                        "judge": {
                            "type": "STRING",
                            "description": "Optional judge filter."
                        }
                    },
                    "required": ["query"]
                }
            }
        ]
    }
]