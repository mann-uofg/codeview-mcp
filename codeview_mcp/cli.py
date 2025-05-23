import sys, argparse, json
from server import ping, ingest_pr, analyze_pr, inline_comments

TOOLS = {
    "ping": ping,
    "ingest": ingest_pr,
    "analyze": analyze_pr,
    "inline": inline_comments,
}

def main():
    p = argparse.ArgumentParser(prog="reviewgenie")
    p.add_argument("tool", choices=TOOLS.keys())
    p.add_argument("pr_url")
    p.add_argument("--style", default=None)
    args = p.parse_args()

    fn = TOOLS[args.tool]
    kw = {"style": args.style} if args.tool == "inline" else {}
    out = fn(args.pr_url, **kw) if kw else fn(args.pr_url)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
