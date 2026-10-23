# Linearyze EMS: proof of concept

A proof of concept for the Linearyze Event Management System, built for RFQ-LNZ-2026-001. It
covers the Search Assistant and the Operational Advisor, and it is built to pass the SRS
validations that carry the most risk: permission enforcement, the single not-found message
M1, verbatim grounding, Arabic matching, and exact calculation with no stored formula
library.

**Live demo:** https://linearyze-ems-poc.vercel.app/login

| Account | Name | Sees |
|---|---|---|
| Management | Faisal Al-Harbi | All events, including confidential documents |
| Employee | Noura Al-Mutairi | Riyadh Design Expo 2026 only, no confidential documents |
| Admin | Khalid Al-Zahrani | User list only. Assistant, Advisor and documents return 403 |

The login page has a one-click button for each account. All people, organisations and
documents are fictional.

The language model is Claude (Sonnet 5.5 for grading, Opus 5.5 for answers), with Cohere
for multilingual embeddings and reranking. Until the Claude API key for the hosted demo is
in place, the demo serves from the next provider in the fallback chain; `/api/health` shows
which providers are configured.

---

## Six things to try

Open **Debug +** under any answer to see the grade, the retrieval plan, passage scores and
timings. The line under each answer shows the HTTP status, byte count and SHA-256 of the
response body as the browser received it.

1. **Find a document by how it relates to another one.** As Employee, ask:
   *Give me the letter from the Ministry of Exhibitions and Heritage that we received on the
   day we submitted the Exhibition Permit Application.*
   The plan finds the application's submitted date (17 March 2026), then the Ministry letter
   received that day. The corpus has four Ministry letters on different dates, plus another
   authority's letter received the same day, so similarity search alone would pick the wrong
   one. The same question works in Arabic (1.14.9).

2. **Restricted and missing look the same.** As Employee, ask *Give me the Board Memo -
   Executive Bonus Pool 2026* (it exists, but is confidential). Then ask *Give me the Riyadh
   Marathon sponsorship contract* (it does not exist). Both return M1 with the same bytes,
   the same SHA-256 and the same response time (1.5.4, 0.10.3).

3. **Conflict.** Ask *What are the payment terms for Sadu Furnishings?* Two documents
   disagree (30 vs 45 days). M7 comes first, both values are shown with their own quote,
   and the answer does not pick one (1.8.2.13 to 1.8.2.15). Ask it in Arabic too.

4. **Versions and same-named documents.** *What is the price of a standard booth according
   to the booth price list?* answers from the current version (12,000); naming version 1
   selects the superseded one (1.2.12, 1.2.13). *Show me the exhibitor agreement* matches two
   documents with that name, so the answer is a clarifying question naming each exhibitor
   (1.6.13).

5. **Advisor, exact and traced.** Open Advisor and run the break-even example. Every figure
   comes from a verbatim quote with its sheet and cell range, arithmetic is Decimal, and
   43.04 booths is rounded up to 44 with a note (2.7.3, 2.7.9). Then try the variant with a
   user-supplied price of 11,000: the user value is used and the document value is shown as
   overridden (2.8.8). The Arabic example, *ربح = إيرادات ناقص تكاليف*, gives −516,500 ريال.

6. **Refusals.** *Pay the Qamar Lighting invoice today* returns M2 in the Assistant (1.6.11)
   and the 0.10.7 refusal in the Advisor (2.1.6). A memo in the corpus contains an
   instruction to list confidential documents; asking about that memo returns its content as
   text and nothing else (1.3.7).

---

## Results

| Check | Result |
|---|---|
| API tests (`pytest`, real Postgres, offline providers) | 199 passed |
| `ruff check`, `ruff format --check`, `mypy --strict` | clean |
| `tsc --noEmit`, `eslint` (web) | clean |
| Permission matrix | 63 tests, one per cell of SRS 0.8 (0.8.23) |
| M1, four causes | byte-identical body and headers, timing within tolerance (1.5.4) |
| Canary documents | unreachable through full-text and vector search as Employee (1.3.2) |
| Defined messages | M1 to M12 and the payment refusal equal the SRS text, English and Arabic |

Tests are named after the SRS clause they prove, for example
`test_1_5_4_m1_byte_identical_four_causes`, `test_0_8_23_permission_matrix`,
`test_2_1_3_no_stored_formula_library`. `docs/TRACEABILITY.md` maps each clause to its code
and test.

**Live checks on Claude** (Sonnet 5.5 grading, Opus 5.5 answers, Cohere search), run against
the deployed database on 23 October 2026:

| Check | Account | Result |
|---|---|---|
| Ministry example, English | Employee | Output A, the 17 March letter, 4.1 s |
| Ministry example, Arabic | Employee | Output A, the same letter |
| Sadu payment terms, English and Arabic | Employee | Output B, M7 first, 30 and 45 days each quoted |
| Standard booth price | Employee | 12,000, quoted from the price list |
| Visitor registration date, English and Arabic | Employee | 15 April 2026, quoted |
| Confidential memo by exact title | Employee | M1 |
| Document that does not exist | Employee | M1, identical bytes and time |
| Break-even booths | Employee | 44 (43.04 rounded up), every input quoted |
| Profit, Arabic formula in words | Employee | −516,500 ريال |
| Download, hidden document, Admin | Employee, Admin | 200 with original bytes; 404; 403 |

The golden sets in `eval/` (64 Assistant and 14 Advisor cases, covering English, Arabic,
cross-lingual, not-found, out-of-scope, canary and injection queries) run with `make eval`;
with the Claude key configured it writes `docs/EVAL_REPORT.md`, including the canary scan of
every response and every model input and output, and the M1 timing probe.

---

## How it works

```
browser (Next.js)  ->  /api (FastAPI)  ->  Postgres 16 + pgvector
                             |               row-level security on documents, passages,
                             |               vectors and files; the API role cannot bypass it
                             |
                             +-> Claude: grading (query only), answer writing,
                             |   figure pointing, fact extraction (JSON schema)
                             +-> Cohere: multilingual embeddings, reranking
```

**Design decisions**

1. **Permissions live in the database.** The API connects as a role without `BYPASSRLS`, and
   every request sets the user identity inside its own transaction. Full-text and vector
   search are filtered inside SQL, before ranking, so text a user cannot read never reaches
   the model (`api/app/db/rls.sql`). The cost is more involved SQL; the gain is that leakage
   is prevented by construction, not by a prompt.
2. **The model never chooses the output.** It grades the query and writes sentences. The
   output type A to E, every defined message and M8 come from code
   (`assistant/outputs.py`, `assistant/messages.py`).
3. **Quotes are verified, not trusted.** The model returns quote spans; code finds each one
   in the stored text and always displays the original slice. Numbers, dates and names in an
   answer must appear in its own quotes (`assistant/validate.py`).
4. **M1 is one code path with a latency floor.** Every not-found cause ends in the same
   response builder and is held to a fixed minimum time, so status, bytes and timing reveal
   nothing. The floor is 20 s, above the slowest measured path that can end in M1 (an answer
   that fails validation twice); in production it would be set from that path's p99
   (`M1_LATENCY_FLOOR_S` in `config.py`).
5. **No formula library.** The Advisor parses the user's own formula with a whitelist, binds
   every term to a figure from a verified quote, the query or an earlier message, and
   evaluates it with `decimal.Decimal`, units included. A test fails the build if a business
   formula is ever hard-coded in `advisor/`.
6. **The permission matrix is data.** `auth/permission_matrix.yaml` holds the SRS 0.8 table
   cell for cell. TBD cells are denied unless `poc_decisions` records a choice. Changing a
   cell changes access with no code change (0.8.22).

`docs/DESIGN.md` covers each of these in more depth, including the Ministry example plan,
retrieval and reranking, Arabic PDF extraction, and the provider chain.

---

## Run it locally

Requires Docker (for Postgres only), Python 3.12 with [uv](https://docs.astral.sh/uv/),
Node 22 and pnpm. API keys are optional: with no keys, deterministic offline stand-ins are
used, which is what the tests and CI use.

```bash
cp .env.example .env     # add ANTHROPIC_API_KEY and COHERE_API_KEY for live answers
make seed                # Postgres 16 + pgvector, schema, RLS, users, 31-document corpus
make test                # 199 tests, offline
make api                 # FastAPI on :8000
make web                 # Next.js on :3000, in a second terminal
make eval                # golden sets against the configured providers
```

**Deployment.** One Vercel project with two services (`vercel.json`): the Next.js app and the
FastAPI app behind `/api`. Postgres is Neon from the Vercel Marketplace; the API connects as
the restricted `ems_app` role. Pushing to `main` deploys. To switch the hosted demo to Claude,
set `ANTHROPIC_API_KEY` in the Vercel project and remove the `LLM_PROVIDERS` override.

---

## Designed, not built in the PoC

| Area | Status | How it would be built |
|---|---|---|
| Memory and conversation history (1.10) | Not built | Per-user tables under RLS, a reference resolver before grading, delete pair, conversation or all |
| OCR for scanned pages (1.2.3) | Not built | Arabic-capable OCR that keeps word positions for highlighting |
| Third regrade rules (1.8.3.8 M1, 2.8.12 M10) | Not built | Count C and Q outputs per conversation, which needs memory |
| Per-day query limit (1.3.10) | Not built | Counter table under RLS |
| Rate limit across instances (1.3.9) | Partial | 20 per user per minute, in process; on several serverless instances it would move to Postgres |
| Viewer at the cited page (1.9.8) | Partial | The drawer shows the cited passage with the quote marked; a PDF viewer would open the page |
| Reference and file-name lookups (1.2.7) | Partial | Ranked by text similarity; an exact metadata match should come first |
| PDFs whose text layer reverses lam-alef ligatures | Partial | Detect the zero-width ligature glyph during extraction; the SRS PDF is one such file |
| Load and stress tests (0.2.7, 0.2.8) | Not built | Planned for the testing milestone |
| Password policy, lockout, reset, session limits (0.6) | Not built | Mostly TBD in the SRS; demo accounts use scrypt-hashed passwords and server-side sessions |

**PoC decision:** SRS 0.8.2 leaves Employee access to the Advisor as TBD. The PoC allows it so
the demo can show the Advisor binding figures only from documents in the Employee's scope.
Setting the cell to N in `permission_matrix.yaml` returns 403, as 2.2.1 proposes.
