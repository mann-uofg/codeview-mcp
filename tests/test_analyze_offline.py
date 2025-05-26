"""
Unit test for analyze(): uses a tiny canned diff so no LLM/network hit.
"""
from codeview_mcp.llm import analyze

SAMPLE_DIFF = """\
@@ -1,3 +1,3 @@
-# v1
+# v2
 print("hello world")
"""

def test_analyze_contract(monkeypatch):
    # monkey-patch _local_complete & _cloud_chat to avoid LLM
    monkeypatch.setattr("codeview_mcp.llm._local_complete", lambda *_: "- duplicate print")
    monkeypatch.setattr("codeview_mcp.llm._cloud_chat",
                        lambda *_ , **__: '{"summary":"demo","smells":["duplicate print"],"risk_score":0.42}')

    data = analyze(SAMPLE_DIFF, loc_added=1, loc_removed=1)
    assert data["summary"] == "demo"
    assert data["smells"] == ["duplicate print"]
    assert 0.0 <= data["risk_score"] <= 1.0
