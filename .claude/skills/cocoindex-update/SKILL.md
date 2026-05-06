---
name: cocoindex-update
description: Update the cocoindex vector database to reflect current codebase state. Run `make cocoindex-update` after adding/removing files or updating cocoindex config. Uses Docker container with proper dependencies and DB connection.
---

## When to Use

Run this skill after:
- Adding, removing, or changing source files
- Updating `cocoindex/cocoindex.yaml` patterns
- Changing dependencies or environment
- Before using code search or embeddings features

## How to Run

```sh
make cocoindex-update
```

This launches a one-off Python container that mounts your cocoindex and repo folders, installs dependencies, and runs the indexer. It connects to the cocoindex-postgres DB as configured in `cocoindex/cocoindex.yaml`.

## Notes

- Processing may take several minutes for large codebases
- Ensure web and cocoindex-postgres containers are running
- Check logs if encountering errors with missing dependencies or DB connectivity
