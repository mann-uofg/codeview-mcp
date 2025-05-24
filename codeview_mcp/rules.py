RULES = [
    {
        "id": "SEC001",
        "name": "Hard-coded AWS secret",
        "pattern": r"AKIA[0-9A-Z]{16}",
        "severity": 0.9,
    },
    {
        "id": "SEC002",
        "name": "eval() usage",
        "pattern": r"\\beval\\(.*?\\)",
        "severity": 0.8,
    },
    {
        "id": "QUAL001",
        "name": "Long loop w/out break",
        "pattern": r"for .*:.*\\n(\\s{4,}[^\\n]+){30,}",
        "severity": 0.4,
    },
    # … add more rules later
]
