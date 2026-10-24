---
inclusion: always
---

# Technology stack

- Python 3.12 in a repository-local `.venv`.
- pandas for tabular transformations.
- GeoPandas and Shapely for district and hospital geospatial work.
- NumPy and SciPy for numerical modeling, ODE integration, and fitting.
- NetworkX or explicit matrices for the dependency network; choose the smallest clear implementation.
- Streamlit for the app, with pydeck preferred for the map unless a tested requirement favors Folium.
- pytest for tests, Ruff for formatting and linting, and type hints on public functions.
- Streamlit Community Cloud is the intended deployment target.

## Dependency policy

- Record direct runtime and development dependencies with pinned versions in `requirements.txt` before implementation.
- Do not add a library when the standard library or an existing dependency is sufficient.
- Do not make the judging demo depend on a live API. Fetch and validate data ahead of time, then run from committed cleaned snapshots when licensing and size permit.

## Quality commands

Once dependencies exist, keep these commands working:

```bash
python -m pytest
ruff check .
ruff format --check .
streamlit run app/main.py
```
