# Local Claude Configuration

This file contains local customizations for Claude's behavior in this repository. These settings override defaults and should be referenced by agents during development.

## Docker Compose Commands

**CRITICAL: When running docker compose commands, ALWAYS use both compose files in this exact format:**

```bash
docker compose -f docker-compose.yml -f docker-compose.local-dev.yml exec web <command>
```

Do NOT omit `-f docker-compose.yml` — both files are required for local development to work correctly. The `docker-compose.local-dev.yml` file contains local service overrides including custom containers (such as cocoindex) not present in the main `docker-compose.yml`.

This applies to ALL agents and claude instances working on this repository.

# Agents.md

## Command Execution Rules

Do **not** run project commands directly on the host machine. All application commands run inside the Docker `web` container.

- Prefer `Makefile` targets — they already route into the container.
- If no `Makefile` target exists, use the Docker fallback below.
- Never suggest host-side `php`, `phpunit`, `artisan`, or `composer` invocations.

## Makefile Commands

```bash
make puf <phpunit-filter>       # run a specific test by name
make pug <phpunit-group>        # run tests by @group tag
make artisan <artisan-command>  # run an Artisan command
make tinker                     # open Tinker REPL (always call `ddb` first to set up the tenant)
make cc                         # clear caches
make cs-fix                     # apply PHP code style fixes
```

## Fallback (no Makefile target)

```bash
docker compose -f docker-compose.yml -f docker-compose.local-dev.yml exec web <command>
```

## Development Workflow

This project follows **TDD** (red-green-refactor) and a **search-first** discovery approach. Refer to the skills for full detail:

- `tdd-workflow` — TDD cycle, PHPUnit conventions, factory patterns, assertion standards
- `search-first` — semantic code search before writing or modifying any code
