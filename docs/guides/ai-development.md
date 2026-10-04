---
title: Developing with coding agents
description: The instructions canVODpy gives coding agents such as Claude Code, how they stay correct, and the free code graph
---

# Developing with coding agents

canVODpy is developed with coding agents, mostly
[Claude Code](https://docs.anthropic.com/en/docs/claude-code). The
repository carries instructions for them, so that an agent works by the
same rules as a person and knows the science and the traps before it
changes code. You don't need an agent to contribute: the same files are a
compact summary of the project's conventions for people too.

Everything here works with free tools only. No step needs a paid service
or an API key.

---

## The instruction files

| File | What it holds |
|---|---|
| `AGENTS.md` (root) | Scientific context, packages, the one way to process data, data contracts, workflow, rules, guardrails, and the reading order of these docs |
| `canvodpy/AGENTS.md`, `packages/<package>/AGENTS.md` | Per package: where things live, invariants and decisions, tests |
| `.claude/skills/<task>/SKILL.md` | Step-by-step guides for recurring tasks: run the pipeline, add a reader or constellation, deprecate code, store safety, the icechunk 2 API, the link to canvodpy-extensions, releasing |
| `CLAUDE.md` files | One line, `@AGENTS.md`: Claude Code reads `CLAUDE.md`, other agents read `AGENTS.md` |

Claude Code loads the root file at the start of a session, a package's
file when it works in that package, and a task guide when the task fits
its description. Other agents read the same Markdown files.

The files describe what cannot be seen quickly in the code: decisions,
invariants, where the truth lives. They point at the code instead of
copying it, so they go out of date less often.

### Kept correct by a check

Every file path and `just` recipe named in these files must exist.
`just check-agent-docs` verifies this; it runs in `just check`, as a
pre-commit hook and in CI. Paths in canvodpy-extensions are written
`extensions:<path>` and checked at the extensions commit canvodpy is
locked to. A change that makes a statement wrong updates the file in the
same pull request.

---

## The code graph

`just graph` builds a graph of the code with
[graphify](https://pypi.org/project/graphifyy/): every module, class and
function, and who calls, imports or subclasses whom. It is built from the
syntax tree on your machine in about ten seconds, needs no API key and is
never committed (`.graphify/`). Git hooks rebuild it in the background
after each commit, merge and checkout.

```bash
just graph-affected add_cell_ids_to_ds_fast   # everything that uses it
just graph-explain VodComputer                # its neighbours, both directions
just graph-path VodComputer TauOmegaZerothOrder
```

Agents use it before changing or deprecating anything (to find every
caller) and before writing new code (to find an existing implementation).
Connections marked `INFERRED` are guesses; check them in the code.

graphify can also call paid language-model services. The `just` recipes
use only its free, local commands and remove API keys from its
environment. Don't run other graphify commands or install its assistant
skill.

---

## Getting started

```bash
just sync      # dependencies and git hooks (including the graph rebuild)
just graph     # first build of the code graph
claude         # in the repository root
```

Start the agent in the repository root: it reads its instructions from
there.

---

## Guidelines for agent-assisted contributions

1. **Review all output.** A person reviews every change before it is
   merged and is responsible for it.
2. **Run the checks.** `just check` and the tests of the changed packages
   (`just test-package <package>`).
3. **Check scientific claims.** Agents can invent references, formulas or
   values. Compare with primary sources (IGS formats, interface control
   documents, the literature).
4. **Attribution.** Commits with substantial agent help say so in a
   `Co-Authored-By:` line.
5. **No secrets.** Never give an agent credentials or private data. Hosted
   agents send what they read to their provider.

---

## Related pages

- [Architecture](../architecture.md): packages and data flow
- [API levels](api-levels.md): the CLI and `Site.pipeline()`
- [Contributor setup](contributor-setup.md): setup and first run
