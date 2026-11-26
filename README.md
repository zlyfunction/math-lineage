# MathLineage — Open & Dissertation-Verified Mathematics Genealogy

**Live Site**: https://zlyfunction.github.io/math-lineage/

A modernized rebuild of the [Mathematics Genealogy Project](https://www.genealogy.math.ndsu.nodak.edu/) engineered around one strict rule: **every newly added scholar and advisor–student relationship must be backed by a verifiable, publicly searchable doctoral dissertation record**.

## Features

- **Dissertation-First Provenance**: Every verified entry links directly to an official institutional thesis page and/or full-text PDF, along with verbatim repository/title-page metadata.
- **5 Authoritative Dissertation Connectors + Historical Backbone**:
  - **NYU Courant** (`cs.nyu.edu/dynamic/reports/` + automatic `pypdf` title-page verification when HTML omits advisor metadata)
  - **MIT DSpace 7 REST API** (`dspace.mit.edu`, Department of Mathematics Ph.D. dissertations + permanent Handles)
  - **HAL / TEL** (`api.archives-ouvertes.fr`, French & European Math Ph.D. theses + direct PDFs)
  - **theses.fr** (ABES French National Doctoral Registry, defended theses + IdRef PPNs)
  - **DataCite Dissertations API** (Oxford ORA, Cambridge Apollo, LMU Munich, ETH Zürich, Caltech, TU Delft DOIs with `Supervisor` metadata)
  - **Wikidata** (`P549` MGP ID / `P184` doctoral advisor / `P185` doctoral student historical backbone with EN/ZH labels)
- **Interactive Lineage Graph**: Layered pan/zoom SVG graph (up to 12 ancestor generations) with verification-coded edges and 1-click SVG export.
- **Shortest Academic Path Finder**: Undirected BFS shortest lineage chain between any two mathematicians with step-by-step provenance badges.
- **Dual-Mode Architecture**:
  - **GitHub Pages Live Mode**: Instant search, graph, shortest paths, direct browser CORS verification (DataCite / HAL / `theses.fr`), local review sandbox + 1-click GitHub Issue submission, and weekly GitHub Actions harvesting.
  - **Full-Stack Server Mode**: FastAPI + SQLite FTS5 + `pypdf` live PDF title-page verification + persistent review queue (`uvicorn` or Docker).

## Run Locally (Full-Stack Mode)

```bash
# Install dependencies
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..

# Run unified FastAPI + React SPA server on port 8000
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

Or with Docker:

```bash
docker build -t math-lineage .
docker run -p 8000:8000 math-lineage
```
