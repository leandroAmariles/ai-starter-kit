#!/usr/bin/env python
"""Claude Code statusline: shows the most recent turn's input/output tokens
plus the running session cost, and (if the current git branch matches a
`specs/<branch>/` directory — the spec-kit convention) accumulates that
turn's tokens into `specs/<branch>/.token-usage.json` so a feature's PR
description can report a real, cumulative total.

Coverage note: this only sees turns that go through the MAIN statusline,
i.e. the main conversation thread. Tokens spent by subagents (the Agent/
Task tool) are not included — there is no documented, verified way to
capture those today (see commit-and-push/SKILL.md for how the total is
labeled in the PR body to keep this honest).

Reads the JSON payload Claude Code pipes to this script's stdin after every
response; see https://code.claude.com/docs/en/statusline
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # Windows terminals default stdout to cp1252, which can't encode the
    # 🤖 emoji below.
    sys.stdout.reconfigure(encoding="utf-8")

# Official Anthropic API pricing, USD per 1M tokens (cached 2026-06-24 via
# this kit's own claude-api skill — anthropic.com/pricing is the live
# source). Override with TOKEN_PRICE_INPUT_USD_PER_MTOK /
# TOKEN_PRICE_OUTPUT_USD_PER_MTOK for a different rate (e.g. partner/Bedrock
# pricing, or a future model this table hasn't been updated for).
DEFAULT_PRICING_PER_MTOK = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
# Falls back to Sonnet 5's rate for an unrecognized model id — this kit's
# projects default to Sonnet 5, so it's the more representative guess than
# picking Opus or Haiku's rate for an unknown model.
FALLBACK_PRICING_PER_MTOK = DEFAULT_PRICING_PER_MTOK["claude-sonnet-5"]


def _price_per_mtok(model_id: str | None) -> tuple[float, float]:
    env_in = os.environ.get("TOKEN_PRICE_INPUT_USD_PER_MTOK")
    env_out = os.environ.get("TOKEN_PRICE_OUTPUT_USD_PER_MTOK")
    if env_in and env_out:
        try:
            return float(env_in), float(env_out)
        except ValueError:
            pass  # fall through to the built-in table on a malformed override
    if model_id and model_id in DEFAULT_PRICING_PER_MTOK:
        return DEFAULT_PRICING_PER_MTOK[model_id]
    return FALLBACK_PRICING_PER_MTOK


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
    """Read the branch name straight from .git/HEAD — no subprocess, so this
    stays fast enough to run after every single turn. Returns None on a
    detached HEAD (nothing sensible to track in that case)."""
    try:
        content = (repo_root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if content.startswith("ref:"):
        return content.rsplit("/", 1)[-1]
    return None


TOOL_KEY = "claude"


def _track_spec_usage(cwd: str | None, in_tok, out_tok, model_id: str | None) -> None:
    """Best-effort: accumulate this turn's tokens into
    specs/<branch>/.token-usage.json (under this tool's own top-level key,
    so Claude and Copilot — or any other agent with an equivalent script —
    can accumulate into the SAME file without clobbering each other) when
    the current branch matches an existing specs/ subdirectory (the
    spec-kit convention: branch "001-foo" <-> specs/001-foo/). Silently
    does nothing otherwise — this must never break the statusline for repos
    that don't use spec-kit."""
    if not cwd or in_tok is None or out_tok is None:
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

    price_in, price_out = _price_per_mtok(model_id)
    turn_cost = (in_tok / 1_000_000) * price_in + (out_tok / 1_000_000) * price_out

    entry = all_tools.get(TOOL_KEY) or {}
    entry["input_tokens"] = entry.get("input_tokens", 0) + in_tok
    entry["output_tokens"] = entry.get("output_tokens", 0) + out_tok
    entry["cost_usd"] = round(entry.get("cost_usd", 0.0) + turn_cost, 6)
    entry["turns"] = entry.get("turns", 0) + 1
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
    entry["note"] = (
        "Claude Code main-thread tokens only; excludes subagent/Task-tool calls. "
        "cost_usd is an estimate from published per-token pricing (or "
        "TOKEN_PRICE_*_USD_PER_MTOK if set) — not an authoritative bill; see /usage."
    )
    all_tools[TOOL_KEY] = entry

    try:
        usage_file.write_text(json.dumps(all_tools, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # never let a write failure break the statusline


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("statusline: waiting for data...")
        return

    model_info = data.get("model") or {}
    model = model_info.get("display_name", "Claude")
    model_id = model_info.get("id")
    cost = data.get("cost") or {}
    total_cost = cost.get("total_cost_usd")
    ctx = data.get("context_window") or {}
    current = ctx.get("current_usage") or {}
    in_tok = current.get("input_tokens")
    out_tok = current.get("output_tokens")
    used_pct = ctx.get("used_percentage")

    _track_spec_usage(data.get("cwd"), in_tok, out_tok, model_id)

    parts = [f"🤖 {model}"]

    if in_tok is not None or out_tok is not None:
        parts.append(f"turn in:{fmt_tokens(in_tok)} out:{fmt_tokens(out_tok)}")

    if total_cost is not None:
        parts.append(f"session:${total_cost:.4f}")

    if used_pct is not None:
        parts.append(f"ctx:{used_pct}%")

    print(" · ".join(parts))


if __name__ == "__main__":
    main()
