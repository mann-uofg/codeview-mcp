import os
import sys, argparse, json
from codeview_mcp.server import ping, ingest_pr, analyze_pr, inline_comments, generate_tests

TOOLS = {
    "ping": ping,
    "ingest": ingest_pr,
    "analyze": analyze_pr,
    "inline": inline_comments,
    "generate_tests": generate_tests,
    "check":           analyze_pr,
}

def main():
    p = argparse.ArgumentParser(prog="reviewgenie")
    p.add_argument("tool", choices=TOOLS.keys())
    p.add_argument("pr_url")
    p.add_argument("--style", default=None)
    p.add_argument("--threshold", type=float,
               help="fail if risk_score exceeds this value "
                    "(default RG_RISK_THRESHOLD env or 0.5)")
    p.add_argument("--dry-run", action="store_true",
               help="for 'inline' tool: compute targets but do not post comments")

    args = p.parse_args()
    if args.tool == "check":
        result = analyze_pr(args.pr_url)
        threshold = args.threshold or float(os.getenv("RG_RISK_THRESHOLD", "0.5"))
        if result["risk_score"] > threshold:
            print(f"❌  risk_score {result['risk_score']} exceeds {threshold}")
            sys.exit(1)
        print(f"✅  risk_score {result['risk_score']} within limit {threshold}")
        return
    elif args.tool == "inline":
        kw = {"style": args.style, "dry_run": args.dry_run}
        out = inline_comments(args.pr_url, **kw)

    fn = TOOLS[args.tool]
    kw = {"style": args.style} if args.tool == "inline" else {}
    out = fn(args.pr_url, **kw) if kw else fn(args.pr_url)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
