# Contributing to RMIC-Guard

Thanks for your interest in RMIC-Guard! This is an active academic research
project, and contributions — bug reports, questions, and pull requests — are
welcome.

## Reporting a bug or asking a question

Open a [GitHub Issue](https://github.com/Arshu-1104/RMIC/issues/new). Please include:

- What you were trying to do
- What you expected to happen
- What actually happened (full error message/traceback if there is one)
- Your Python version and OS
- Whether you're using the SDK (`pip install rmic-guard`) or the full
  research repo (cloned from GitHub)

## Suggesting a feature

Open an Issue describing the use case — what you're trying to build, and
what's missing to make it possible. We're especially interested in feedback
from anyone trying to integrate the enforcement engine into their own agent
project.

## Submitting a pull request

1. Fork the repo and create a branch off `main`.
2. Make your change. If it touches `core/`, please also update
   `rmic_guard/__init__.py`'s exports if relevant, since that's the public
   SDK surface.
3. If you're changing enforcement logic (`core/enforcement_engine.py`,
   `core/reasoning_layer.py`, `core/ids_engine.py`), please explain your
   reasoning in the PR description — this project's core contribution is
   about *where* enforcement happens, so changes there get extra scrutiny.
4. Run `python preflight_check.py` before opening the PR to confirm your
   environment is sane.
5. Open the PR against `main` with a clear description of what changed and why.

## Project structure, for orientation

- `core/` — the enforcement engine (contracts, hard rules, IDS, reasoning layer)
- `rmic_guard/` — the public SDK facade (what `pip install rmic-guard` ships)
- `experiment/` — the research experiment runner and statistical analysis
- `baselines/` — comparisons against Lakera Guard and NeMo Guardrails
- `dashboard/` — FastAPI results dashboard
- `contracts/`, `prompts/` — the role contracts and adversarial/legitimate prompt corpus

## Code of conduct

Be respectful and constructive. This is a student research project — we're
here to learn and build something useful, not to score points.

## Questions before contributing?

Open an Issue, or reach out to the corresponding author listed in
[`PYPI_README.md`](PYPI_README.md).
