import pytest
from app.ocr import build_extraction
from tests.eval.dataset import OCR_EVAL_CASES

# Thresholds
MIN_AVG_DATE_COVERAGE = 0.8
MIN_AVG_ITEM_COVERAGE = 0.8

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
