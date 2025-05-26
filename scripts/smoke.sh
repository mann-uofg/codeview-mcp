#!/usr/bin/env bash
set -euo pipefail
PR="https://github.com/psf/requests/pull/6883"

json_with() {        # usage: json_with KEY reviewgenie <subcommand>...
  KEY=$1; shift
  python - "$KEY" "$@" <<'PY'
import re, sys, json, subprocess, os
key = sys.argv[1]
raw = subprocess.check_output(sys.argv[2:], text=True)

# First try to parse the entire output as JSON
try:
    data = json.loads(raw)
    if key in data:
        print(json.dumps(data))
        sys.exit(0)
except json.JSONDecodeError:
    pass

# If that fails, use a more sophisticated approach to find JSON objects
stack = []
in_string = False
escape = False
start_indexes = []

for i, char in enumerate(raw):
    # Handle string boundaries
    if char == '"' and not escape:
        in_string = not in_string
    
    # Track escape sequences in strings
    escape = char == '\\' and not escape and in_string
    
    # Only process braces outside of strings
    if not in_string:
        if char == '{':
            if not stack:  # Start of a potential JSON object
                start_indexes.append(i)
            stack.append(i)
        elif char == '}' and stack:
            stack.pop()
            if not stack:  # End of a complete JSON object
                start = start_indexes.pop()
                json_str = raw[start:i+1]
                if key in json_str:
                    try:
                        obj = json.loads(json_str)
                        if key in obj:
                            print(json.dumps(obj))
                            sys.exit(0)
                    except json.JSONDecodeError:
                        pass  # Not valid JSON, try the next candidate

# If we get here, no valid JSON with the key was found
print("{}")  # Return empty object as fallback
PY
}

echo "🛠  ping"
json_with title          reviewgenie ping    "$PR"      | jq .

echo "🛠  ingest"
json_with changed_files  reviewgenie ingest  "$PR"      | jq '.changed_files'

echo "🛠  analyze"
json_with risk_score     reviewgenie analyze "$PR"      | jq '.risk_score'

echo "🛠  check (threshold=0.9)"
reviewgenie check "$PR" --threshold 0.9 && echo "✅ risk below threshold"

echo "🎉  all good"