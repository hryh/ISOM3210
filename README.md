# Procurement-agent

Browser-assisted procurement agent

PurchasePilot converts an employee's equipment request into a traceable supplier
comparison and an approval-ready purchase requisition. It researches supplier
websites with Stagehand, extracts product evidence, applies explicit purchasing
rules in Python, and explains its recommendation. A human (a manager) reviews
and approves before the order is placed.

The prototype stops at order placement. It does not process payments, sign
contracts, or guarantee supplier fulfillment.

## Setup

```bash
uv sync          # creates .venv with Python 3.12 and installs dependencies
uv run pytest    # run the deterministic test suite
```

Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY` (used by the chatbot
parser and the Stagehand browser LLM).

## Status

Multi-page Streamlit UI (chatbot, order wizard, order history, manager
approvals, supplier and user management) on top of a human-record SQLite
schema. The agent researches the seeded mock supplier sites with Stagehand,
and also supports **live aggregator sites** (Price.com.hk is seeded as an
approved supplier): free-text order requests are searched live and deep-
scraped within a strict exploration budget. Free-text ("Other") categories
let users order anything, validated by deterministic keyword matching.

## Running the demo

```bash
# 1. The mock supplier sites (one app serves all three suppliers)
uv run uvicorn mock_sites.server:app --port 8100

# 2. The Streamlit UI (creates/seed data/purchasepilot.db on first run)
uv run streamlit run app.py

# 3. Sign in with the seeded manager account
#    admin / admin123   (override with DEMO_ADMIN_PASSWORD)
```

Set `MOCK_BASE_URL` if the mock sites run elsewhere. Aggregator suppliers
(Price.com.hk) sit behind Cloudflare, so their research automatically runs in
a **visible browser window** — you can watch it shop. Set `STAGEHAND_HEADLESS=false`
to make all research visible, `true` to force headless.

Managers add employees under **User Management**. Any user can create an order
via the **Chatbot** or the **Order Request** wizard — typed categories
(monitor / keyboard / chair) or the **Other** free-text option; only managers
approve on **Pending Approvals**. Research runs in a background thread
writing order status to SQLite, so Streamlit reruns never restart it.

### Deep-scrape fence

For aggregator suppliers the agent searches the request phrase, then opens at
most **6 product pages**, taking at most **5 shop offers** each, within **120s
and 25 browser actions** per supplier — then the deterministic rules engine
picks the best compliant offer inside that fence. Availability is classified
by the extractor (in stock / low stock / preorder / out of stock); shipping
that the site does not list is excluded from the verified total and shown as
unverified on the approval card.

### Adding a live supplier

Managers add suppliers on the **Suppliers** page. For a plain catalog site,
just the site URL is needed. For an aggregator/search site (like Price.com.hk)
also set a **Catalog / search URL** containing a `{query}` placeholder, e.g.
`https://www.price.com.hk/search.php?q={query}` — zero agent code changes.

## Layout

```text
app.py                     # Streamlit shell: login gate + st.navigation router
procurement/               # deterministic core + agent blackbox
  controller.py           # workflow controller / state machine (in-memory)
  states.py               # WorkflowState enum + transition graph
  schemas.py               # Pydantic models
  money.py                 # integer minor-unit (HKD cents) arithmetic
  rules.py                 # business rules (§5)
  auth.py                  # pbkdf2 password hashing + login
  order_service.py         # order lifecycle + human decisions
  chat_service.py          # chat session/message persistence (5-session cap)
  research.py              # blackbox research orchestrator (background thread)
  seed.py                  # synthetic data generator + DB seeding
  repository.py            # SQLAlchemy models + SQLite session
  tools/                   # browser (Stagehand) + supplier research + portal stubs
  llm/                     # configurable LLM adapter + prompts
  ui/                      # Streamlit page renderers
mock_sites/                # FastAPI supplier sites + mock portal
data/                      # policy + seed configuration
scripts/                   # seed_demo.py, inspect_db.py, run_evaluation.py
tests/                     # unit + integration + fixtures
```

## Key design constraints

- The database is the **human record** (users, suppliers, products, orders,
  human decisions, chat persistence). Agent internals (runs, evidence, audit
  events) are deliberately not persisted — the agent is a blackbox whose
  outputs touch SQLite only.
- Order lifecycle transitions are enforced in `order_service.py` — never in the
  UI layer — so Streamlit reruns cannot repeat writes or restart research.
- The LLM parses ambiguity and explains decisions; Python owns all arithmetic,
  eligibility, and state transitions.
- Supplier facts are acquired only through browser-visible evidence, never from
  seed data or hidden fixtures. Unknown facts stay unknown (three-valued
  logic), never silently zero.
- All money is integer HKD minor units (cents); no floating-point arithmetic.

## Phase 1 feasibility spike

See `scripts/browser_smoke_test.py` for the Stagehand + local Chrome + DeepSeek
round-trip check (`uv run python scripts/browser_smoke_test.py --target local`
with the mock sites running).
