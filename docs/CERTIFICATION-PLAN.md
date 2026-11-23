# Certification plan

Certifying a game project means proving, with real evidence, that Alpa Studio runs it end to end under its gates. Each project is certified against its profile (`profiles/example.json` or your own profile JSON); `certification_order` and `depends_on_certification` let a profile wait for another project to pass first.

## Steps per project

1. For a project that already has its own Claude setup, choose the migration strategy (`alpa migrate`, see `docs/MIGRATION.md`).
2. Clean or checkpoint the existing worktree without discarding changes.
3. Run the installer dry-run and review every conflict; apply only after explicit confirmation.
4. Import approved decisions and references without rewriting history; lock them after reconciliation.
5. Record current competitor, gameplay-video, player-review, rights, privacy and store-policy evidence (the profile's `required_evidence_types`).
6. Run Unity EditMode/PlayMode tests, build checks, screenshots, interaction video, performance profile, and the Android emulator/device and iOS Simulator/device matrix as actually available.
7. Independent QA must score at least 95/100, with zero critical decision, rights, privacy, child-safety, release or device-evidence gaps.
8. The owner approves any paid service, store identifiers, signing action, upload and publication separately.

## Child-directed profiles

A profile that lists `child-safety` in `required_roles` adds a parental gate, no ads and no tracking, offline behavior, narration/localization, accessibility, UK/Apple/Google child-policy and real-device requirements. Existing product decisions take precedence until a versioned owner-approved change supersedes them.
