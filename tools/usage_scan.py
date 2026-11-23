#!/usr/bin/env python3
"""Measure Claude Code token usage from local transcripts, before vs after a change date.

Reads ~/.claude/projects/**/*.jsonl (main sessions and subagents), deduplicates assistant
messages by requestId, and prints a Markdown report. Nothing leaves your machine.

    python3 tools/usage_scan.py --split 2026-10-29
    python3 tools/usage_scan.py --split 2026-10-29 --since 2026-09-01 --json usage.json

Note: Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30).
Set it to 90+ in ~/.claude/settings.json before you start measuring.
"""
import argparse
import collections
import json
import os
import sys

FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def project_name(encoded_dir, home):
    """`-Users-me-repos-Game` -> `Game`; never prints the home path."""
    prefix = home.replace("/", "-")
    name = encoded_dir[len(prefix):] if encoded_dir.startswith(prefix) else encoded_dir
    name = name.strip("-")
    if name.startswith("repos-"):
        name = name[len("repos-"):]
    if not name or name.startswith(("private-", "var-", "tmp-", "Volumes-")):
        return "(other)"
    return name


def scan(root, since):
    seen = set()
    rows = []  # (project, day, is_subagent, model, counts)
    sessions = {}
    home = os.path.expanduser("~")
    for encoded in sorted(os.listdir(root)):
        pdir = os.path.join(root, encoded)
        if not os.path.isdir(pdir):
            continue
        proj = project_name(encoded, home)
        for dirpath, _, files in os.walk(pdir):
            sub = "subagents" in dirpath.split(os.sep)
            for fn in files:
                if not fn.endswith(".jsonl"):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, errors="replace") as fh:
                    for line in fh:
                        if '"usage"' not in line:
                            continue
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        if d.get("type") != "assistant":
                            continue
                        day = (d.get("timestamp") or "")[:10]
                        msg = d.get("message") or {}
                        key = d.get("requestId") or msg.get("id")
                        model = msg.get("model", "?")
                        if day < since or key in seen or model == "<synthetic>":
                            continue
                        seen.add(key)
                        u = msg.get("usage") or {}
                        c = [u.get(f) or 0 for f in FIELDS]
                        rows.append((proj, day, sub, model, c))
                        if not sub:
                            s = sessions.setdefault(path, {"proj": proj, "first": day, "last": day,
                                                           "turns": 0, "peak": 0, "tokens": 0})
                            s["first"], s["last"] = min(s["first"], day), max(s["last"], day)
                            s["turns"] += 1
                            s["peak"] = max(s["peak"], c[0] + c[2] + c[3])
                            s["tokens"] += sum(c)
    return rows, list(sessions.values())


def family(model):
    for f in ("fable", "opus", "sonnet", "haiku"):
        if f in model:
            return f
    return "other"


def fmt(n):
    return f"{n / 1e9:.2f}B" if n >= 1e9 else f"{n / 1e6:.0f}M" if n >= 1e6 else f"{n / 1e3:.0f}K"


def report(rows, sessions, split):
    period = lambda day: "before" if day < split else "after"
    days = collections.defaultdict(set)
    tot = collections.defaultdict(lambda: [0, 0, 0, 0, 0])  # in, out, cw, cr, turns
    proj = collections.defaultdict(collections.Counter)
    fam = collections.defaultdict(collections.Counter)
    for p, day, sub, model, c in rows:
        per = period(day)
        days[per].add(day)
        t = tot[per]
        for i in range(4):
            t[i] += c[i]
        t[4] += 1
        proj[p][per] += sum(c)
        fam[(per, "subagent" if sub else "main")][family(model)] += sum(c)

    out = [f"# Token usage, split at {split}\n", "| Metric | Before | After |", "|---|---:|---:|"]
    def cell(per, fn):
        return fn(tot[per], len(days[per])) if tot[per][4] else "-"
    metrics = [
        ("Active days", lambda t, n: str(n)),
        ("Total tokens", lambda t, n: fmt(sum(t[:4]))),
        ("Turns (API calls)", lambda t, n: f"{t[4]:,}"),
        ("Tokens / active day", lambda t, n: fmt(sum(t[:4]) / n)),
        ("Tokens / turn", lambda t, n: fmt(sum(t[:4]) / t[4])),
        ("Cache-read share", lambda t, n: f"{100 * t[3] / max(1, sum(t[:4])):.0f}%"),
        ("Output tokens", lambda t, n: fmt(t[1])),
    ]
    for label, fn in metrics:
        out.append(f"| {label} | {cell('before', fn)} | {cell('after', fn)} |")

    out += ["\n## Sessions (main transcripts)\n", "| Metric | Before | After |", "|---|---:|---:|"]
    by = {k: [s for s in sessions if period(s["first"]) == k] for k in ("before", "after")}
    def sess(k, fn):
        return fn(by[k]) if by[k] else "-"
    smetrics = [
        ("Sessions", lambda s: str(len(s))),
        ("Peak context", lambda s: fmt(max(x["peak"] for x in s))),
        ("Sessions with context > 500K", lambda s: str(sum(x["peak"] > 500_000 for x in s))),
        ("Sessions spanning > 1 day", lambda s: str(sum(x["first"] != x["last"] for x in s))),
        ("Median turns / session", lambda s: str(sorted(x["turns"] for x in s)[len(s) // 2])),
    ]
    for label, fn in smetrics:
        out.append(f"| {label} | {sess('before', fn)} | {sess('after', fn)} |")

    out += ["\n## Model mix (share of tokens)\n", "| Period / kind | fable | opus | sonnet | haiku |", "|---|---:|---:|---:|---:|"]
    for key in sorted(fam):
        c = fam[key]
        total = max(1, sum(c.values()))
        out.append(f"| {key[0]} / {key[1]} | " + " | ".join(f"{100 * c[f] / total:.0f}%" for f in ("fable", "opus", "sonnet", "haiku")) + " |")

    out += ["\n## Projects\n", "| Project | Before | After |", "|---|---:|---:|"]
    for p, c in sorted(proj.items(), key=lambda kv: -sum(kv[1].values()))[:15]:
        out.append(f"| {p} | {fmt(c['before'])} | {fmt(c['after'])} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", required=True, help="YYYY-MM-DD; days before it count as 'before'")
    ap.add_argument("--since", default="2000-01-01", help="ignore days before YYYY-MM-DD")
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--json", help="also write raw rows + sessions to this file")
    a = ap.parse_args()
    rows, sessions = scan(a.root, a.since)
    if not rows:
        sys.exit("no transcripts found under " + a.root)
    print(report(rows, sessions, a.split))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"rows": rows, "sessions": sessions}, fh)


if __name__ == "__main__":
    main()
