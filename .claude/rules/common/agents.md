# Agent Orchestration

## Available Agents

Located in `.claude/agents/` (this project):

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| planner | Implementation planning | Complex features, refactoring |
| code-reviewer | Code review | After writing code |
| python-reviewer | Python review | Backend changes |
| typescript-reviewer | TypeScript review | Frontend / mobile changes |
| database-reviewer | PostgreSQL / migrations review | Schema, SQL, Alembic changes |
| security-reviewer | Security analysis | Before deploy, auth / input handling |

Launch these agents when the user asks for it or when the current workflow step calls for it (see `CLAUDE.md`), with the model from `performance.md`.

## Multi-Perspective Analysis

For complex problems, use split role sub-agents:
- Factual reviewer
- Senior engineer
- Security expert
- Consistency reviewer
- Redundancy checker
