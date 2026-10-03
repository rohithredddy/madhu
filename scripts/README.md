# scripts - helpers

Small convenience scripts that are not part of any of the three programs:

- `start-all.sh` / `start-all.bat` - start the Python engine, the Java backend and the React dev
  server together (they `cd` into `backend/` first, so the default data directory resolves).
- `make_synthetic_cases.py` - write a handful of synthetic cases into `data/cases/`, so the
  application has something to show before any benchmark data is downloaded.
