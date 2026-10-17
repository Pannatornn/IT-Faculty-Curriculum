from pathlib import Path
import sys
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from competition_ai.config import SETTINGS
from competition_ai.knowledge import load_catalog, load_evidence
from competition_ai.pipeline import CompetitionPipeline
from competition_ai.benchmark import load_benchmark, score_answer
from competition_ai.health import api_health


st.set_page_config(
    page_title="IT KMITL Curricula",
    page_icon="🧠",
    layout="wide"
)

st.markdown("""
<style>
.stApp{
background:
radial-gradient(circle at 80% 10%,rgba(150,80,255,.35),transparent 35%),
radial-gradient(circle at 15% 80%,rgba(0,210,255,.25),transparent 35%),
#050816;
color:white;
}
section[data-testid="stSidebar"]{
background:rgba(5,10,25,.75);
backdrop-filter:blur(20px);
}
.card{
background:rgba(15,22,50,.65);
border:1px solid rgba(120,160,255,.25);
border-radius:22px;
padding:22px;
margin:12px 0;
backdrop-filter:blur(15px);
}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def load_system():
    catalog = load_catalog(ROOT)
    evidence = load_evidence(ROOT, catalog)
    return catalog, evidence


catalog, evidence = load_system()
ok, health = api_health(SETTINGS)


st.markdown("""
<div class="card">
<h1>🧠 IT KMITL Curricula</h1>
<p>IT KMITL Curricula • Evidence Grounded • Verified AI</p>
</div>
""", unsafe_allow_html=True)


with st.sidebar:
    st.header("⚡ System Status")

    if ok:
        st.success("ThaiLLM API พร้อมใช้งาน")
    else:
        st.warning(health)

    st.write("Model:", SETTINGS.model)
    st.write("Evidence Units:", len(evidence))

    st.subheader("Knowledge Base")

    for p in ["AIT","DSBA","IT","IT_INTER"]:
        if p in catalog:
            st.write("✓", catalog[p]["display"])

    context = st.selectbox(
        "Program Context",
        ["AUTO","AIT","DSBA","IT","IT_INTER"]
    )


tab1, tab2, tab3, tab4 = st.tabs(
    ["💬 Ask AI","⚖️ Compare","🏆 Benchmark","🛡️ Reliability"]
)


with tab1:
    st.subheader("ถามข้อมูลหลักสูตร")

    question = st.text_area(
        "คำถาม",
        placeholder="เช่น AIT เรียนกี่หน่วยกิต?",
        height=120
    )

    if st.button(
        "🚀 วิเคราะห์ด้วย ThaiLLM",
        type="primary",
        disabled=not question.strip()
    ):

        pipeline = CompetitionPipeline(
            SETTINGS,
            catalog,
            evidence
        )

        with st.spinner("กำลังค้นหลักฐานและตรวจสอบ..."):

            result = pipeline.ask(
                question,
                forced_program=context
            )

        st.markdown("## คำตอบ")
        st.write(result.answer)

        a, b, c = st.columns(3)

        a.metric(
            "Evidence",
            len(result.evidence)
        )

        b.metric(
            "Confidence",
            f"{result.verification.confidence:.0%}"
            if result.verification else "-"
        )

        c.metric(
            "Status",
            result.status
        )

        st.subheader("📄 หลักฐาน")

        for i, e in enumerate(result.evidence, 1):

            with st.expander(
                f"Evidence {i}: {e.citation}"
            ):
                st.write(e.text)

                
with tab2:
    st.subheader("Cross Program Comparison")

    a,b = st.columns(2)

    left = a.selectbox(
        "หลักสูตร A",
        ["AIT","DSBA","IT","IT_INTER"]
    )

    right = b.selectbox(
    "หลักสูตร B",
    [x for x in ["AIT","DSBA","IT","IT_INTER"] if x != left]
)

    topic = st.text_input(
        "หัวข้อ",
        "รายวิชาและทักษะ"
    )

    if st.button("⚖️ เปรียบเทียบ"):
        pipeline = CompetitionPipeline(
            SETTINGS,
            catalog,
            evidence
        )

        result = pipeline.compare(
            f"เปรียบเทียบ {left} กับ {right}: {topic}",
            [left,right],
            topic
        )

        st.write(result.answer)


with tab3:
    st.subheader("🏆 Competition Benchmark")

    bench = load_benchmark(ROOT)

    if st.button("Run Easy.xlsx Benchmark"):
        pipeline = CompetitionPipeline(
            SETTINGS,
            catalog,
            evidence
        )

        rows=[]
        passed=0

        for item in bench["questions"]:
            result = pipeline.ask(item["question"])
            spec = bench["gold"][str(item["id"])]

            ok2,note = score_answer(
                item["id"],
                result,
                spec
            )

            passed += int(ok2)

            rows.append({
                "ข้อ": item["id"],
                "ผล": "PASS" if ok2 else "FAIL",
                "Status": result.status,
                "Note": note
            })

        st.metric(
            "Score",
            f"{passed}/{len(rows)}"
        )

        st.dataframe(rows)

with tab4:
    st.subheader("🛡️ Reliability Architecture")

    st.code("""
Question
 ↓
Security Guard
 ↓
Program Router
 ↓
Evidence Retrieval
 ↓
ThaiLLM
 ↓
Verification
 ↓
Final Answer
""")
