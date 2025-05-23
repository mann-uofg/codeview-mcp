import ast, textwrap, tempfile, subprocess, os, pathlib
from github import Github
from codeview_mcp.utils.helpers import parse_pr_url
from codeview_mcp.utils.ingest import fetch_pr

GH = Github(os.getenv("GH_TOKEN"))

def _functions_needing_tests(repo_path: pathlib.Path) -> list[pathlib.Path]:
    """Return .py files in PR that add defs without matching test_ files."""
    funcs = []
    for py in repo_path.rglob("*.py"):
        if "test_" in py.name:
            continue
        tree = ast.parse(py.read_text())
        if any(isinstance(n, ast.FunctionDef) for n in tree.body):
            funcs.append(py)
    return funcs

def generate_pytest_stub(func_path: pathlib.Path) -> str:
    """Return a pytest skeleton string."""
    mod = func_path.stem
    return textwrap.dedent(f"""
        import pytest
        from {mod} import *  # import functions to test

        def test_placeholder():
            assert True  # TODO: write real assertions
    """).lstrip()

def draft_tests(repo_slug: str, pr_num: int) -> dict[str,str]:
    """Clone repo@PR, scan for funcs, return map {filename:content}."""
    pr = GH.get_repo(repo_slug).get_pull(pr_num)
    tmp = tempfile.TemporaryDirectory()
    subprocess.run(["git", "clone", pr.head.repo.clone_url, tmp.name], check=True)
    subprocess.run(["git", "-C", tmp.name, "checkout", pr.head.sha], check=True)

    repo_path = pathlib.Path(tmp.name)
    stubs = {}
    for f in _functions_needing_tests(repo_path):
        target = pathlib.Path("tests") / f"test_{f.stem}.py"
        stubs[str(target)] = generate_pytest_stub(f)

    tmp.cleanup()
    return stubs
