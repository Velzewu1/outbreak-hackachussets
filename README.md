# outbreak-hackachussets

Boston what-if model for DS+X 2026 / Hackachusetts: an epidemic wave drives
hospital load, hospital disruption propagates through an FDNA dependency
network, overloaded hospitals divert patients, and the site shows which
neighborhoods lose access to care. Research and demo tool; public aggregate
data; every assumption labelled.

- `seir/`: the model (SEIR layer plus the cascade system layer), CLI and tests. See [seir/README.md](seir/README.md).
- `frontend/`: SvelteKit site and FastAPI wrapper. See [frontend/README.md](frontend/README.md).

```bash
pip install -r seir/requirements.txt -r frontend/api/requirements.txt
npm --prefix frontend/web install && npm --prefix frontend/web run build
uvicorn main:app --app-dir frontend/api --port 8000      # open http://localhost:8000
```
