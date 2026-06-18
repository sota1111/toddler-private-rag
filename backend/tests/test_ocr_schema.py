import pytest
from pydantic import ValidationError
from app.schemas import DocumentExtraction
from app import ocr

def test_document_extraction_auto_derivation():
    """
    DocumentExtraction が raw_text から char_count, is_empty を正しく導出することを検証。
    """
    # 非空テキスト
    doc = DocumentExtraction(raw_text="Hello World")
    assert doc.char_count == 11
    assert doc.is_empty is False

    # 空文字
    doc = DocumentExtraction(raw_text="")
    assert doc.char_count == 0
    assert doc.is_empty is True

    # 空白のみ
    doc = DocumentExtraction(raw_text="   ")
    assert doc.char_count == 3
    assert doc.is_empty is True

def test_document_extraction_validation_error():
    """
    不正な型で ValidationError が発生することを検証。
    """
    with pytest.raises(ValidationError):
        # raw_text は str である必要がある
        DocumentExtraction(raw_text=123)

def test_ocr_build_extraction_detection():
    """
    ocr.build_extraction が日付と項目を期待どおり抽出することを検証。
    """
    text = """
    園だより 10月号
    発行日: 2023/10/25
    
    【持ち物】
    ・お弁当
    ・水筒
    
    【準備するもの】
    着替え
    タオル
    
    次回の予定: 令和5年11月1日
    12月24日 クリスマス会
    """
    doc = ocr.build_extraction(text)
    
    # 日付の抽出
    assert "2023/10/25" in doc.detected_dates
    assert "令和5年11月1日" in doc.detected_dates
    assert "12月24日" in doc.detected_dates
    
    # 項目の抽出
    assert "・お弁当" in doc.detected_items
    assert "・水筒" in doc.detected_items
    assert "着替え" in doc.detected_items
    assert "タオル" in doc.detected_items

def test_ocr_build_extraction_empty():
    """
    空入力に対する挙動を検証。
    """
    doc = ocr.build_extraction("")
    assert doc.raw_text == ""
    assert doc.char_count == 0
    assert doc.is_empty is True
    assert doc.detected_dates == []
    assert doc.detected_items == []
