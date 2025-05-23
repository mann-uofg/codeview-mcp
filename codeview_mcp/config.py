import os, pathlib, functools, yaml

DEFAULTS = {
    "max_comments": 10,
    "style": "nitpick",
    "enable_test_gen": True,
}

@functools.lru_cache
def load() -> dict:
    """Merge user .reviewgenie.yml (if any) with DEFAULTS."""
    cwd = pathlib.Path.cwd()
    for parent in [cwd, *cwd.parents]:
        cfg_file = parent / ".reviewgenie.yml"
        if cfg_file.exists():
            user_cfg = yaml.safe_load(cfg_file.read_text()) or {}
            return {**DEFAULTS, **user_cfg}
    return DEFAULTS
