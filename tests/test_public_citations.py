from citation_view import evidence_excerpt, public_answer, source_url
from competition_ai.models import AnswerResult, Evidence
from render_server import response_payload


def test_model_echoed_retrieval_dump_removed_from_all_public_answer_fields():
    answer = "English is used [E1].\n\nEVIDENCE:\n[E1] ID=FACT-IT_INTER-1\nSOURCE=IT_inter2565.pdf\nRETRIEVAL_SCORE=10000.0\nTEXT:\nEnglish is used."
    result = AnswerResult(status="SUPPORTED", answer=answer, programs=["IT_INTER"], evidence=[
        Evidence("FACT-IT_INTER-1", "IT_inter2565.pdf", 2, "The IT Inter program is conducted in English.", "IT_INTER")
    ])
    payload = response_payload("What language does IT International use?", result)
    assert payload["answer"] == "English is used [E1]."
    assert payload["answerTh"] == payload["answerEn"] == payload["answer"]
    assert "RETRIEVAL_SCORE" not in " ".join(payload["summaryKeyPoints"])
    assert payload["evidenceList"][0]["sourceUrl"] == "/documents/IT_inter2565.pdf#page=2"


def test_prose_evidence_heading_is_preserved():
    text = "Answer.\nEVIDENCE:\nThe handbook states this on page 2."
    assert public_answer(text) == text


def test_excerpt_selects_relevant_source_passage_and_has_bounded_length():
    source = "Unrelated course information. " * 40 + "หมวดวิชาเฉพาะ 90 หน่วยกิต เป็นส่วนหนึ่งของหลักสูตร AIT. " + "Other course information. " * 40
    preview = evidence_excerpt(source, "AIT หมวดวิชาเฉพาะกี่หน่วยกิต?", "90 หน่วยกิต")
    assert "หมวดวิชาเฉพาะ 90 หน่วยกิต" in preview
    assert len(preview) <= 442
    assert preview.strip("…") in source


def test_document_links_only_allow_known_local_pdf_names():
    assert source_url("AIT.pdf", 12) == "/documents/AIT.pdf#page=12"
    assert source_url("../../.env", 1) is None
    assert source_url("https://evil.example/key", 1) is None


def test_short_source_is_not_rewritten():
    source = "AIT มีหมวดวิชาเฉพาะ 90 หน่วยกิต"
    assert evidence_excerpt(source, "หน่วยกิต?", "90") == source


def test_dump_only_output_becomes_nonempty_retryable_response():
    payload = response_payload("AIT credits?", AnswerResult(status="SUPPORTED", answer="EVIDENCE:\n[E1] ID=FACT-AIT-1\nSOURCE=AIT.pdf\nTEXT:120 credits"))
    assert payload["answer"].strip()
    assert payload["status"] == "RETRY_REQUIRED"
    assert payload["degraded"] is True
    assert payload["supportedByEvidence"] is False
