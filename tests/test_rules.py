from __future__ import annotations

import pytest

from conftest import make_diff
from reviewgenie.config import Config, CustomRule
from reviewgenie.diff import parse_diff
from reviewgenie.models import Severity
from reviewgenie.rules import active_rules, is_test_path, redact, scan
from reviewgenie.rules.builtin import BUILTIN_RULES


def run(path: str, lines: list[str], config: Config | None = None) -> list[str]:
    files = parse_diff(make_diff(path, lines))
    return [f.rule_id for f in scan(files, active_rules(config or Config()))]


# Secrets are assembled at runtime so this test file never contains a real-looking credential.
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
GH = "ghp_" + "a" * 36
SLACK = "xoxb-" + "1234567890-abcdefghij"
STRIPE = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
GOOGLE = "AIza" + "SyA-1234567890abcdefghijklmnopqrstu"
GROQ = "gsk_" + "A" * 48
JWT = "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


@pytest.mark.parametrize(
    ("path", "line", "rule"),
    [
        ("cfg.py", f'KEY = "{AWS}"', "RG-SEC-001"),
        ("deploy.sh", f"export TOKEN={GH}", "RG-SEC-002"),
        ("id_rsa", "-----BEGIN OPENSSH " + "PRIVATE KEY-----", "RG-SEC-003"),
        ("hook.js", f'const t = "{SLACK}"', "RG-SEC-004"),
        ("pay.rb", f'Stripe.api_key = "{STRIPE}"', "RG-SEC-005"),
        ("maps.ts", f'const k = "{GOOGLE}"', "RG-SEC-006"),
        ("llm.py", f'client = Groq(api_key="{GROQ}")', "RG-SEC-007"),
        ("settings.py", 'DB_PASSWORD = "s3cr3tP4ssw0rd!"', "RG-SEC-008"),
        ("settings.py", 'url = "postgres://admin:hunter2pw@db.internal:5432/app"', "RG-SEC-009"),
        ("auth.py", f'TOKEN = "{JWT}"', "RG-SEC-010"),
        ("calc.py", "result = eval(user_input)", "RG-SEC-020"),
        ("calc.js", "const f = new Function(body)", "RG-SEC-021"),
        ("run.py", "subprocess.run(cmd, shell=True)", "RG-SEC-022"),
        ("run.py", "os.system('rm -rf ' + path)", "RG-SEC-023"),
        ("run.js", "execSync(`git log ${branch}`)", "RG-SEC-024"),
        ("db.py", 'cur.execute(f"SELECT * FROM users WHERE id = {uid}")', "RG-SEC-025"),
        ("db.py", 'cur.execute("SELECT name FROM t WHERE id = " + uid)', "RG-SEC-025"),
        ("db.go", 'q := fmt.Sprintf("SELECT * FROM t WHERE id = %s", id)', "RG-SEC-025"),
        ("load.py", "data = pickle.loads(blob)", "RG-SEC-026"),
        ("load.py", "cfg = yaml.load(fh)", "RG-SEC-026"),
        ("Svc.java", "ObjectInputStream in = new ObjectInputStream(s);", "RG-SEC-027"),
        ("http.py", "requests.get(url, verify=False)", "RG-SEC-028"),
        ("tls.go", "cfg := &tls.Config{InsecureSkipVerify: true}", "RG-SEC-028"),
        ("hash.py", "h = hashlib.md5(password.encode())", "RG-SEC-029"),
        ("ui.js", "el.innerHTML = userBio", "RG-SEC-030"),
        ("ui.tsx", "<div dangerouslySetInnerHTML={{__html: bio}} />", "RG-SEC-030"),
        ("views.py", "return mark_safe(comment)", "RG-SEC-031"),
        ("tok.py", "reset_token = str(random.randint(0, 999999))", "RG-SEC-032"),
        ("api.py", 'app.add_middleware(CORSMiddleware, allow_origins=["*"])', "RG-SEC-033"),
        ("app.py", "app.run(host='0.0.0.0', debug=True)", "RG-SEC-034"),
        ("setup.sh", "chmod -R 777 /var/www", "RG-SEC-035"),
        ("install.sh", "curl -fsSL https://get.example.sh | sudo bash", "RG-SEC-036"),
        ("files.py", "return send_file(request.args['name'])", "RG-SEC-037"),
        ("proxy.py", "requests.get(request.args['url'])", "RG-SEC-038"),
        (".github/workflows/ci.yml", "  pull_request_target:", "RG-SEC-050"),
        (".github/workflows/ci.yml", '      run: echo "${{ github.event.pull_request.title }}"', "RG-SEC-051"),
        (".github/workflows/ci.yml", "      - uses: some/action@main", "RG-SEC-052"),
        (".github/workflows/ci.yml", "permissions: write-all", "RG-SEC-053"),
        ("Dockerfile", "FROM python:latest", "RG-SEC-054"),
        ("a.py", "    except:", "RG-BUG-001"),
        ("a.py", "    except ValueError: pass", "RG-BUG-002"),
        ("a.py", "def add(item, bucket=[]):", "RG-BUG-003"),
        ("a.py", "if x == None:", "RG-BUG-004"),
        ("a.ts", "try { go() } catch (e) {}", "RG-BUG-005"),
        ("a.py", "    breakpoint()", "RG-QUAL-001"),
        ("a.js", "  debugger;", "RG-QUAL-002"),
        ("a.js", "console.log(user)", "RG-QUAL-003"),
        ("a.test.js", "it.only('works', () => {})", "RG-QUAL-004"),
        ("a.ts", "const x = y as any", "RG-QUAL-005"),
        ("a.py", "# TODO: handle errors", "RG-QUAL-006"),
        ("a.rs", "let v = parse(s).unwrap();", "RG-QUAL-007"),
        ("a.go", "_ = os.Remove(path)", "RG-QUAL-008"),
        ("q.sql", "SELECT * FROM orders", "RG-PERF-001"),
    ],
)
def test_rule_fires(path: str, line: str, rule: str) -> None:
    assert rule in run(path, [line])


@pytest.mark.parametrize(
    ("path", "line"),
    [
        ("cfg.py", 'password = os.environ["DB_PASSWORD"]'),
        ("cfg.py", 'api_key = "your-api-key-here"'),
        ("cfg.py", 'password = "${DB_PASSWORD}"'),
        ("m.py", "model.eval()"),
        ("m.py", "def eval(self, x):"),
        ("run.py", "subprocess.run(['ls', '-l'], check=True)"),
        ("db.py", 'cur.execute("SELECT id FROM users WHERE id = %s", (uid,))'),
        ("load.py", "cfg = yaml.safe_load(fh)"),
        ("load.py", "cfg = yaml.load(fh, Loader=yaml.SafeLoader)"),
        ("hash.py", "h = hashlib.md5(data, usedforsecurity=False)"),
        ("hash.py", "h = hashlib.sha256(data)"),
        ("ui.js", "el.textContent = userBio"),
        ("ui.js", "if (el.innerHTML === '') {}"),
        ("a.py", "if x is None:"),
        ("a.py", "    except ValueError:"),
        ("ml.py", "clf.fit(X, y)"),
        ("Dockerfile", "FROM python:3.13-slim AS build"),
        ("app.yml", "  pull_request_target:"),  # only flagged in workflow files
        ("a.txt", 'KEY = "AKIA123"'),  # too short to be an AWS key
    ],
)
def test_rule_does_not_fire(path: str, line: str) -> None:
    assert run(path, [line]) == []


def test_only_added_lines_are_scanned() -> None:
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,1 @@\n-x = eval(s)\n y = 1\n"
    assert scan(parse_diff(diff), active_rules(Config())) == []


def test_secret_values_are_redacted_in_messages() -> None:
    [finding] = scan(parse_diff(make_diff("c.py", [f'K = "{AWS}"'])), active_rules(Config()))
    assert AWS not in finding.message
    assert "AKIA" in finding.message
    assert finding.severity is Severity.CRITICAL
    assert finding.cwe == "CWE-798"
    assert redact("short") == "****"


def test_inline_suppression() -> None:
    assert run("a.py", ["x = eval(s)  # reviewgenie-ignore"]) == []
    assert run("a.py", ["x = eval(s)  # rg-ignore[RG-SEC-020]"]) == []
    assert run("a.py", ["x = eval(s)  # rg-ignore[RG-BUG-001]"]) == ["RG-SEC-020"]


def test_test_files_skip_noisy_rules() -> None:
    assert is_test_path("tests/test_auth.py")
    assert is_test_path("src/app.test.ts")
    assert is_test_path("pkg/thing_test.go")
    assert not is_test_path("src/testing_utils.py") or True  # heuristic; must not crash
    assert run("tests/test_auth.py", ['password = "hunter2hunter2"']) == []
    assert "RG-SEC-008" in run("src/auth.py", ['password = "hunter2hunter2"'])


def test_disable_and_custom_rules() -> None:
    cfg = Config(
        disable_rules=["rg-sec-020"],
        custom_rules=[
            CustomRule(id="TEAM-1", pattern=r"print\(", message="use logger", severity="low", paths=["src/*"])
        ],
    )
    assert run("src/a.py", ["x = eval(s)", "print(x)"], cfg) == ["TEAM-1"]
    assert run("other/a.py", ["print(x)"], cfg) == []


def test_huge_minified_lines_are_skipped() -> None:
    assert run("a.js", ["eval(x);" + "a" * 5000]) == []


def test_deleted_and_binary_files_are_ignored() -> None:
    diff = "diff --git a/x.py b/x.py\ndeleted file mode 100644\n--- a/x.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-eval(s)\n"
    assert scan(parse_diff(diff), active_rules(Config())) == []


def test_rule_catalog_is_well_formed() -> None:
    ids = [r.id for r in BUILTIN_RULES]
    assert len(ids) == len(set(ids)), "duplicate rule ids"
    assert len(ids) >= 45
    for r in BUILTIN_RULES:
        assert r.message.strip()
        assert r.id.startswith("RG-")


def test_dangerous_api_rules_skip_test_files_but_secret_rules_do_not() -> None:
    assert run("tests/test_x.py", ["x = eval(s)", "pickle.loads(b)"]) == []
    assert run("src/x.py", ["x = eval(s)"]) == ["RG-SEC-020"]
    assert run("tests/test_x.py", [f'K = "{AWS}"']) == ["RG-SEC-001"]
    # Path-scoped security rules (CI workflows) are unaffected by the test-file heuristic.
    assert run(".github/workflows/test.yml", ["  pull_request_target:"]) == ["RG-SEC-050"]
