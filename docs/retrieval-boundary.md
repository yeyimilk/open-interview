# Retrieval Boundary Decision

Retrieval stays in-process for now.

The current boundary under `openinterview_core/domain/retrieval/` is already
service-shaped: callers pass `RetrieveRequest`, receive `RetrieveResponse`, and
do not know whether the backing implementation uses SQL, Chroma, common KB,
memory, generated QA, or project chunks.

Keeping it in Core is the right next step because:

- the contract is still changing as common KB, memory pinning, and QA review
  mature;
- tests can exercise permissions, filters, ranking, and context packing without
  a second deployable;
- Chroma and SQL access still share Core configuration and user scoping;
- production metrics should guide whether process isolation is worth the
  operational cost.

A separate retrieval service becomes attractive when ranking models, caching,
or vector infrastructure need independent scale or release cadence. Until then,
the implementation hardens the in-process boundary with hybrid ranking,
evaluation fixtures, and explicit source metadata.

Local eval fixtures live at:

```text
backend/services/core/tests/fixtures/retrieval_eval.json
```

Score captured retrieval output with:

```bash
.venv/bin/python scripts/eval_retrieval.py --results /path/to/results.json
```
