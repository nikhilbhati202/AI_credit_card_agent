# Architecture

**Phase 4 deliverable** (Implementation Guide Section 3: "architecture diagrams"). Companion
to `README.md` (how to run it) and `EVALUATION_REPORT.md` (how well it works) - this document
answers what the system is built from and how a request actually flows through it.

## Governing principle

Every diagram below is a direct consequence of one constraint (guide Section 1.2): **facts,
arithmetic, and judgment must never leak into each other.**

| Concern | Owned by | Never done by |
|---|---|---|
| Facts (what a card's T&C says) | Retrieval (RAG, `tools/retriever.py`) | The LLM's memory |
| Arithmetic (what the reward is worth) | `tools/calculator.py`, `tools/transfer_calculator.py` | The LLM |
| Judgment (what to tell the user, and whether to trust the draft) | LLM (2 of 9 graph nodes) + Guardrail node | An unchecked LLM output |

## System components

```mermaid
flowchart LR
    subgraph Client
        UI["Streamlit UI\napp/streamlit_app.py\n(thin - HTTP only)"]
    end

    subgraph API["FastAPI backend (backend/)"]
        REC["/recommend\n/optimize/monthly"]
        XFER["/transfer/evaluate\n/transfer/confirm"]
        MISC["/cards, /user/profile, /health"]
    end

    subgraph Agent["LangGraph agent (agents/)"]
        GRAPH["Compiled graph\n(see Node Flow below)"]
        CKPT[("MemorySaver\nsession checkpointer")]
    end

    subgraph Data["Postgres + pgvector"]
        DB[("card_documents\ndocument_chunks (vector)\nreward_rules\ntransfer_partners\nuser_profiles\nrecommendation_logs")]
    end

    subgraph Ingestion["Offline ingestion (rag/), run once via database.seed"]
        PDF["Issuer PDFs\ndata/raw_pdfs/"] --> CHUNK["chunk_documents.py"] --> EMBED["embed_documents.py\n(local bge-small-en-v1.5)"] --> DB
    end

    LLM[("LLM (agents/llm.py)\nopenai_compatible (Colab/Ollama, default) or anthropic")]
    LangSmith[("LangSmith / Phoenix\n(optional tracing)")]

    UI -- HTTP/JSON --> REC
    UI -- HTTP/JSON --> XFER
    REC --> GRAPH
    XFER --> GRAPH
    MISC --> DB
    GRAPH <--> CKPT
    GRAPH -- reads/writes --> DB
    GRAPH -- 2 of 9 nodes only --> LLM
    GRAPH -.trace every node run.-> LangSmith
```

Dependency direction (guide Section 22.1, enforced by code review, not tooling):
`backend/` → `agents/` → `services/` → `tools/`, `database/`. `tools/` never imports
`agents/` - it stays framework-agnostic and independently testable, which is what makes the
84 `tools/`+`database/models.py`+`agents/state.py` lines in the coverage report hit 100%
without a single mock.

## LangGraph node flow

Nine nodes total; only **Intent Classification** and **Final Answer**'s narrative step touch
an LLM (shaded). Every other node - including the two added in Phase 3, Guardrail and Human
Approval - is deterministic, pure Python, independently unit-tested without any LLM call.

```mermaid
flowchart TD
    START((START)) --> Intent

    Intent["Intent Classification 🤖\n(structured output, provider-switchable)"]
    Intent -- unclear, round < cap --> Clarify
    Intent -- transfer_evaluation --> Propose
    Intent -- single_transaction /\nmonthly_optimization --> Retrieve

    Clarify["Clarification 🤖\n(1 round max, Section 14.3)"] --> ENDA((END\nwaits for next turn))

    Retrieve["Retrieval\n(pgvector similarity + card_name filter)"] --> Validate
    Validate["Rule Validation\n(is there any evidence at all?)"]
    Validate -- insufficient --> Final
    Validate -- sufficient --> Calculate

    Calculate["Calculation\n(tools/calculator.py, per owned card)"] --> Compare
    Compare["Comparison\n(rank by reward_value)"] --> Final

    Propose["Transfer Proposal\n(tools/transfer_calculator.py)"]
    Propose -- unknown partner /\nmissing data --> Final
    Propose -- sufficient --> Guardrail

    Final["Final Answer\n(deterministic fields +\n🤖 narrative, skipped entirely on a refusal)"]
    Final -- fresh spend draft --> Guardrail
    Final -- already resolved\n(refusal / post-approval) --> ENDB((END))

    Guardrail["Guardrail\n(numeric consistency, citation,\ncategory vocab, injection leakage,\nnumber grounding - all code, no LLM)"]
    Guardrail -- pass, spend flow --> ENDB
    Guardrail -- pass, transfer flow --> Approval
    Guardrail -- fail, loop < MAX_GUARDRAIL_LOOPS --> Retrieve
    Guardrail -- fail, transfer OR loop exhausted --> Refuse

    Approval["Human Approval\nreal interrupt() / Command(resume=...)\n⏸ pauses execution, no auto-finalize"] --> Final

    Refuse["Guardrail Refusal\n(-> honest insufficient_information)"] --> Final

    classDef llm fill:#fde8d0,stroke:#c9791f
    class Intent,Clarify,Final llm
```

Two loop-prevention caps, both hard iteration counters in `agents/state.py`, never an
assumption that "the LLM won't loop forever" (Section 14.3 / Section 24's explicit pitfall):

- `MAX_CLARIFICATION_ROUNDS = 1` - a second unclear intent is forced through to a best-effort
  or honest refusal, never a second question.
- `MAX_GUARDRAIL_LOOPS = 2` - a persistently-failing draft retries retrieval up to twice, then
  is refused. `tests/agent/test_graph.py::TestGuardrailLoop` drives this end-to-end with a
  mocked LLM that fails identically every retry, proving the cap actually terminates the graph
  rather than looping.

## The Human Approval gate (Phase 3's core safety property)

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit UI
    participant API as POST /recommend or\n/transfer/evaluate
    participant Graph as LangGraph (paused)
    participant Confirm as POST /transfer/confirm

    User->>UI: "Transfer 10000 miles to KrisFlyer"
    UI->>API: query, cards_owned, session_id
    API->>Graph: invoke()
    Graph->>Graph: Propose -> Guardrail (pass) -> Approval: interrupt()
    Graph-->>API: {"__interrupt__": [...], no final_answer}
    API-->>UI: approval_pending=true, proposal={...}
    UI->>UI: render proposal, block chat input,\nshow Confirm/Cancel
    User->>UI: clicks Confirm
    UI->>Confirm: session_id, approved=true
    Confirm->>Graph: Command(resume={"approved": true})
    Graph->>Graph: Approval returns -> Final Answer
    Graph-->>Confirm: final_answer.approval_status="approved"
    Confirm-->>UI: transfer_proposal, message
    UI->>UI: unblock chat input
```

The graph cannot reach `final_answer` with a non-null `approval_status` without a
`Command(resume=...)` call landing on the exact paused `thread_id` - there is no code path
that finalizes a transfer from a single `invoke()`. `agents/runner.py`'s
`get_pending_interrupt()` / `resume_agent()` / `has_pending_approval()` are the only points
that touch this mechanism.

## Data model (selected tables)

```mermaid
erDiagram
    CARD_DOCUMENTS ||--o{ DOCUMENT_CHUNKS : contains
    CARD_DOCUMENTS ||--o{ REWARD_RULES : "governs (source_chunk_id)"
    CARD_DOCUMENTS ||--o{ TRANSFER_PARTNERS : "governs (source_chunk_id)"
    USER_PROFILES ||--o{ RECOMMENDATION_LOGS : "queried by (user_id)"

    CARD_DOCUMENTS {
        int id PK
        string card_name
        string document_type
        date effective_date
        string source_url
    }
    DOCUMENT_CHUNKS {
        int id PK
        int document_id FK
        string card_name
        text chunk_text
        vector embedding
    }
    REWARD_RULES {
        int id PK
        string card_name
        string spend_category
        float reward_rate
        enum reward_unit
        enum cap_basis
        float confidence_score
    }
    TRANSFER_PARTNERS {
        int id PK
        string card_name
        string partner_name
        float transfer_ratio_from
        float transfer_ratio_to
        float confidence_score
        string source_note
    }
```

`reward_rules.confidence_score` (0.85-1.0, issuer-PDF-sourced) vs.
`transfer_partners.confidence_score` (0.7-0.85, secondary-source cross-checked) is a
deliberate, visible distinction - see `README.md`'s "Data sourcing" section.

## Deployment

```mermaid
flowchart LR
    subgraph "docker compose up"
        db["db\npgvector/pgvector:pg16"]
        app["app\nFastAPI, port 8000\nmulti-stage Dockerfile"]
        ui["ui\nStreamlit, port 8501\nDockerfile.streamlit"]
    end
    app -->|DB_HOST=db| db
    ui -->|API_BASE_URL=http://app:8000/api/v1| app
```

`docker-compose.yml` is the primary local-dev and capstone-demo deployment mechanism (guide
Section 20.1) - a full orchestration platform is explicitly out of scope at this project's
scale. See `README.md`'s "Rollback" section for the commit-SHA image tagging strategy
(Section 20.5) and a demonstrated rollback cycle.
