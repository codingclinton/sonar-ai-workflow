# Agents.md

## Command Execution Rules

For this repository, do **not** recommend or run project console commands directly on the host machine.

### Docker Compose Local Overrides
- The file `docker-compose.local-dev.yml` contains local service overrides, including any custom containers (such as cocoindex) not present in the main `docker-compose.yml`. Always include this file when running or referencing Docker Compose commands for local development.

### Required default behavior
- Assume all project commands should be executed **inside the Docker `web` container** (unless otherwise specified, e.g., cocoindex).
- Prefer the root `Makefile` targets because they already route commands into the `web` container or the appropriate service.
- Do **not** suggest host-side commands like direct `php`, `phpunit`, `artisan`, `composer`, or similar for normal project workflows.
- If a command is not covered by a `Makefile` target, use the Docker compose `web` service execution pattern or the appropriate service (e.g., cocoindex) rather than a host-side command.

## Preferred Command Patterns

Run these from the repository root:

```bash
make puf <phpunit-filter>
make pug <phpunit-group>
make artisan <artisan-command>
make tinker
make cc
```

These `Makefile` targets execute commands inside the Docker `web` container.

## Examples

```bash
make puf can_clear_company_eligibility_criteria_when_service_is_already_applied_to_an_account
make pug ab42190
make artisan migrate:status
```

## CocoIndex Indexing

To update the cocoindex vector database for code search and embeddings, use the Makefile target:

```bash
make cocoindex-update
```

This launches a one-off Python container, mounts the cocoindex and repo folders, installs dependencies, and runs the indexer. It connects to the cocoindex-postgres DB as configured in cocoindex/cocoindex.yaml. No long-lived service is required.

## Fallback Pattern

If a needed command does not already have a `Makefile` target, execute it through Docker compose against the `web` service instead of suggesting a host command.

**CRITICAL: Always use BOTH compose files in this exact format:**

```bash
docker compose -f docker-compose.yml -f docker-compose.local-dev.yml exec web <command>
```

Do NOT omit `-f docker-compose.yml` — both files are required for local development to work correctly.

## Notes for Future Agents

- Treat the Docker `web` container as the canonical runtime for application commands.
- When suggesting PHPUnit commands, prefer `make puf` or `make pug` first.
- When suggesting Artisan commands, prefer `make artisan ...`.
- Avoid telling the user to run project PHP tooling directly on macOS/Linux host shells unless they explicitly ask for a host-only workflow.
