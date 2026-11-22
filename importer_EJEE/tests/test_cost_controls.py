import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cost_controls import make_submit_pair, prune_previews  # noqa: E402
from extraction_contract import bind_descriptions, build_prompt  # noqa: E402

IMG = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}


def preview(name):
    return HumanMessage(content=[{"type": "text", "text": f"[Crop preview: {name}]"}, dict(IMG)])


def test_only_latest_preview_per_figure_keeps_its_image():
    source = HumanMessage(content=[{"type": "text", "text": "QUESTION page 1"}, dict(IMG)])
    messages = [source, preview("qfig1.png"), ToolMessage("retry", tool_call_id="a"),
                preview("sfig1.png"), preview("qfig1.png"), AIMessage(content="ok")]
    assert prune_previews(messages) == 1
    assert messages[0].content[1]["type"] == "image_url"          # source page untouched
    assert "Older preview of qfig1.png" in messages[1].content[0]["text"]
    assert messages[3].content[1]["type"] == "image_url"          # other figure untouched
    assert messages[4].content[1]["type"] == "image_url"          # newest kept
    assert messages[2].content == "retry"                          # text history kept
    assert prune_previews(messages) == 0                           # idempotent


def test_text_form_tool_calls_are_recovered_only_for_allowed_tools():
    from cost_controls import recover_text_tool_calls
    text = (
        '<atem:function_calls>\n<atem:invoke name="default.submit_pair">\n'
        '<atem:parameter name="paper_id">1</atem:parameter>\n'
        '<atem:parameter name="question_number">4</atem:parameter>\n'
        '<atem:parameter name="question_latex">Radius $R_{ab} << r$ and \\textbf{Q8.}\nnext line</atem:parameter>\n'
        '<atem:parameter name="solution_latex">no_solution_found</atem:parameter>\n'
        '</atem:invoke>\n<atem:invoke name="default.delete_everything">'
        '<atem:parameter name="x">1</atem:parameter></atem:invoke>\n</atem:function_calls>')
    calls = recover_text_tool_calls(text, {"submit_pair", "exact_crop"})
    assert [c["name"] for c in calls] == ["submit_pair"]          # unknown tool ignored
    args = calls[0]["args"]
    assert args["paper_id"] == 1 and args["question_number"] == "4"   # IDs stay strings
    assert args["question_latex"] == "Radius $R_{ab} << r$ and \\textbf{Q8.}\nnext line"
    assert recover_text_tool_calls("plain prose, no markup", {"submit_pair"}) == []


def test_paired_mode_exposes_one_save_tool_and_explains_it():
    def fake(name):
        from langchain_core.tools import tool
        @tool(name)
        def f(x: int) -> str:
            """stub"""
            return ""
        return f
    tools = [fake("get_page_image"), fake("exact_crop"), make_submit_pair()]
    bound = bind_descriptions(tools, {"raster_exact_crop": True})
    assert [t.name for t in bound] == ["get_page_image", "exact_crop", "submit_pair"]
    schema = bound[2].tool_call_schema.model_json_schema()["properties"]
    assert {"question_latex", "solution_latex", "qtype"} <= set(schema)
    prompt = build_prompt({"raster_exact_crop": True})
    assert "ONE submit_pair call" in prompt
    assert "submit_pair" not in build_prompt({"raster_exact_crop": False, "paired_submit": False})
