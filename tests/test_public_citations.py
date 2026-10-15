import pytest

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


@pytest.mark.parametrize(
    "dump",
    [
        "EVIDENCE: [E1] ID=FACT-IT_INTER-1 SOURCE=IT_inter2565.pdf RETRIEVAL_SCORE=10000",
        "Evidence:\n[e1] id=FACT-IT_INTER-1\nsource=IT_inter2565.pdf\nretrieval_score=10000",
        "### Evidence: [e1] id = FACT-IT_INTER-1 source = IT_inter2565.pdf",
        "**EVIDENCE:** [e1] kind = canonical retrieval_score = 10000",
        "**Evidence**: [e1] id=FACT-IT_INTER-1 source=IT_inter2565.pdf",
        "Retrieval details: [e1] id=FACT-IT_INTER-1 source=IT_inter2565.pdf",
    ],
)
def test_inline_lowercase_and_markdown_retrieval_dumps_are_removed(dump):
    payload = response_payload(
        "What language does IT International use?",
        AnswerResult(status="SUPPORTED", answer="English is used [E1].\n\n" + dump),
    )
    assert payload["answer"] == "English is used [E1]."
    assert payload["answerTh"] == payload["answerEn"] == payload["answer"]
    assert payload["summaryKeyPoints"] == ["English is used [E1]."]


@pytest.mark.parametrize("label", ["EVIDENCE:", "Evidence:", "**Evidence:**", "### Evidence:"])
def test_inline_natural_evidence_prose_is_preserved(label):
    text = "English is used [E1].\n" + label + " The handbook states this on page 2."
    assert public_answer(text) == text


def test_natural_evidence_section_before_a_technical_dump_is_preserved():
    prose = "English is used [E1].\nEvidence: The handbook states this on page 2."
    assert public_answer(prose + "\nEVIDENCE: id=FACT-IT_INTER-1 source=IT_inter2565.pdf") == prose


def test_chinese_localized_dump_is_removed_after_the_natural_evidence_paragraph():
    prose = (
        "AIT课程于2023年7月（2023年第一学期）开始招生并开课。\n\n"
        "证据：\n- [E1] AIT课程是新开设的课程，定于2023年7月开课。"
    )
    dump = (
        "\n\n证据：\n[E1] ID=FACT-AIT-1\n来源=AIT.pdf • 第4页\n课程=AIT\n"
        "类型=canonical\n检索得分=10000.0\n文本：\n原始OCR与不受支持的扩展。"
    )
    payload = response_payload(
        "AIT人工智能技术专业从什么时候开始招生开课?",
        AnswerResult(status="SUPPORTED", answer=prose + dump, programs=["AIT"]),
    )
    assert payload["answer"] == prose
    assert "ID=" not in payload["answer"]
    assert "检索得分" not in payload["answer"]


@pytest.mark.parametrize("heading", ["หลักฐาน:", "证据：", "Belege:", "دليل:", "### 証拠："])
def test_structural_retrieval_dump_is_removed_regardless_of_heading_language(heading):
    answer = "Supported answer [E1].\n\n" + heading + "\n[E1] ID=FACT-AIT-1\n來源=AIT.pdf"
    assert public_answer(answer) == "Supported answer [E1]."


def test_localized_natural_citation_prose_is_not_a_dump():
    answer = "AIT于2023年7月开课。\n证据：\n- [E1] 课程文件第4页明确说明开课时间。"
    assert public_answer(answer) == answer


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
