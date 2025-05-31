# Architecture

```mermaid
graph TD
  subgraph Pipeline
    A["GitHub PR URL"] -->|ingest_pr| B["Diff JSON + cache"]
    B -->|prompt| C["Local LLM<br>CodeLlama-13B"]
    C -->|summary| D["Cloud LLM<br>llama-3.1-8b-instant"]
    D -->|smells + risk| E["risk engine"]
  end

  E -->|risk < 0.6| F["CI ✅"]
  E -->|risk ≥ 0.6| G["CI ❌"]

  B --> H["ChromaDB<br>(hunk embeddings)"]
  E --> I["inline_comments"] --> PR["GitHub Review Comments"]
