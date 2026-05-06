# Local Claude Configuration

This file contains local customizations for Claude's behavior in this repository. These settings override defaults and should be referenced by agents during development.

## Docker Compose Commands

**CRITICAL: When running docker compose commands, ALWAYS use both compose files in this exact format:**

```bash
docker compose -f docker-compose.yml -f docker-compose.local-dev.yml exec web <command>
```

Do NOT omit `-f docker-compose.yml` — both files are required for local development to work correctly. The `docker-compose.local-dev.yml` file contains local service overrides including custom containers (such as cocoindex) not present in the main `docker-compose.yml`.

This applies to ALL agents and claude instances working on this repository.
