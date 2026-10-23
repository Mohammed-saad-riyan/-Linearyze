"""Run the golden sets and write docs/EVAL_REPORT.md.

    cd api && uv run python ../eval/run_eval.py [--throttle 6] [--m1-url https://...]

Uses whatever database and providers the environment configures (see .env.example). With
no API keys it runs the offline stand-ins, which is a smoke test of the pipeline, not a
measure of answer quality; the report says which providers produced it.

What it measures (SRS 1.14, 2.14):
- output type, documents and quote content per golden case
- every displayed quote is the exact slice of its stored passage (1.8.2.9)
- every sentence passes the number, date and name check again (1.8.2.12)
- canary leakage: each canary token is searched for in every response body and in every
  model input and output recorded during the Employee runs (1.3.2)
- optionally, M1 bytes and timing over HTTP against a deployed instance (1.5.4)
"""

import argparse
import datetime as dt
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app import llm  # noqa: E402
from app.advisor import pipeline as advisor  # noqa: E402
from app.assistant import pipeline as assistant  # noqa: E402
from app.assistant.validate import check_sentence  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.session import as_owner, as_user  # noqa: E402
from app.text.arabic import normalize  # noqa: E402

TODAY = dt.date(2026, 5, 1)
MANIFEST = yaml.safe_load((ROOT / "seed/corpus_manifest.yaml").read_text())["documents"]
CANARIES = sorted(d["canary"] for d in MANIFEST if "canary" in d)
M1_PROBES = {
    "does not exist": "Give me the Riyadh Marathon sponsorship contract",
    "no access": "Give me the Board Memo - Executive Bonus Pool 2026",
    "below threshold": "What colour are the volunteer uniforms?",
    "not yet indexed": "Give me the sponsorship proposal",
}

model_traffic: list[str] = []  # every model input and output, for the canary scan


def _record_llm() -> None:
    original = llm.structured

    def recording(prompt_name: str, user_content: str, schema: Any, **kwargs: Any) -> Any:
        model_traffic.append(user_content)
        result = original(prompt_name, user_content, schema, **kwargs)
        model_traffic.append(result.model_dump_json())
        return result

    llm.structured = recording  # type: ignore[assignment]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value] if value is not None else []


def run_assistant(cases: list[dict[str, Any]], users: dict[str, Any], throttle: float) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        started = time.perf_counter()
        error = None
        try:
            with as_user(users[case["user"]]) as conn:
                outcome = assistant.run(conn, case["query"], TODAY, debug=True)
                body = json.loads(outcome.body)
                passages = _passage_texts(conn, body)
        except (llm.LLMUnavailable, llm.LLMTimeout) as exc:
            body, passages, error = {"output": "ERROR"}, {}, type(exc).__name__
        elapsed = time.perf_counter() - started
        results.append(_score_assistant(case, body, passages, elapsed, error))
        print(f"{case['id']:8} {results[-1]['verdict']:5} {body.get('output')} "  # noqa: T201
              f"{body.get('message_id', '')} {elapsed:5.1f}s", flush=True)
        time.sleep(throttle)
    return results


def _passage_texts(conn: Any, body: dict[str, Any]) -> dict[int, str]:
    ids = [c["chunk_id"] for s in body.get("sentences", []) for c in s["citations"]]
    ids += [v["citation"]["chunk_id"] for c in body.get("conflicts", []) for v in c["values"]]
    if not ids:
        return {}
    rows = conn.execute("SELECT id, text_original FROM chunks WHERE id = ANY(%s)", (ids,))
    return {r["id"]: r["text_original"] for r in rows.fetchall()}


def _score_assistant(case: dict[str, Any], body: dict[str, Any], passages: dict[int, str],
                     elapsed: float, error: str | None) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    output = body.get("output")
    checks["output"] = output in case["output"]
    if "message" in case:
        checks["message"] = body.get("message_id") in _as_list(case["message"])
    returned = [d["id"] for d in body.get("documents", [])]
    if "docs" in case:
        checks["docs"] = set(case["docs"]) <= set(returned)
    if "any_docs" in case:
        checks["any_docs"] = bool(set(case["any_docs"]) & set(returned))
    quotes = [c["quote"] for s in body.get("sentences", []) for c in s["citations"]]
    quotes += [v["citation"]["quote"] for c in body.get("conflicts", []) for v in c["values"]]
    if "quote" in case:
        checks["quote"] = any(normalize(w) in normalize(q) for w in case["quote"] for q in quotes)
    if case.get("conflict"):
        checks["conflict"] = bool(body.get("notice")) and len(body.get("conflicts", [])) > 0

    verbatim = [passages[c["chunk_id"]][c["start"]:c["end"]] == c["quote"]
                for s in body.get("sentences", []) for c in s["citations"]
                if c["chunk_id"] in passages]
    grounded = []
    for sentence in body.get("sentences", []):
        cited = {c["chunk_id"]: passages.get(c["chunk_id"], "") for c in sentence["citations"]}
        quotes_for = [(c["chunk_id"], c["quote"]) for c in sentence["citations"]]
        titles = {c["chunk_id"]: _title(c["document_id"]) for c in sentence["citations"]}
        grounded.append(check_sentence(sentence["text"], quotes_for, cited, [], titles).ok)
    return {
        "id": case["id"], "cat": case["cat"], "user": case["user"], "query": case["query"],
        "expected": case["output"], "output": output, "message_id": body.get("message_id"),
        "documents": returned, "checks": checks, "verbatim": verbatim, "grounded": grounded,
        "seconds": round(elapsed, 2), "error": error, "body": body,
        "verdict": "PASS" if checks and all(checks.values()) and not error else "FAIL",
    }


def _title(document_id: str) -> str:
    return next((d["title"] for d in MANIFEST if d["id"] == document_id), "")


def run_advisor(cases: list[dict[str, Any]], users: dict[str, Any], throttle: float) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        started = time.perf_counter()
        error = None
        try:
            with as_user(users[case["user"]]) as conn:
                body = json.loads(advisor.run(conn, case["query"], []).body)
        except (llm.LLMUnavailable, llm.LLMTimeout) as exc:
            body, error = {"output": "ERROR"}, type(exc).__name__
        elapsed = time.perf_counter() - started
        checks = {"output": body.get("output") == case["output"]}
        if "value" in case:
            checks["value"] = (body.get("result") or {}).get("value") == case["value"]
        if "unit" in case:
            checks["unit"] = (body.get("result") or {}).get("unit") == case["unit"]
        if "message" in case:
            checks["message"] = body.get("message_id") == case["message"]
        if "missing" in case:
            checks["missing"] = body.get("missing") == case["missing"]
        if "notice" in case:
            checks["notice"] = bool(body.get("notice"))
        traced = [bool(i.get("citation")) and i["value"] in i["citation"]["quote"]
                  for i in body.get("inputs", []) if i["source_type"] == "document"]
        verdict = "PASS" if all(checks.values()) and not error else "FAIL"
        results.append({"id": case["id"], "user": case["user"], "query": case["query"],
                        "expected": case.get("value") or case.get("message") or case["output"],
                        "got": (body.get("result") or {}).get("value") or body.get("message_id")
                        or body.get("output"), "checks": checks, "traced": traced,
                        "seconds": round(elapsed, 2), "error": error, "body": body,
                        "verdict": verdict})
        print(f"{case['id']:8} {verdict:5} {results[-1]['got']} {elapsed:5.1f}s", flush=True)  # noqa: T201
        time.sleep(throttle)
    return results


def probe_m1(base_url: str, rounds: int) -> dict[str, Any]:
    """Each M1 cause, `rounds` times, as the Employee over HTTP: bytes and seconds."""
    client = httpx.Client(base_url=base_url, timeout=90)
    client.post("/api/auth/login", json={"email": "employee@demo.lnz", "password": "demo-employee"})
    samples: dict[str, list[tuple[str, float]]] = {cause: [] for cause in M1_PROBES}
    for _ in range(rounds):
        for cause, query in M1_PROBES.items():
            started = time.perf_counter()
            response = client.post("/api/assistant/query", json={"query": query})
            samples[cause].append((hashlib.sha256(response.content).hexdigest(),
                                   time.perf_counter() - started))
            time.sleep(4)
    hashes = {h for runs in samples.values() for h, _ in runs}
    medians = {c: statistics.median(s for _, s in runs) for c, runs in samples.items()}
    return {"hashes": sorted(hashes), "medians": medians,
            "spread": max(medians.values()) - min(medians.values()),
            "all": {c: [round(s, 2) for _, s in runs] for c, runs in samples.items()}}


def canary_scan(assistant_results: list[dict[str, Any]],
                advisor_results: list[dict[str, Any]]) -> dict[str, int]:
    employee_bodies = [json.dumps(r["body"], ensure_ascii=False)
                       for r in assistant_results + advisor_results if r["user"] == "employee"]
    haystack = "\n".join(employee_bodies + model_traffic)
    return {token: haystack.count(token) for token in CANARIES}


def pct(values: list[bool]) -> str:
    return f"{100 * sum(values) / len(values):.0f}% ({sum(values)}/{len(values)})" if values else "n/a"


def report(a: list[dict[str, Any]], v: list[dict[str, Any]], leaks: dict[str, int],
           m1: dict[str, Any] | None, providers: str, started: dt.datetime) -> str:
    answerable = [r for r in a if r["expected"] != ["E"]]
    unanswerable_m1 = [r for r in a if r.get("expected") == ["E"] and r["cat"] in ("nf", "canary")]
    ad = [r for r in a if set(r["expected"]) & {"A", "D"}]
    xl = [r for r in a if r["cat"] == "xl"]
    verbatim = [x for r in a for x in r["verbatim"]]
    grounded = [x for r in a for x in r["grounded"]]
    traced = [x for r in v for x in r["traced"]]
    lines = [
        "# Evaluation report",
        "",
        f"Generated by `eval/run_eval.py` on {started:%Y-%m-%d %H:%M} UTC against the deployed "
        f"database (31 documents, 80 passages). Language model chain: {providers}. "
        f"Search: {'Cohere embed-multilingual-v3.0 and rerank-v3.5' if settings.use_live_cohere() else 'offline stand-ins'}.",
        "",
        "Rerun with `cd api && uv run python ../eval/run_eval.py`. Golden sets: "
        "`eval/golden_assistant.yaml`, `eval/golden_advisor.yaml`.",
        "",
        "## Summary",
        "",
        "| Metric | Result | Target proposed in the bid |",
        "|---|---|---|",
        f"| Canary leakage, Employee runs (bodies and every model input and output) | {sum(leaks.values())} / {len(leaks)} tokens found | 0 |",
        f"| Assistant golden cases passing all checks | {pct([r['verdict'] == 'PASS' for r in a])} | ≥ 90% |",
        f"| Output type correct (grading and A to E selection) | {pct([r['checks']['output'] for r in a])} | ≥ 90% |",
        f"| A vs D cases correct (type and documents) | {pct([r['verdict'] == 'PASS' for r in ad])} | ≥ 90% |",
        f"| Quotes verbatim (displayed text equals the stored slice) | {pct(verbatim)} | 100% |",
        f"| Sentences whose numbers, dates and names are in their quotes | {pct(grounded)} | 100% |",
        f"| Correct M1 on unanswerable and restricted queries | {pct([r['message_id'] in ('M1', 'M2') for r in unanswerable_m1])} | ≥ 95% |",
        f"| False M1 on answerable queries | {pct([r['message_id'] == 'M1' for r in answerable])} | ≤ 5% |",
        f"| Cross-lingual: expected document returned | {pct([r['verdict'] == 'PASS' for r in xl])} | ≥ 85% |",
        f"| Advisor golden cases correct | {pct([r['verdict'] == 'PASS' for r in v])} | 100% |",
        f"| Advisor document inputs traced to a quote containing the figure | {pct(traced)} | 100% |",
        f"| Provider errors during the run (M3/M4) | {sum(1 for r in a + v if r['error'])} | 0 |",
    ]
    if m1:
        lines.append(f"| M1 four causes: distinct response bodies | {len(m1['hashes'])} | 1 |")
        lines.append(f"| M1 four causes: spread of median response time | {m1['spread'] * 1000:.0f} ms | within tolerance |")
    lines += ["", "## Assistant cases", "",
              "| Case | User | Query | Expected | Got | Documents | Seconds | Result |",
              "|---|---|---|---|---|---|---|---|"]
    for r in a:
        got = f"{r['output']} {r['message_id'] or ''}".strip()
        failed = [k for k, ok in r["checks"].items() if not ok]
        verdict = r["verdict"] if not failed else f"FAIL ({', '.join(failed)})"
        if r["error"]:
            verdict = f"FAIL ({r['error']})"
        lines.append(f"| {r['id']} | {r['user']} | {r['query']} | {'/'.join(r['expected'])} | {got} | "
                     f"{', '.join(r['documents'][:4])} | {r['seconds']} | {verdict} |")
    lines += ["", "## Advisor cases", "", "| Case | User | Query | Expected | Got | Seconds | Result |",
              "|---|---|---|---|---|---|---|"]
    for r in v:
        failed = [k for k, ok in r["checks"].items() if not ok]
        verdict = r["verdict"] if not failed else f"FAIL ({', '.join(failed)})"
        lines.append(f"| {r['id']} | {r['user']} | {r['query']} | {r['expected']} | {r['got']} | "
                     f"{r['seconds']} | {verdict} |")
    lines += ["", "## Canary scan", "", "| Token | Occurrences |", "|---|---|"]
    lines += [f"| `{t}` | {n} |" for t, n in leaks.items()]
    if m1:
        lines += ["", "## M1 timing (HTTP, Employee, deployed instance)", "",
                  "| Cause | Runs (s) | Median (s) |", "|---|---|---|"]
        lines += [f"| {c} | {', '.join(map(str, runs))} | {m1['medians'][c]:.2f} |"
                  for c, runs in m1["all"].items()]
        lines += ["", f"Distinct SHA-256 of the response bodies across all runs: {len(m1['hashes'])}."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--throttle", type=float, default=0.0,
                        help="seconds between cases, to stay inside provider rate limits")
    parser.add_argument("--m1-url", help="deployed base URL for the M1 timing probe")
    parser.add_argument("--m1-rounds", type=int, default=3)
    parser.add_argument("--out", default=str(ROOT / "docs/EVAL_REPORT.md"))
    args = parser.parse_args()

    started = dt.datetime.now(dt.UTC)
    _record_llm()
    with as_owner() as conn:
        users = {r["role"]: r["id"] for r in conn.execute("SELECT role, id FROM users")}
    golden_a = yaml.safe_load((ROOT / "eval/golden_assistant.yaml").read_text())["cases"]
    golden_v = yaml.safe_load((ROOT / "eval/golden_advisor.yaml").read_text())["cases"]
    a = run_assistant(golden_a, users, args.throttle)
    v = run_advisor(golden_v, users, args.throttle)
    m1 = probe_m1(args.m1_url, args.m1_rounds) if args.m1_url else None
    providers = " → ".join(llm.configured_providers()) if settings.use_live_llm() else "offline stand-ins"
    leaks = canary_scan(a, v)
    Path(args.out).write_text(report(a, v, leaks, m1, providers, started))
    raw = ROOT / "eval/results/latest.json"
    raw.parent.mkdir(exist_ok=True)
    raw.write_text(json.dumps({"assistant": a, "advisor": v, "canaries": leaks, "m1": m1},
                              ensure_ascii=False, indent=1, default=str))
    print(f"wrote {args.out}")  # noqa: T201


if __name__ == "__main__":
    main()
