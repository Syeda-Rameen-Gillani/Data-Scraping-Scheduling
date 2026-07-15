import os
import csv
import json
from pathlib import Path

JSON_DIR = Path("json")

def is_missing(value):
    if value is None:
        return True

    if isinstance(value, str):
        return value.strip() == ""

    if isinstance(value, list):
        return len(value) == 0

    return False


FIELD_WEIGHTS = {
    # ==========================
    # Critical
    # ==========================
    "Case Number": 10,
    "Case Title": 10,
    "Judge Name(s)": 10,
    "Court Name": 9,
    "Decision/Order Date": 9,
    "head_note": 9,
    "Short Summary of the Case": 9,
    "final_decision": 9,

    # ==========================
    # High
    # ==========================
    "key_legal_issues": 8,
    "precedents_cited": 8,
    "Cited Case Laws": 8,
    "articles_sections_cited": 8,
    "statutes_mentioned": 8,
    "legal_keywords": 8,

    # ==========================
    # Medium
    # ==========================
    "Applicant and Respondents": 6,
    "petitioner_appellant": 6,
    "respondent": 6,
    "Type of Petition or Application": 6,
    "case_category": 6,
    "disposition_type": 6,
    "Legal Sections Involved": 6,
    "Advocate Names for each party": 6,
    "bench_strength": 6,
    "Hearing Date": 6,
    "citation_year": 6,
    "citation_journal": 6,
    "citation_page_number": 6,

    # ==========================
    # Infrastructure
    # ==========================
    "reference_url": 5,
}

ALWAYS_NULL_FIELDS = {
    "Page count",
    "case_filing_date",
    "trial_court_decision_date",
    "appellate_court_decision_date",
    "supreme_court_decision_date",
}

OPTIONAL_FIELDS = {
    "source_url"
}

def judge_needs_reextract(name):
    if not name:
        return True

    n = name.strip().lower()

    invalid = {
        "judge",
        "judges",
        "justice",
        "honourable judge",
        "Hon'ble Judge"
        "The Judge"
        "Presiding Judge"
        "unknown",
        "n/a",
    }

    if n in invalid:
        return True

    # single generic word
    if len(n.split()) == 1 and n in {"judge", "justice"}:
        return True

    return False

def analyze_file(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    priority_score = 0
    missing_fields = []

    total_weight = sum(FIELD_WEIGHTS.values())
    present_weight = total_weight

    for field, weight in FIELD_WEIGHTS.items():
        if field in ALWAYS_NULL_FIELDS:
            continue

        if field in OPTIONAL_FIELDS:
            continue


        value = data.get(field)

        if field == "Judge Name(s)":
            missing = is_missing(value) or judge_needs_reextract(value)
        else:
            missing = is_missing(value)

        if missing:
            priority_score += weight
            present_weight -= weight
            missing_fields.append(field)

    completeness = round((present_weight / total_weight) * 100, 2)

    if priority_score >= 35:
        priority = "HIGH"

    elif priority_score >= 15:
        priority = "MEDIUM"

    else:
        priority = "LOW"

    return {
        "file": json_path.name,
        "priority_score": priority_score,
        "priority": priority,
        "completeness": completeness,
        "missing_count": len(missing_fields),
        "missing_fields": missing_fields,
    }


def main():
    results = []

    for json_file in JSON_DIR.glob("*.json"):
        result = analyze_file(json_file)
        results.append(result)

    results.sort(
        key=lambda x: (
            x["priority_score"],
            x["missing_count"]
        ),
        reverse=True
    )
    with open("metadata_validation_report.csv", "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)

        writer.writerow([
            "File",
            "Priority Score",
            "Completeness (%)",
            "Missing Count",
            "Missing Fields"
        ])

        for result in results:
            writer.writerow([
                result["file"],
                result["priority_score"],
                result["completeness"],
                result["missing_count"],
                "; ".join(result["missing_fields"])
            ])
    print(f"Analyzed {len(results)} files.\n")
    
    for result in results:
        print("=" * 60)
        print(f"File: {result['file']}")
        print(f"Priority Score : {result['priority_score']}")
        print(f"Missing Fields : {result['missing_count']}")
        print(f"Completeness   : {result['completeness']}%")

        if result["missing_fields"]:
            print("\nMissing Fields:")
            for field in result["missing_fields"]:
                print(f"  - {field}")
        else:
            print("\n✓ Metadata Complete")

        print("=" * 60)
        print()
    

if __name__ == "__main__":
    main()