# AGENTS.md

## Dev environment tips
- This project uses [uv](https://github.com/astral-sh/uv) for dependency management and running scripts.
- After cloning the repository run `uv sync` to install dependencies.
- To start the MCP Redmine server locally:
  ```bash
  REDMINE_URL=<url> REDMINE_API_KEY=<key> uv run -m mcp_redmine.server main
  ```
- For containerized development:
  ```bash
  cp .env.example .env
  docker compose up --build
  ```
- Use `make version-bump` to update the version number before publishing.

## Testing instructions
- There is currently no automated test suite.
- If you add tests, run them with:
  ```bash
  uv run pytest
  ```
- Always ensure the server starts successfully after changes:
  ```bash
  REDMINE_URL=<url> REDMINE_API_KEY=<key> uv run -m mcp_redmine.server main
  ```

## PR instructions
- Title format: `[mcp-redmine] <Title>`
- Run any available tests (see above) and verify the server starts before committing.
- Include relevant documentation updates for user-facing changes.
