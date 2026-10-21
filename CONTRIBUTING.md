# Contributing

1. Branch from `main`: `git checkout -b feature/short-name`.
2. Set up: `pip install -r requirements.txt` (add `requirements/dev.txt` if present).
3. Make the change. Keep violation logic in `app/violation/` free of model code so it stays testable.
4. Add or update tests in `tests/`, then run `pytest`.
5. Run `python scripts/check_setup.py` for a quick environment check.
6. Open a pull request. CI runs the tests, a Docker build, and a real YOLO + ByteTrack smoke test.

## Layout rules

* Application code: `app/`. Command-line tools: `scripts/` (one-off checks in `scripts/manual_checks/`).
* Docs: `docs/`. Notebooks: `notebooks/`. Weights: `models/` (never committed).
* Do not commit `.env`, databases, `users.json`, or generated outputs.

## Style

Plain Python, small functions, docstrings that say why. Prefer clear names over comments.

## Data and licences

Datasets are CC BY 4.0. Keep credits in `data/*/README.dataset.txt` when you add data.
