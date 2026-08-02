from __future__ import annotations

import argparse
from pathlib import Path

from .runner import RunnerError, run_from_environment


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one queued ADP handoff locally")
    parser.add_argument("agent", choices=("claude", "codex", "gemini"))
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()
    try:
        return run_from_environment(args.agent, args.db_path)
    except RunnerError as exc:
        parser.exit(1, f"adp-runner: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
