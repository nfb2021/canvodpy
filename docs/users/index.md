---
title: Get Started — Users
description: Retrieve GNSS-T VOD with canVODpy, from the command line or from Python.
---

# Get Started Retrieving VOD

**The CLI is the main way to use canVODpy** — a complete, terminal-first
entrypoint designed to run unattended: cron jobs, HPC/remote machines,
scheduled batch processing. Most users should start there, even if they
plan to wrap it in their own scripts later.

Python gives you two more targeted alternatives when you need to go beyond
running the pipeline as-is: `Site.pipeline()` for scripted/notebook-driven
runs, and the stateless `canvodpy.functional` building blocks if you're
building your own custom pipeline logic in Python.

<div class="grid cards" markdown>

-   :fontawesome-solid-terminal: &nbsp; **CLI — start here**

    ---

    The recommended entrypoint for production runs, cron jobs, and remote/HPC
    deployments. Complete on its own — no Python required.

    [:octicons-arrow-right-24: CLI Quickstart](cli.md){ .md-button .md-button--primary }

-   :fontawesome-brands-python: &nbsp; **Python — for scripting & custom pipelines**

    ---

    `Site.pipeline()` for scripted/notebook-driven runs, or the functional
    building blocks (`read_rinex`, `augment_with_ephemeris`, ...) if you're
    assembling your own custom pipeline.

    [:octicons-arrow-right-24: Python Quickstart](python.md){ .md-button .md-button--primary }

</div>

---

Both paths share the same installation and the same `canvod-settings.yaml`
configuration file — see whichever guide you pick for the full walkthrough.

---

Looking to contribute to canVODpy itself, not just use it? See
[Get Started Contributing](../guides/getting-started.md) instead — it
covers everything here plus the development environment, tests, and PR
workflow.
