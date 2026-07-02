"""SOT-1470 D2: extraction output schema versioning."""

from app import schemas
from app.schemas import (
    EXTRACTION_SCHEMA_VERSION,
    DocumentExtraction,
    InfoExtractDraft,
)


def test_document_extraction_defaults_to_current_version():
    doc = DocumentExtraction(raw_text="お知らせ")
    assert doc.schema_version == EXTRACTION_SCHEMA_VERSION


def test_blank_schema_version_is_normalized_to_current():
    doc = DocumentExtraction(raw_text="x", schema_version="   ")
    assert doc.schema_version == EXTRACTION_SCHEMA_VERSION


def test_explicit_version_is_preserved_for_compat_checks():
    doc = DocumentExtraction(raw_text="x", schema_version="0.9.0")
    # A stale/older version is preserved so consumers can detect a mismatch.
    assert doc.schema_version == "0.9.0"
    assert doc.schema_version != EXTRACTION_SCHEMA_VERSION


def test_info_extract_draft_carries_version():
    draft = InfoExtractDraft(title="t", info_type="notice", content="c")
    assert draft.schema_version == EXTRACTION_SCHEMA_VERSION


def test_version_constant_is_nonempty_string():
    assert isinstance(schemas.EXTRACTION_SCHEMA_VERSION, str)
    assert schemas.EXTRACTION_SCHEMA_VERSION
