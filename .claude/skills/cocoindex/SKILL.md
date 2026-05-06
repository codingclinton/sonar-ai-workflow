---
name: cocoindex
description: |
  This skill should be used when building data processing pipelines with CocoIndex, a Python library for incremental data transformation. Use when the task involves processing files/data into databases, creating vector embeddings, building knowledge graphs, ETL workflows, or any data pipeline requiring automatic change detection and incremental updates. CocoIndex is Python-native (supports any Python types), has no DSL, and uses version 1.0.0 or later.
---

# CocoIndex Skill

CocoIndex is a Python library for building incremental data processing pipelines with declarative target states. Think spreadsheets or React for data pipelines: declare what the output should look like based on current input, and CocoIndex automatically handles incremental updates, change detection, and syncing to external systems.

## When to Use This Skill

Use this skill when building pipelines that involve:
- Document processing: PDF/Markdown conversion, text extraction, chunking
- Vector embeddings: Embedding documents/code for semantic search
- Database transformations: ETL from source DB to target DB
- Knowledge graphs: Extract entities and relationships from data
- LLM-based extraction: Structured data extraction using LLMs
- File-based pipelines: Transform files from one format to another
- Incremental indexing: Keep search indexes up-to-date with source changes
- Streaming pipelines: Kafka-based real-time data processing

## Quick Start: Creating a New Project

### Initialize Project

    cocoindex init my-project
    cd my-project

This creates: `main.py`, `pyproject.toml`, `.env`, `README.md`.

### Add Dependencies

    # For vector embeddings with PostgreSQL
    dependencies = ["cocoindex>=1.0.0", "sentence-transformers", "asyncpg"]

    # For LLM extraction
    dependencies = ["cocoindex>=1.0.0", "litellm", "instructor", "pydantic>=2.0"]

See references/setup_project.md for complete examples.

### Run the Pipeline

    pip install -e .
    cocoindex update main.py

## Core Concepts

- Apps: Top-level executables binding main functions with parameters
- Functions (@coco.fn): Mark processing functions, support memoization
- Processing Components: Group item processing with target states
- Target States: Declare what should exist; CocoIndex handles updates
- Context for Shared Resources: Share DB connections, models, etc.
- ID Generation: Stable, unique IDs for incremental updates
- Catch-Up vs Live Mode: Choose between batch and streaming updates

## CLI Commands

    cocoindex init my-project              # Create new project
    cocoindex update main.py               # Run app
    cocoindex update main.py:my_app        # Run specific app
    cocoindex update main.py -L            # Run in live mode (continuous)
    cocoindex update main.py --full-reprocess  # Reprocess everything
    cocoindex drop main.py [-f]            # Drop and reset all state
    cocoindex ls [main.py]                 # List apps
    cocoindex show main.py [--tree]        # Show component paths

## Best Practices

- Use @coco.fn on all processing functions
- Add memoization for expensive operations
- Use stable component paths
- Use context for shared resources
- Use Annotated[NDArray, CONTEXT_KEY] for vectors
- Use convenience APIs for targets

## Troubleshooting

- Add memo=True to expensive functions to avoid unnecessary reprocessing
- Use stable IDs for memoization

## Resources

- CocoIndex Documentation: https://docs.cocoindex.dev/docs/
- GitHub Examples: https://github.com/cocoindex-io/cocoindex/tree/v1/examples

## Version Note

This skill is for CocoIndex >=1.0.0 (v1). It uses a completely different API from v0.
