from subprocess import check_output
def test_ping_smoke():
    out = check_output([
        "python", "-m", "codeview_mcp.cli",
        "ping", "https://github.com/psf/requests/pull/6883"
    ], text=True)
    assert '"title"' in out
