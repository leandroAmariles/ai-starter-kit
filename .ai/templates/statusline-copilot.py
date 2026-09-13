#!/usr/bin/env python
"""GitHub Copilot CLI statusline: shows running session token usage, and (if
the current git branch matches a `specs/<branch>/` directory — the spec-kit
convention) accumulates each turn's tokens into
`specs/<branch>/.token-usage.json`, under this tool's own "copilot" key, so
the commit-and-push skill can report a real total in that spec's PR.

Schema caveat: unlike Claude Code, Copilot CLI's statusline payload only
exposes CUMULATIVE session totals (context_window.total_input_tokens /
total_output_tokens), not a per-turn delta — this script computes the delta
itself by remembering the previous cumulative total per session_id (see
_delta_tokens below). The exact field names here come from a third-party
walkthrough, not an Anthropic-style dedicated reference page — if nothing
shows up after restarting Copilot CLI, run `/statusline` inside a Copilot
CLI session to confirm/re-point it at this script, and check the actual
payload with a diagnostic script (print `data` to a file) if fields differ.

Coverage note: like the Claude version, this only sees turns that go
through Copilot CLI's own statusline — not other tools working on the same
spec (see commit-and-push/SKILL.md for how totals are broken down by tool
in the PR body to keep this honest).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

TOOL_KEY = "copilot"
STATE_DIR = Path.home() / ".copilot" / ".statusline-state"

# Unlike Claude Code, GitHub Copilot has no published official $/token rate
# to default to — it bills through usage-based AI credits, not a per-model
# per-token price. So there's no built-in pricing table here: cost is only
# computed if you set TOKEN_PRICE_INPUT_USD_PER_MTOK /
# TOKEN_PRICE_OUTPUT_USD_PER_MTOK yourself (e.g. from your own effective
# credit-to-dollar rate). Same env var names as the Claude script, so
# setting them once applies to both.


def _price_per_mtok() -> tuple[float, float] | None:
    env_in = os.environ.get("TOKEN_PRICE_INPUT_USD_PER_MTOK")
    env_out = os.environ.get("TOKEN_PRICE_OUTPUT_USD_PER_MTOK")
    if not env_in or not env_out:
        return None
    try:
        return float(env_in), float(env_out)
    except ValueError:
        return None


def fmt_tokens(n):
    if n is None:
        return "?"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _find_repo_root(start: str) -> Path | None:
    try:
        p = Path(start).resolve()
    except Exception:
        return None
    for candidate in (p, *p.parents):
        if (candidate / ".git").is_dir():
            return candidate
    return None


def _current_branch(repo_root: Path) -> str | None:
    try:
        content = (repo_root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if content.startswith("ref:"):
        return content.rsplit("/", 1)[-1]
    return None


def _delta_tokens(session_id: str | None, total_in, total_out) -> tuple[int, int]:
    """Copilot's payload only gives session-cumulative totals. Diff against
    the last-seen cumulative total (persisted per session_id) to recover
    this turn's actual delta — never negative (a lower total than last seen
    means a new/reset session, not a refund)."""
    if not session_id or total_in is None or total_out is None:
        return 0, 0
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / f"{session_id}.json"
        prev = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    except Exception:
        prev = {}

    prev_in = prev.get("total_input_tokens", 0)
    prev_out = prev.get("total_output_tokens", 0)
    delta_in = max(0, total_in - prev_in)
    delta_out = max(0, total_out - prev_out)

    try:
        state_file.write_text(
            json.dumps({"total_input_tokens": total_in, "total_output_tokens": total_out}),
            encoding="utf-8",
        )
    except Exception:
        pass

    return delta_in, delta_out


def _track_spec_usage(cwd: str | None, delta_in: int, delta_out: int) -> None:
    if not cwd or (delta_in == 0 and delta_out == 0):
        return
    repo_root = _find_repo_root(cwd)
    if repo_root is None:
        return
    branch = _current_branch(repo_root)
    if not branch:
        return
    spec_dir = repo_root / "specs" / branch
    if not spec_dir.is_dir():
        return

    usage_file = spec_dir / ".token-usage.json"
    try:
        all_tools = json.loads(usage_file.read_text(encoding="utf-8")) if usage_file.exists() else {}
    except Exception:
        all_tools = {}
    if not isinstance(all_tools, dict):
        all_tools = {}

    entry = all_tools.get(TOOL_KEY) or {}
    entry["input_tokens"] = entry.get("input_tokens", 0) + delta_in
    entry["output_tokens"] = entry.get("output_tokens", 0) + delta_out
    price = _price_per_mtok()
    if price is not None:
        price_in, price_out = price
        turn_cost = (delta_in / 1_000_000) * price_in + (delta_out / 1_000_000) * price_out
        entry["cost_usd"] = round(entry.get("cost_usd", 0.0) + turn_cost, 6)
    entry["turns"] = entry.get("turns", 0) + 1
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
    entry["note"] = (
        "GitHub Copilot CLI tokens only (delta of session cumulative totals); excludes other "
        "tools. cost_usd is only present if TOKEN_PRICE_*_USD_PER_MTOK was set — Copilot has no "
        "published official per-token rate to default to (it bills via AI credits)."
    )
    all_tools[TOOL_KEY] = entry

    try:
        usage_file.write_text(json.dumps(all_tools, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("statusline: waiting for data...")
        return

    model = (data.get("model") or {}).get("display_name", "Copilot")
    ctx = data.get("context_window") or {}
    total_in = ctx.get("total_input_tokens")
    total_out = ctx.get("total_output_tokens")
    used_pct = ctx.get("used_percentage")
    session_id = data.get("session_id")

    delta_in, delta_out = _delta_tokens(session_id, total_in, total_out)
    _track_spec_usage(data.get("cwd"), delta_in, delta_out)

    parts = [f"🧑‍💻 {model}"]

    if total_in is not None or total_out is not None:
        parts.append(f"session in:{fmt_tokens(total_in)} out:{fmt_tokens(total_out)}")

    if used_pct is not None:
        parts.append(f"ctx:{used_pct}%")

    print(" · ".join(parts))


if __name__ == "__main__":
    main()
