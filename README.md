# Sonar AI Workflow

Central repository for AI workflow tools and configurations used in development at Sonar Software.

## Overview

This repository serves as a hub for:
- **Local Claude Configuration** - Customizations for Claude's behavior in the Sonar development environment
- **Agent Configurations** - Rules and best practices for agent-based development workflows
- **Docker Development Setup** - Local development environment with Docker Compose overrides
- **AI Tooling Integration** - Integration with Sonar's development infrastructure, including CocoIndex for semantic code search

## Key Files

- **CLAUDE.md** - Local Claude configuration and Docker Compose best practices for development
- **AGENTS.md** - Command execution rules, Makefile patterns, and guidance for agent workflows
- **docker-compose.local-dev.yml** - Local service overrides for development (e.g., CocoIndex containers)

## Development Setup

All project commands should be executed inside the Docker `web` container using Makefile targets:

```bash
make artisan <artisan-command>     # Run Laravel Artisan commands
make puf <phpunit-filter>         # Run filtered PHPUnit tests
make pug <phpunit-group>          # Run grouped PHPUnit tests
make tinker                        # Launch Tinker shell
make cc                            # Clear cache
make cocoindex-update              # Update CocoIndex vector database
```

For Docker commands, always use both compose files:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-dev.yml exec web <command>
```

## Purpose

This repository helps ensure consistent AI-assisted development practices across Sonar Software's team, providing centralized documentation and configurations for local development environments.
