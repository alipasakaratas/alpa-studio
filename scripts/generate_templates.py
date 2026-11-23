#!/usr/bin/env python3
"""Generate deterministic project templates. No external dependencies."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "templates/project"

ROLES = {
    "studio-director": ("Selects only the roles needed and coordinates the studio.", "Read, Grep, Glob, Agent"),
    "producer": ("Plans milestones, dependencies, risks, and owner gates.", "Read, Grep, Glob"),
    "product-manager": ("Defines audience, product outcomes, scope, and metrics.", "Read, Grep, Glob, WebSearch, WebFetch"),
    "game-director": ("Owns coherent game vision inside approved decisions.", "Read, Grep, Glob"),
    "game-designer": ("Designs rules, loops, progression, and player feedback.", "Read, Grep, Glob"),
    "systems-designer": ("Designs interacting game systems and balance models.", "Read, Grep, Glob"),
    "level-designer": ("Builds and validates levels, pacing, and difficulty.", "Read, Grep, Glob"),
    "economy-designer": ("Designs ethical currencies, rewards, and sinks.", "Read, Grep, Glob"),
    "narrative-designer": ("Designs story, characters, dialogue, and world logic.", "Read, Grep, Glob"),
    "technical-director": ("Owns technical quality, budgets, and integration decisions.", "Read, Grep, Glob, Bash"),
    "unity-architect": ("Designs maintainable Unity architecture and boundaries.", "Read, Grep, Glob"),
    "unity-developer": ("Implements tested Unity gameplay and presentation code.", "Read, Grep, Glob, Edit, Write, Bash"),
    "editor-tools-engineer": ("Builds safe Unity Editor automation and validation tools.", "Read, Grep, Glob, Edit, Write, Bash"),
    "build-engineer": ("Owns deterministic local builds and CI-ready build scripts.", "Read, Grep, Glob, Edit, Write, Bash"),
    "ios-engineer": ("Handles iOS build, signing diagnostics, and device constraints.", "Read, Grep, Glob, Bash"),
    "android-engineer": ("Handles Android builds, emulators, devices, and store constraints.", "Read, Grep, Glob, Bash"),
    "backend-engineer": ("Designs optional online services with offline-safe fallbacks.", "Read, Grep, Glob, Edit, Write"),
    "data-analyst": ("Defines event schemas, metrics, experiments, and truthful analyses.", "Read, Grep, Glob"),
    "art-director": ("Owns the approved Art Bible and cross-asset consistency.", "Read, Grep, Glob"),
    "concept-artist": ("Creates three distinct original visual concept directions.", "Read, Grep, Glob"),
    "ui-ux-designer": ("Designs readable mobile flows, layouts, and interactions.", "Read, Grep, Glob"),
    "2d-artist": ("Produces 2D asset specifications within the approved style.", "Read, Grep, Glob"),
    "3d-artist": ("Produces topology, material, rig, and export specifications.", "Read, Grep, Glob, Bash"),
    "technical-artist": ("Bridges art and Unity under performance budgets.", "Read, Grep, Glob, Bash"),
    "animator": ("Designs readable, responsive animation systems and clips.", "Read, Grep, Glob"),
    "vfx-artist": ("Designs performant mobile effects and motion-reduction variants.", "Read, Grep, Glob"),
    "audio-director": ("Owns sonic identity, budgets, and licensing evidence.", "Read, Grep, Glob"),
    "composer": ("Specifies original adaptive music and loop requirements.", "Read, Grep, Glob"),
    "sound-designer": ("Specifies original feedback, ambience, and mix behavior.", "Read, Grep, Glob"),
    "localization": ("Owns internationalization, translation quality, and text fit.", "Read, Grep, Glob"),
    "accessibility": ("Audits motor, visual, hearing, cognitive, and motion access.", "Read, Grep, Glob"),
    "child-safety": ("Audits age-appropriate design, parental gates, and dark patterns.", "Read, Grep, Glob, WebSearch, WebFetch"),
    "privacy-security": ("Audits data minimization, secrets, SDKs, and attack surfaces.", "Read, Grep, Glob, Bash"),
    "copyright": ("Tracks provenance, licenses, similarity, and rights risks.", "Read, Grep, Glob, WebSearch, WebFetch"),
    "qa-lead": ("Coordinates independent test stages and evidence completeness.", "Read, Grep, Glob, Bash"),
    "gameplay-qa": ("Tests rules, regressions, edge cases, and deterministic behavior.", "Read, Grep, Glob, Edit, Write, Bash"),
    "visual-qa": ("Independently scores in-engine visuals against approved references.", "Read, Grep, Glob"),
    "performance-qa": ("Profiles frame time, memory, loading, thermal, and battery risk.", "Read, Grep, Glob, Bash"),
    "device-lab": ("Runs truthful simulator, emulator, and physical-device matrices.", "Read, Grep, Glob, Bash"),
    "research-analyst": ("Builds source-backed market and design research.", "Read, Grep, Glob, WebSearch, WebFetch"),
    "competitor-analyst": ("Compares current competitors from primary store evidence.", "Read, Grep, Glob, WebSearch, WebFetch"),
    "review-miner": ("Extracts recurring player needs from cited real reviews.", "Read, Grep, Glob, WebSearch, WebFetch"),
    "monetization-auditor": ("Audits ethical ads, IAP, pricing, and owner approval gates.", "Read, Grep, Glob"),
    "release-manager": ("Prepares release evidence but never publishes without approval.", "Read, Grep, Glob, Bash"),
    "continuity-manager": ("Maintains checkpoints, handoffs, queue state, and session rotation.", "Read, Grep, Glob, Bash"),
    "resource-manager": ("Schedules model, hardware, disk, and concurrency conservatively.", "Read, Grep, Glob, Bash"),
}

OPUS_ROLES = {
    "studio-director", "product-manager", "game-director", "game-designer", "systems-designer",
    "level-designer", "economy-designer", "narrative-designer", "technical-director",
    "unity-architect", "art-director", "concept-artist", "ui-ux-designer", "2d-artist",
    "3d-artist", "technical-artist", "animator", "vfx-artist", "audio-director", "composer",
    "sound-designer", "accessibility", "unity-developer", "editor-tools-engineer",
    "build-engineer", "backend-engineer", "visual-qa",
}
HAIKU_ROLES = {"continuity-manager", "resource-manager"}

# Role-specific lines appended after the shared agent body.
EXTRA_LINES = {
    "gameplay-qa": "- You write and run all test code (EditMode and PlayMode) under `Assets/_Project/Tests/`. Do not edit production code; report failures to the implementer.\n",
    "unity-developer": "- You write production code only. Test code is written and run by gameplay-qa (sonnet); do not write tests yourself.\n",
}


def model_for(name: str) -> str:
    if name in OPUS_ROLES:
        return "opus"
    if name in HAIKU_ROLES:
        return "haiku"
    return "sonnet"

AGENT_BODY = """---
name: {name}
description: {description}
model: {model}
tools: {tools}
---

You are the Alpa Studio **{name}** specialist.

- Read `docs/studio/STATUS.md`, `DECISIONS.md`, `GAME-BIBLE.md`, and `ART-BIBLE.md` before material work.
- Treat owner-approved decisions as immutable. Propose a change request; never silently replace them.
- Record claims from competitors, videos, reviews, policies, or research with a real URL and capture date.
- Do not use paid services, publish, upload, merge, force-push, or alter credentials without explicit owner approval.
- Distinguish verified evidence from assumptions and planned work.
- Return a concise handoff with files changed, tests run, evidence, risks, and pending approval IDs.
"""

for name, (description, tools) in ROLES.items():
    path = T / ".claude/agents" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        AGENT_BODY.format(name=name, description=description, model=model_for(name), tools=tools)
        + EXTRA_LINES.get(name, ""),
        encoding="utf-8",
    )

catalog = "# Role catalog\n\nRoles are selected per task; loading all roles is discouraged.\n\n" + "\n".join(
    f"- `{name}` (`{model_for(name)}`) — {description}" for name, (description, _) in ROLES.items()
) + "\n"
(T / "docs/studio/ROLE-CATALOG.md").parent.mkdir(parents=True, exist_ok=True)
(T / "docs/studio/ROLE-CATALOG.md").write_text(catalog, encoding="utf-8")
print(f"Generated {len(ROLES)} project-scoped Claude agents")

