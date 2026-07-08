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

    for item in EVAL_SET:
        predicted_label = classify_query(item["question"])
        predicted_should_answer = should_answer(predicted_label)
        expected_should_answer = (item["expected_label"] == "relevant")

        is_correct = predicted_should_answer == expected_should_answer
        if is_correct:
            correct += 1
        elif expected_should_answer is False and predicted_should_answer is True:
            false_positives.append((item["question"], predicted_label))
        elif expected_should_answer is True and predicted_should_answer is False:
            false_negatives.append((item["question"], predicted_label))

        details.append({
            "question": item["question"],
            "expected_label": item["expected_label"],
            "predicted_label": predicted_label,
            "correct": is_correct,
        })

    n = len(EVAL_SET)
    accuracy = correct / n if n else 0.0

    if verbose:
        print(f"\n=== Query Classification Evaluation ===")
        print(f"Questions evaluated: {n}")
        print(f"Accuracy: {accuracy:.1%}  ({correct}/{n})")
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
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "details": details,
    }


if __name__ == "__main__":
    evaluate_classifier()