"""
CLI smoke tests – live GitHub + Groq (skipped if creds missing).
They ignore trace chatter and pick the JSON that contains the expected key.
"""
import os, re, json, subprocess, pytest

PR = "https://github.com/psf/requests/pull/6883"
env_ok = all(os.getenv(k) for k in ("GH_TOKEN", "OPENAI_API_KEY", "OPENAI_BASE_URL"))

def _json_from_cli(cmd: list[str], must_have: str) -> dict:
    """Run CLI; return the first JSON block that contains `must_have`."""
    raw = subprocess.check_output(["reviewgenie", *cmd], text=True)
    
    # Use a more robust approach to find JSON blocks
    # Start from positions of all opening braces
    candidates = []
    stack = []
    in_string = False
    escape = False
    
    for i, char in enumerate(raw):
        # Handle string boundaries
        if char == '"' and not escape:
            in_string = not in_string
        
        # Track escape sequences in strings
        escape = char == '\\' and not escape and in_string
        
        # Only process braces outside of strings
        if not in_string:
            if char == '{':
                stack.append(i)
            elif char == '}' and stack:
                start = stack.pop()
                # If we've closed the outermost level, we have a complete JSON object
                if not stack:
                    json_str = raw[start:i+1]
                    if '"' in json_str and must_have in json_str:
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            # Skip invalid JSON and continue looking
                            pass
    
    raise ValueError(f"JSON with key {must_have!r} not found")

@pytest.mark.skipif(not env_ok, reason="live creds not available")
@pytest.mark.parametrize(
    "cmd, key",
    [
        (["ping",   PR],                           "title"),
        (["ingest", PR],                           "changed_files"),
        (["analyze",PR],                           "risk_score"),
        (["inline", PR, "--dry-run"],              "posted"),
    ],
)
def test_cli_smoke(cmd, key):
    payload = _json_from_cli(cmd, key)
    assert key in payload
