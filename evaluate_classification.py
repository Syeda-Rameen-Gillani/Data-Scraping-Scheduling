"""
evaluate_classification.py

Evaluates the query classifier (classification.py) against every question
in eval_set.py, using expected_label (relevant/irrelevant) as ground truth.
Reports accuracy plus precision/recall for correctly rejecting off-corpus
questions, and prints every misclassification for failure-mode analysis --
per Task 3's requirement to understand, not just claim, failure modes.
"""

from eval_set import EVAL_SET
from classification import classify_query, should_answer


def evaluate_classifier(verbose: bool = True) -> dict:
    correct = 0
    false_positives = []  # expected irrelevant, classifier said relevant (answered when it shouldn't have)
    false_negatives = []  # expected relevant, classifier said other/irrelevant (refused when it shouldn't have)
    details = []
    tp = 0   
    tn = 0   
    fp = 0   
    fn = 0   


    for item in EVAL_SET:
        predicted_label = classify_query(item["question"])
        predicted_should_answer = should_answer(predicted_label)
        expected_should_answer = (item["expected_label"] == "relevant")

        if expected_should_answer and predicted_should_answer:
            tp += 1
            correct += 1

        elif expected_should_answer and not predicted_should_answer:
            fn += 1
            false_negatives.append((item["question"], predicted_label))

        elif not expected_should_answer and predicted_should_answer:
            fp += 1
            false_positives.append((item["question"], predicted_label))

        else:
            tn += 1
            correct += 1

        details.append({
            "question": item["question"],
            "expected_label": item["expected_label"],
            "predicted_label": predicted_label,
            "correct": predicted_should_answer == expected_should_answer,
        })

    n = len(EVAL_SET)
    accuracy = correct / n if n else 0.0
    rejection_rate = tn / (tn + fp) if (tn + fp) else 0.0
    false_negative_rate = fn / (tp + fn) if (tp + fn) else 0.0

    if verbose:
        print(f"\n=== Query Classification Evaluation ===")
        print(f"Questions evaluated: {n}")
        print(f"Accuracy: {accuracy:.1%}  ({correct}/{n})")
        print(f"Irrelevant Query Rejection Rate: {rejection_rate:.1%}")
        print(f"Relevant Query False Negative Rate: {false_negative_rate:.1%}")
        print("\nConfusion Matrix")
        print("----------------------------------------")
        print(f"{'':20s}Pred Relevant   Pred Irrelevant")
        print(f"Actual Relevant     {tp:3d}              {fn:3d}")
        print(f"Actual Irrelevant   {fp:3d}              {tn:3d}")
        print()
        print()
        for d in details:
            status = "OK  " if d["correct"] else "FAIL"
            print(f"[{status}] expected={d['expected_label']:10s} predicted={d['predicted_label']:10s}  {d['question']}")
        print()
        if false_positives:
            print("False positives (should have been rejected, but classifier answered):")
            for q, label in false_positives:
                print(f"  - [{label}] {q}")
        if false_negatives:
            print("False negatives (should have been answered, but classifier rejected):")
            for q, label in false_negatives:
                print(f"  - [{label}] {q}")
        print()

    return {
    "n": n,
    "accuracy": accuracy,
    "rejection_rate": rejection_rate,
    "false_negative_rate": false_negative_rate,
    "confusion_matrix": {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    },
    "false_positives": false_positives,
    "false_negatives": false_negatives,
    "details": details,
    }


if __name__ == "__main__":
    results = evaluate_classifier()

    from pathlib import Path
    import json
    from datetime import datetimeprint(f"Relevant Query False Negative Rate: {false_negative_rate:.1%}")
 
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output = {
        "timestamp": timestamp,
        "questions": results["n"],
        "relevant_queries": (
            results["confusion_matrix"]["tp"]
            + results["confusion_matrix"]["fn"]
        ),
        "irrelevant_queries": (
            results["confusion_matrix"]["tn"]
            + results["confusion_matrix"]["fp"]
        ),
        "accuracy": results["accuracy"],
        "irrelevant_query_rejection_rate": results["rejection_rate"],
        "relevant_query_false_positive_rate": results["false_positive_rate"],
        "confusion_matrix": {
            "true_positive": results["confusion_matrix"]["tp"],
            "false_positive": results["confusion_matrix"]["fp"],
            "true_negative": results["confusion_matrix"]["tn"],
            "false_negative": results["confusion_matrix"]["fn"],
        },
        "false_positives": results["false_positives"],
        "false_negatives": results["false_negatives"],
        "details": results["details"],
    }

    output_dir = Path("evaluation")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f"classification_results_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved classification results to {output_file}")