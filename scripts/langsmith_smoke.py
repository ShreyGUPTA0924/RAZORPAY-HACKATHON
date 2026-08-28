"""
LangSmith tracing smoke test.

Makes one real LLM call through pipeline.llm_clients.get_chat_model() and
then reads the resulting run back from LangSmith's API (not just "the call
didn't error") -- this is the difference between "tracing is configured" and
"tracing is actually landing in the dashboard."

Usage:
    python scripts/langsmith_smoke.py                  # traces the extractor (Gemini)
    python scripts/langsmith_smoke.py --component adversarial_generator  # traces Groq instead
"""

import argparse
import sys
import time
import warnings

from langchain_core.tracers.context import collect_runs
from langsmith import Client

from pipeline.llm_clients import get_chat_model
from pipeline.tracing import configure_tracing, tracing_status

READ_BACK_ATTEMPTS = 6
READ_BACK_DELAY_S = 2.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--component",
        default="extractor",
        help="pipeline.llm_config component to trace through (default: extractor).",
    )
    args = parser.parse_args()

    print("=" * 72)
    if not configure_tracing():
        print("REFUSING: LANGCHAIN_API_KEY not set in .env -- tracing is not configured.", file=sys.stderr)
        sys.exit(1)
    status = tracing_status()
    print(f"Tracing configured: project={status['project']!r}, enabled={status['tracing_enabled']}")

    print(f"\n[1/2] Calling get_chat_model({args.component!r}).invoke(...) with a trivial prompt...")
    model = get_chat_model(args.component)
    with collect_runs() as runs_cb:
        response = model.invoke("Reply with exactly one word: ok")
    print(f"      Model replied: {response.content!r}")

    if not runs_cb.traced_runs:
        print("      FAILED: no run was collected locally -- tracing callback did not fire.", file=sys.stderr)
        sys.exit(1)
    run_id = runs_cb.traced_runs[0].id
    print(f"      Local run id captured: {run_id}")

    print("\n[2/2] Reading that run back from the LangSmith API (proves it actually landed)...")
    client = Client()
    run = None
    # read_run()/get_run_url() are deprecated in favor of the async client.runs.*
    # resource (not migrating here -- this script is meant to stay simple sync
    # code, not the reason to introduce asyncio into a smoke test).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for attempt in range(1, READ_BACK_ATTEMPTS + 1):
            try:
                run = client.read_run(run_id)
                break
            except Exception as e:  # noqa: BLE001 -- expected 404 while ingestion catches up; retry loop handles it
                print(f"      attempt {attempt}/{READ_BACK_ATTEMPTS}: not readable yet ({e}); retrying...")
                time.sleep(READ_BACK_DELAY_S)

        if run is None:
            print(
                f"      FAILED: run {run_id} was never readable back from LangSmith's API after "
                f"{READ_BACK_ATTEMPTS} attempts. The call succeeded locally but nothing confirms "
                f"it reached the dashboard.",
                file=sys.stderr,
            )
            sys.exit(1)

        url = client.get_run_url(run=run)
    print(f"      OK  LangSmith confirms run {run.id} exists (name={run.name!r}, status={run.status!r})")
    print(f"\n      Trace URL: {url}")
    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
