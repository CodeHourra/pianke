# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

**片刻 (Pianke)** is a local photo culling/selection tool for photographers. It is a pure Python Flask app with a vanilla HTML/CSS/JS frontend (no build step, no npm, no databases, no Docker). See `README.md` for full product details.

### Running the application

```bash
source .venv/bin/activate
python app.py --port 5057 --no-browser
```

The app binds to `127.0.0.1:5057`. Use `--no-browser` in headless/cloud environments to suppress the auto-open browser call.

### Running tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

There are pre-existing test failures (7 of 14 tests fail as of the initial codebase state). This is not caused by the environment setup.

### Linting

`ruff` is installed as a transitive dependency. No project-level ruff/flake8/pylint config exists, so `ruff check .` uses defaults. There are pre-existing lint warnings (~35 issues).

### OpenCV package conflict (critical gotcha)

After running `pip install -r requirements.txt`, transitive dependencies (`insightface`, `pyiqa`) pull in `opencv-python` and `opencv-python-headless`, which conflict with the required `opencv-contrib-python` (needed for `cv2.saliency`). You **must** run:

```bash
pip uninstall -y opencv-python opencv-python-headless
pip install --force-reinstall --no-deps "opencv-contrib-python>=4.9"
```

The update script handles this automatically. If you ever re-run `pip install -r requirements.txt`, you must repeat the OpenCV fix.

### Three operating modes

- **Fast (极速)**: Pure local CV heuristics. No extra deps beyond `requirements.txt`. Works fully offline.
- **Expert (专家)**: Needs PyTorch + DINOv2/InsightFace/NIMA models. First run downloads ~600MB of models from HuggingFace.
- **Tycoon (土豪)**: Requires `ARK_API_KEY` env var for remote LLM API calls. Not usable without an API key.

For development/testing, **Fast mode** is the safest default since it requires no models or API keys.
