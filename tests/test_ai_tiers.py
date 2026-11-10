"""Quality-first tiered AI use: model calls happen where they add accuracy, and nowhere else."""
import pytest

from vendorcheck import db, reader
from vendorcheck.reader import HybridReader

PAN_TEXT = "INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nPermanent Account Number Card\nAAACB1234C\nName\nBLUEHERONTRADINGPRIVATELIMTED"


class FakeLlm:
    def __init__(self, critical=None):
        self.text_calls, self.vision_read_calls, self.vision_critical_calls = [], [], []
        self.critical = critical or {}

    def read_text(self, pages, progress=None):
        self.text_calls.append(sorted(pages))
        n = next(iter(pages))
        return {"pages": [], "fields": [{"field": "legal_name", "value": "BLUE HERON TRADING PRIVATE LIMITED", "page": n, "doc_type": "pan_card", "snippet": ""}]}

    def vision_read(self, f, pages, progress=None):
        self.vision_read_calls.append(sorted(pages))
        n = min(pages)
        return {"pages": [{"page": n, "doc_type": "pan_card", "legible": True, "handwritten": True, "note": "read from the image"}],
                "fields": [{"field": "pan", "value": "AAACB1234C", "page": n, "doc_type": "pan_card", "snippet": ""}]}

    def vision_critical(self, f, pages, progress=None):
        self.vision_critical_calls.append(sorted(pages))
        return {str(n): self.critical for n in pages}


@pytest.fixture
def photo(tmp_path, monkeypatch):
    """One scanned page whose OCR text is PAN_TEXT, with a controllable OCR confidence."""
    p = tmp_path / "pan.png"
    p.write_bytes(b"\x89PNG fake")
    f = {"sha256": "a" * 64, "name": "pan.png", "mime": "image/png", "path": str(p)}
    state = {"score": 0.95, "alt": PAN_TEXT}

    def fake_ocr(file):
        reader.OCR_SCORES[file["sha256"]] = [state["score"]]
        return [PAN_TEXT]
    monkeypatch.setattr(reader, "ocr_pages", fake_ocr)
    monkeypatch.setattr(reader, "imagey_pages", lambda file, n: {1})
    monkeypatch.setattr(reader, "page_count", lambda file: 1)
    monkeypatch.setattr(reader, "ocr_pages_alt", lambda file, pages: {1: state["alt"]})
    return f, state


def test_tier2_scanned_names_are_cleaned_by_the_model(photo):
    f, _ = photo
    llm = FakeLlm()
    d = HybridReader(db.make_engine("sqlite://"), llm).read_document(f)
    name = next(x["value"] for x in d["fields"] if x["field"] == "legal_name")
    assert name == "BLUE HERON TRADING PRIVATE LIMITED"                    # OCR damage ("LIMTED", lost spaces) repaired
    assert llm.text_calls == [[1]] and llm.vision_read_calls == [] and "checked by text analysis" in d["via"]


def test_tier1_a_low_confidence_page_is_read_from_its_image(photo):
    f, state = photo
    state["score"] = 0.55                                                    # poor scan / handwriting
    llm = FakeLlm()
    d = HybridReader(db.make_engine("sqlite://"), llm).read_document(f)
    assert llm.vision_read_calls == [[1]] and "read from the image" in d["via"]
    assert any(p["handwritten"] for p in d["pages"])


def test_tier3_vision_breaks_a_tie_when_the_two_ocr_passes_disagree(photo):
    f, state = photo
    state["alt"] = PAN_TEXT.replace("AAACB1234C", "AAACB1284C")             # the second OCR pass read a different digit
    llm = FakeLlm(critical={"gstin": "", "pan": "AAACB1234C", "cin": "", "bank_account": "", "ifsc": ""})
    r = HybridReader(db.make_engine("sqlite://"), llm)
    second = r.read_critical(f)
    assert llm.vision_critical_calls == [[1]] and second["1"]["pan"] == "AAACB1234C"


def test_tier3_is_not_used_when_both_ocr_passes_agree(photo):
    f, _ = photo
    llm = FakeLlm()
    HybridReader(db.make_engine("sqlite://"), llm).read_critical(f)
    assert llm.vision_critical_calls == []


def test_a_model_can_repair_a_name_but_never_invent_an_identifier(photo):
    f, _ = photo

    class Inventive(FakeLlm):
        def read_text(self, pages, progress=None):
            n = next(iter(pages))
            return {"pages": [], "fields": [
                {"field": "ifsc", "value": "FOrKAVERIPRECISIONCOMRONENTS", "page": n, "doc_type": "pan_card", "snippet": ""},   # garbage after a label
                {"field": "ifsc", "value": "HDFC0000001", "page": n, "doc_type": "pan_card", "snippet": ""},                       # well-formed but not on the page
                {"field": "gstin", "value": "27AAACB1234C1Z?", "page": n, "doc_type": "pan_card", "snippet": ""},                  # doubt is kept
                {"field": "legal_name", "value": "BLUE HERON TRADING PRIVATE LIMITED", "page": n, "doc_type": "pan_card", "snippet": ""}]}
    d = HybridReader(db.make_engine("sqlite://"), Inventive()).read_document(f)
    by = {x["field"]: x["value"] for x in d["fields"]}
    assert "ifsc" not in by                                  # neither invented value survives
    assert by["gstin"] == "27AAACB1234C1Z?"                  # a '?' marks doubt and is passed on so the vendor is asked
    assert by["legal_name"] == "BLUE HERON TRADING PRIVATE LIMITED"


def test_economy_mode_turns_the_extra_tiers_off(photo, monkeypatch):
    f, state = photo
    monkeypatch.setenv("READER_QUALITY", "economy")
    state["score"] = 0.55
    llm = FakeLlm()
    d = HybridReader(db.make_engine("sqlite://"), llm).read_document(f)
    assert llm.text_calls == [] and llm.vision_read_calls == [] and d["via"] == "ocr+rules"
