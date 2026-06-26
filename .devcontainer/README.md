# Dev Container Environment Guide

This development container is pre-configured with several AI agents, system tools, and language runtime utilities to facilitate seamless pair programming and agentic workflows.

## Installed Tools & Agents

### 1. AI Agents & CLI Tools
*   **Google Antigravity CLI (`agy`)**: Installed via the official installation script and symlinked to `/usr/local/bin/agy`. Configured as the primary interactive AI assistant.
*   **Claude Code (`claude`)**: Installed globally via `npm` (`@anthropic-ai/claude-code`) for command-line agentic assistance.
*   **Hermes Agent (`hermes`)**: Installed via the Nous Research installer (`--skip-setup --skip-browser` mode). Run `hermes setup` to initialize.

### 2. Browser Automation & MCP
*   **Playwright**: Pre-installed via the base image (`mcr.microsoft.com/playwright:v1.58.2-jammy`).
*   **Playwright MCP Server**: Configured globally in `~/.gemini/config/mcp_config.json` and `~/.gemini/antigravity-cli/mcp_config.json` to allow Antigravity to perform web browsing, screenshotting, and page interaction.
*   **Google Chrome**: Installed inside the container (`google-chrome-stable`) to support Playwright's browser context execution.
*   **AGENT_BROWSER_EXECUTABLE_PATH**: Configured in `.bashrc` to point automatically to the local Playwright chromium binary.

### 3. Package Managers & Runtimes
*   **Astral UV (`uv` / `uvx`)**: Fast Python package installer and resolver, symlinked to `/usr/local/bin/uv`.
*   **Python Dependencies**: Pre-installed packages include `jupyter`, `ipykernel`, `usd-core`, and `huggingface_hub`.
*   **R Language Utilities**: Installs `languageserver` and `renv` packages; runs `renv::restore()` automatically if a lockfile is detected.
*   **System Packages**: `ripgrep`, `ffmpeg`, and `libmagick++-dev` are pre-installed.
