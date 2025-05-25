import os, keyring

SERVICE = "reviewgenie"

def get(name: str) -> str | None:
    """Return secret from env or keyring."""
    return os.getenv(name) or keyring.get_password(SERVICE, name)

def require(name: str) -> str:
    val = get(name)
    if not val:
        raise RuntimeError(f"missing secret {name}; export or store in keyring")
    return val

def set_in_keyring(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)
