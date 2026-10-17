import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chat_ui import render_chat_ui
from chat_ui_patch import inject_chat_runtime_patch
from render_chat_app import _recent_user_programs


def rendered_chat() -> str:
    return inject_chat_runtime_patch(
        render_chat_ui(
            {
                "supabaseUrl": "https://example.supabase.co",
                "supabaseAnonKey": "public-anon-key",
                "authConfigured": True,
                "modelDisplay": "OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2",
            }
        )
    )


def test_chat_ui_is_english_first_with_history_and_chat_controls():
    html = rendered_chat()
    assert '<html lang="en">' in html
    assert "New chat" in html
    assert "Search chats" in html
    assert "Sign in to ThaiLLM" in html
    assert "Create account" in html
    assert "Competition tools" in html
    assert "conversationTitle" in html
    assert "messages" in html
    assert "question,answer" in html
    assert "__CHAT_CONFIG__" not in html


def test_google_oauth_button_and_flow_are_present():
    html = rendered_chat()
    assert "Continue with Google" in html
    assert "signInWithOAuth" in html
    assert "provider:'google'" in html
    assert "redirectTo:window.location.origin+'/'" in html


def test_legacy_academic_intelligence_theme_is_applied():
    html = rendered_chat()
    assert "legacyChatTheme" in html
    assert "--bg:#07101d" in html
    assert "--accent:#6366f1" in html
    assert "--teal:#14b8a6" in html
    assert "IT <span class=\"brand-accent\">KMITL</span> <span class=\"brand-teal\">Curricula</span>" in html


def test_chat_runtime_patch_enables_contextual_endpoint():
    html = rendered_chat()
    assert "'/api/chat'" in html
    assert "messages=[...(c.messages||[])]" in html
    assert "contextualized" in html


def test_recent_user_program_context_ignores_assistant_mentions():
    history = [
        {"role": "user", "content": "AIT เรียนกี่หน่วยกิต?"},
        {
            "role": "assistant",
            "content": "AIT มี 120 หน่วยกิต ส่วน DSBA, IT และ IT International เป็นหลักสูตรอื่น",
        },
    ]
    assert _recent_user_programs(history) == ["AIT"]


def test_recent_user_program_context_supports_comparison_pair():
    history = [
        {"role": "user", "content": "AIT กับ DSBA ต่างกันอย่างไร"},
        {"role": "assistant", "content": "ทั้งสองหลักสูตรมีจุดเน้นต่างกัน"},
    ]
    assert set(_recent_user_programs(history)) == {"AIT", "DSBA"}


def test_supabase_schema_has_rls_for_private_history():
    sql = (ROOT / "supabase/schema.sql").read_text(encoding="utf-8").casefold()
    assert "create table if not exists public.conversations" in sql
    assert "create table if not exists public.messages" in sql
    assert "enable row level security" in sql
    assert "auth.uid() = user_id" in sql
    assert "on delete cascade" in sql
