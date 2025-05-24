import chromadb, os, hashlib, pathlib, textwrap, json
from codeview_mcp.cache import db

CHROMA_DIR = pathlib.Path(".cache") / "emb"
collection = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_or_create_collection("hunks")

_API_KEY = os.getenv("OPENAI_API_KEY")
_BASE_URL = os.getenv("OPENAI_BASE_URL")

_TEST_MODE = not (_API_KEY and _BASE_URL) or _API_KEY.startswith("dummy")
if not _TEST_MODE:
    from openai import OpenAI
    _client = OpenAI(api_key=_API_KEY, base_url=_BASE_URL)
else:
    _client = None

_EMBED_DIM = 384


def _embed(text: str):
    """Return an embedding list. Falls back to zero-vector on any error."""
    if _TEST_MODE or _client is None:
        return [0.0] * _EMBED_DIM
    try:
        resp = _client.embeddings.create(
            model="text-embedding-3-small",
            input=textwrap.shorten(text, width=512),
        )
        return resp.data[0].embedding
    except Exception as e:
        print("[warn] embedding fallback:", e)
        return [0.0] * _EMBED_DIM


def index_files(files):
    """Embed hunks, inserting only new IDs to avoid DuplicateIDError."""
    # Fetch current IDs stored in Chroma once
    try:
        existing = set(collection.get()["ids"])
    except Exception:
        existing = set()

    docs, ids, embs = [], [], []
    for f in files:
        if f["is_binary"]:
            continue
        for h in f["hunks"]:
            doc_id = hashlib.sha256((f["path"] + h["section_header"]).encode()).hexdigest()
            if doc_id in existing:
                continue  # skip duplicates across PRs
            doc = json.dumps({**h, "path": f["path"]}, separators=(",", ":"))
            docs.append(doc); ids.append(doc_id); embs.append(_embed(doc))
            existing.add(doc_id)
    if ids:
        collection.upsert(ids=ids, documents=docs, embeddings=embs)


def nearest(query: str, k: int = 3):
    if len(collection.get()["ids"]) == 0:
        return []
    res = collection.query(query_embeddings=[_embed(query)], n_results=k)
    return [json.loads(d) for d in res["documents"][0]]
