---
name: backend-infra-completion-report
description: Generate a self-contained HTML completion report for backend, infrastructure, deployment, migration, architecture, security, compatibility, and operations tasks.
uuid: a43a68f9-fda2-4960-a49a-0a97ebf96a8a
language: en
review_version: "1.0.0"
generated_at: "2026-05-25"
report_family: completion-report-html
recommended_output: out/report.html
recommended_mode: custom-skill-profile
primary_use_case: backend-infrastructure-completion-report
status: recommended
related_skills:
  - skill-creator
  - theme-factory
  - web-artifacts-builder: optional-only
dependencies:
  - python>=3.10
  - jinja2>=3.1
  - pyyaml>=6.0
  - markdown-it-py>=3.0
  - beautifulsoup4>=4.12
---

# Backend / Infrastructure Completion Report Skill

## Verdict

Use a dedicated **backend-infra profile** inside a common `completion-report-html` Skill.

The report should be document-first, evidence-heavy, and easy to audit. Output: `out/report.html` (self-contained).

## Recommended Output Structure

Sections:

1. Executive summary
2. Scope and assumptions
3. Target environment
4. Completion checklist
5. Architecture overview
6. Infrastructure topology
7. Implementation steps
8. Configuration changes
9. Validation evidence
10. Security review
11. Compatibility and deprecated notes
12. Operational impact
13. Rollback plan
14. Remaining work
15. Appendix: commands, logs, config snippets, raw evidence

## HTML Layout

```text
Header: title, date, status, completion%, risk level
Left nav: section anchors
Main: summary cards, step timeline, architecture diagram, evidence tables, risk/compat blocks, appendix
```

## Architecture Diagram Strategy

1. Inline SVG (preferred)
2. Mermaid → SVG at build time
3. ASCII (simple topology only)

Avoid external CDN assets.

## Acceptance Criteria

- `out/report.html` opens directly in a browser
- All critical steps have status and evidence
- Architecture visible without network access
- Security and compatibility sections present
- Deprecated/legacy items explicitly identified
- Rollback instructions for risky changes
- Appendix with commands/logs/config evidence
