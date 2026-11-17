# AI Usage

This project was built with AI assistance. This document records how it was used, what the author decided, and how AI-produced work was checked.

## Tooling

- **Claude Code** (model: Claude Opus 5.5), used in VS Code as a pair-programming agent.
- **`CLAUDE.md`** (repo root): the context file Claude Code reads at the start of each session. It holds the requirements, data model, known data gotchas and expected results. It was generated with `/init`, reviewed by the author, and is kept in the repo on purpose as part of the workflow.

## Principles

1. **The author decides; the AI proposes.** Design choices are made by the author and recorded with their reasons in [PLAN.md](PLAN.md).
2. **AI output is not trusted without checking.** Every claim about results is backed by tests, or by values the author re-derived by hand (see PLAN.md §5).
3. **Separate checks.** The SQL cross-check test is a second implementation of the same reports. It exists to catch mistakes in the main code, whether they came from a person or a model.
4. **No code the author can't explain.** Everything committed has been read and understood by the author.

## Session log

| Date | Activity | AI contribution | Author decision / verification |
|---|---|---|---|
| 2026-11-17 | Repo setup | Read the requirements and the CSVs; generated `CLAUDE.md`, including data gotchas (`sponsor_id` header vs "Primary Sponsor" in the requirements, the `bills.csv` name collision, the unknown sponsor `400100`, Yarmuth with no votes) and expected counts | Reviewed `CLAUDE.md`; expected counts to be re-derived by the author from the CSVs (Day 1) |
| 2026-11-17 | Planning | Drafted a plan. Proposed using the standard library instead of pandas. Pointed out that the O(L+V) memory target rules out duplicate detection (O(R)) | Chose the standard library. Asked for Docker Compose to make running easy for others. Set the streaming time/memory target. Asked for AI use to be documented |

_New sessions are added as the work continues._
