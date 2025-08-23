Thank you for contributing to the PCSX2 Patch & Texture Manager project.

This short guide explains where to start, how to run the app/tests locally, and how to add tests or code changes.

Quick start
- Main GUI entrypoint: `main.py` — run with `python main.py` from the repository root.
- Library / helper modules: most logic lives in `main.py` (parsing, build_pnach, workers) and small helpers such as `cheat_online.py`, `playwright_fetch.py`.

Running locally (recommended)
1. Create a venv and activate it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run the GUI:

```powershell
python main.py
```

Running tests and checks
- Quick dependency check: `python check_deps.py` (prints which optional deps are present)
- PySide import debug: `python check_pyside_import.py`
- Unit tests: `pytest -q` (tests live in `tests/`) — please add tests for any new public behavior.

Where to add tests
- Tests live under the `tests/` folder. Use `pytest`.
- Fixtures and sample data can go under `tests/fixtures/` (there are already a few sample fixtures).

Best practices for PRs
- Keep changes focused and small.
- Include or update tests for public behavior you change.
- Update `README.md` or this file if the contribution changes usage or the public API.

CI
- A simple GitHub Actions workflow is included to run the dependency check and `pytest` on push/PR. See `.github/workflows/ci.yml`.

Contact and style
- Follow existing code style in the repository.
- If changing UI flows or UX, include screenshots or a short description in the PR.

Thanks for improving the project!
