# Panels

## Tiers

| Tier | Seats (`ship:` prefix) | Use |
|---|---|---|
| `light` | `reviewer--deepseek-flash`, `reviewer--glm-flash`, `reviewer--luna` | Cheap checks |
| `design` | `reviewer--astra`, `reviewer--fable`, `reviewer--glm`, `reviewer--deepseek` | Design and architecture |
| `high` (default) | `reviewer--sol-max`, `reviewer--glm`, `reviewer--deepseek` | Plan refutation and branch review |
| `final` | `reviewer--sol56-max`, `reviewer--fable`, `reviewer--glm`, `reviewer--deepseek`, `reviewer--kimi` | Final review before push |

`reviewer--fable` is a required seat in `design` and `final`. When it is unavailable, `reviewer--astra` takes the seat; in `design`, where Astra already sits, the panel counts one Astra seat and is incomplete. `reviewer--kimi` is a trial seat until 2026-10-09; its absence does not make the panel incomplete.

Model families for vote counting: OpenAI (`sol`, `sol56`, `astra`, `luna`), Anthropic (`fable`, `opus`, `sonnet`), GLM, DeepSeek, Kimi.

## Challenge lenses

| Type | Persona names |
|------|---------------|
| `code-audit` | `security-analyst`, `performance-engineer`, `dx-advocate`, `maintainability-architect` |
| `architecture` | `systems-architect`, `devops-sre`, `product-engineer`, `cost-optimizer` |
| `data-model` | `database-architect`, `api-designer`, `compliance-officer`, `migration-specialist` |
| `feature-plan` | `product-manager`, `tech-lead`, `qa-strategist`, `ux-advocate` |
| `security` | `penetration-tester`, `compliance-officer`, `incident-responder`, `supply-chain-analyst` |
| `cost-decision` | `cfo-finops`, `platform-engineer`, `growth-lead`, `risk-analyst` |
| `migration` | `migration-specialist`, `rollback-specialist`, `data-integrity-auditor`, `devops-sre` |
| `custom` | 3 to 6 distinct names from the bundled persona roster |

The roster is the `.md` filenames in `${CLAUDE_SKILL_DIR}/personas/`, except `_format.md`. Every seat applies every selected lens in one combined report.
