import os
import pytest
from app.rag.providers import FakeEmbeddingProvider, FakeLLMProvider
from app.rag.service import RagService
from tests.eval.dataset import RAG_CORPUS, RAG_EVAL_CASES

# Thresholds
MIN_TOP_SOURCE_ACCURACY = 0.8
MIN_AVG_KEYWORD_HIT_RATE = 0.8

class FakeAttachment:
    def __init__(self, original_filename, ocr_text):
        self.original_filename = original_filename
        self.ocr_text = ocr_text

class FakeInfo:
    def __init__(self, id, title, content, attachments=None):
        self.id = id
        self.title = title
        self.content = content
        self.attachments = [FakeAttachment(a["original_filename"], a["ocr_text"]) for a in (attachments or [])]

@pytest.fixture(scope="module")
def rag_service():
    # Force deterministic providers
    os.environ["EMBEDDING_PROVIDER"] = "fake"
    os.environ["LLM_PROVIDER"] = "fake"
    
    service = RagService(
        embedding_provider=FakeEmbeddingProvider(),
        llm_provider=FakeLLMProvider()
    )
    
    corpus = [FakeInfo(**item) for item in RAG_CORPUS]
    service.build_index(corpus)
    return service

@pytest.mark.parametrize("case", RAG_EVAL_CASES)
def test_rag_individual_cases(rag_service, case):
    answer = rag_service.answer(case["query"], top_k=case["top_k"])
    
    # Check top source
    top_source_id = answer.sources[0].info_id if answer.sources else None
    is_correct_source = top_source_id == case["expected_top_info_id"]
    
    # Check keywords in answer
    # FakeLLMProvider typically echoes context, so keywords should be present
    hit_count = 0
    for kw in case["expected_keywords"]:
        if kw in answer.answer:
            hit_count += 1
    
    hit_rate = hit_count / len(case["expected_keywords"]) if case["expected_keywords"] else 1.0
    
    print(f"\nCase: {case['id']}")
    print(f"  Query: {case['query']}")
    print(f"  Top Source ID: {top_source_id} (Expected: {case['expected_top_info_id']})")
    print(f"  Keyword Hit Rate: {hit_rate:.2f}")
    
    assert is_correct_source, f"Wrong source for {case['id']}: expected {case['expected_top_info_id']}, got {top_source_id}"
    assert hit_rate >= 0.5, f"Low keyword hit rate for {case['id']}: {hit_rate:.2f}"

def test_rag_aggregate_scores(rag_service):
    correct_sources = 0
    hit_rates = []
    
    for case in RAG_EVAL_CASES:
        answer = rag_service.answer(case["query"], top_k=case["top_k"])
        
        top_source_id = answer.sources[0].info_id if answer.sources else None
        if top_source_id == case["expected_top_info_id"]:
            correct_sources += 1
            
        hit_count = 0
        for kw in case["expected_keywords"]:
            if kw in answer.answer:
                hit_count += 1
        hit_rates.append(hit_count / len(case["expected_keywords"]) if case["expected_keywords"] else 1.0)
        
    accuracy = correct_sources / len(RAG_EVAL_CASES)
    avg_hit_rate = sum(hit_rates) / len(hit_rates)
    
    print(f"\nTop Source Accuracy: {accuracy:.2f}")
    print(f"Average Keyword Hit Rate: {avg_hit_rate:.2f}")
    
    assert accuracy >= MIN_TOP_SOURCE_ACCURACY
    assert avg_hit_rate >= MIN_AVG_KEYWORD_HIT_RATE
