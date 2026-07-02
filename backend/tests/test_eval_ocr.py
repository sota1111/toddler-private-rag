import pytest
from app.ocr import build_extraction
from tests.eval.dataset import OCR_EVAL_CASES

# Thresholds
MIN_AVG_DATE_COVERAGE = 0.8
MIN_AVG_ITEM_COVERAGE = 0.8
# SOT-1471: precision (no false positives) and F1 gates in addition to coverage (recall).
MIN_AVG_DATE_PRECISION = 0.8
MIN_AVG_ITEM_PRECISION = 0.8
MIN_AVG_DATE_F1 = 0.8
MIN_AVG_ITEM_F1 = 0.8


def _matches(a, b):
    """Substring match in either direction (robust to partial date/item spans)."""
    return a in b or b in a


def calculate_precision(expected, detected):
    """Fraction of detected values that correspond to an expected value.

    Precision penalises false positives (spurious detections). When nothing was
    detected there are no false positives, so precision is 1.0 (recall/coverage
    separately captures the miss).
    """
    if not detected:
        return 1.0
    hits = sum(1 for det in detected if any(_matches(det, exp) for exp in expected))
    return hits / len(detected)


def f1_score(precision, recall):
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def calculate_coverage(expected, detected):
    if not expected:
        return 1.0
    
    hits = 0
    for exp in expected:
        # For dates, exact match or substring match
        if any(exp in det or det in exp for det in detected):
            hits += 1
            
    return hits / len(expected)

def calculate_item_coverage(expected, detected):
    if not expected:
        return 1.0
    
    hits = 0
    for exp in expected:
        # For items, check if expected string appears in any detected item
        if any(exp in det for det in detected):
            hits += 1
            
    return hits / len(expected)

@pytest.mark.parametrize("case", OCR_EVAL_CASES)
def test_ocr_individual_cases(case):
    result = build_extraction(case["raw_text"])
    
    date_cov = calculate_coverage(case["expected_dates"], result.detected_dates)
    item_cov = calculate_item_coverage(case["expected_items"], result.detected_items)
    
    print(f"\nCase: {case['id']}")
    print(f"  Detected Dates: {result.detected_dates}")
    print(f"  Detected Items: {result.detected_items}")
    print(f"  Date Coverage: {date_cov:.2f}")
    print(f"  Item Coverage: {item_cov:.2f}")
    
    # Per-case check (allowing some slack but ensuring it's not zero if expected)
    if case["expected_dates"]:
        assert date_cov > 0, f"No dates detected for {case['id']}"
    if case["expected_items"]:
        assert item_cov > 0, f"No items detected for {case['id']}"

def test_ocr_aggregate_scores():
    date_scores = []
    item_scores = []
    
    for case in OCR_EVAL_CASES:
        result = build_extraction(case["raw_text"])
        date_scores.append(calculate_coverage(case["expected_dates"], result.detected_dates))
        item_scores.append(calculate_item_coverage(case["expected_items"], result.detected_items))
        
    avg_date_cov = sum(date_scores) / len(date_scores)
    avg_item_cov = sum(item_scores) / len(item_scores)
    
    print(f"\nAverage Date Coverage: {avg_date_cov:.2f}")
    print(f"Average Item Coverage: {avg_item_cov:.2f}")
    
    assert avg_date_cov >= MIN_AVG_DATE_COVERAGE
    assert avg_item_cov >= MIN_AVG_ITEM_COVERAGE


def test_ocr_precision_and_f1():
    """SOT-1471: gate precision (no false positives) and F1 alongside coverage."""
    date_precisions = []
    item_precisions = []
    date_f1s = []
    item_f1s = []

    for case in OCR_EVAL_CASES:
        result = build_extraction(case["raw_text"])

        d_recall = calculate_coverage(case["expected_dates"], result.detected_dates)
        i_recall = calculate_item_coverage(case["expected_items"], result.detected_items)
        d_prec = calculate_precision(case["expected_dates"], result.detected_dates)
        i_prec = calculate_precision(case["expected_items"], result.detected_items)

        date_precisions.append(d_prec)
        item_precisions.append(i_prec)
        date_f1s.append(f1_score(d_prec, d_recall))
        item_f1s.append(f1_score(i_prec, i_recall))

    avg_date_prec = sum(date_precisions) / len(date_precisions)
    avg_item_prec = sum(item_precisions) / len(item_precisions)
    avg_date_f1 = sum(date_f1s) / len(date_f1s)
    avg_item_f1 = sum(item_f1s) / len(item_f1s)

    print(f"\nAverage Date Precision: {avg_date_prec:.2f}")
    print(f"Average Item Precision: {avg_item_prec:.2f}")
    print(f"Average Date F1: {avg_date_f1:.2f}")
    print(f"Average Item F1: {avg_item_f1:.2f}")

    assert avg_date_prec >= MIN_AVG_DATE_PRECISION
    assert avg_item_prec >= MIN_AVG_ITEM_PRECISION
    assert avg_date_f1 >= MIN_AVG_DATE_F1
    assert avg_item_f1 >= MIN_AVG_ITEM_F1
