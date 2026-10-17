# Third-party skills

Copied from the owner's GitHub forks on 15 Oct 2026. `scan` and
`liquidity-price-action` are this repository's own; every other folder here
comes from the list below. To update one, re-copy its folder from the fork.

| Source (kkute2118-hash/...) | Commit | Path copied | License |
|---|---|---|---|
| superpowers | bb92a77 | `skills/*` | MIT |
| ui-ux-pro-max-skill | 56ea9cf | `.claude/skills/*` | MIT |
| geo-seo-claude | 989cae0 | `skills/*`, `geo/` | MIT |
| code-review-graph | d72e8fb | `skills/*` | MIT |
| claude-mem | fef3402 | `plugin/skills/*` except `babysit` | Apache-2.0 |

Left out on purpose: claude-mem's `babysit` (that path is read as this repo's
PR-handling rules), each repo's internal contributor skills, ECC (1,062
skills), all video skills (remotion, hyperframes, youtube-agent-skill: video
work is kept out of this trading repository entirely), and the dev-only skills in flutter, OpenShell, OmniRoute and OpenBB.

Some skills need their own tooling to do anything: code-review-graph skills
need its MCP server, and most claude-mem skills need the claude-mem worker.
