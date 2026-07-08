# Environment Constraints
- **Execution Environment**: This agent is running in an ISOLATED environment inside a VS Code devcontainer on a Windows machine. It does **not** have access to the Linux server where the actual Isaac Sim simulation or Docker container is running.
- **Simulation**: You CANNOT run Isaac Sim or `docker exec` commands. You CANNOT use `/isaac-sim/python.sh`.
- **Python Execution**: Use `uv run python <script.py>` to execute Python scripts locally (e.g. for data analysis or debugging).
- **Debugging Workflow**: Do not try to run or re-run the simulation. Instead, rely on the data provided by the user (like `.npz` files or logs) and write local analysis scripts to inspect that data. Avoid infinite loops trying to run unsupported Docker or simulation commands.

# Guidelines Override
- Ignore the original `AGENTS.md` instructions regarding Docker execution (`docker exec`) or `/isaac-sim/python.sh` when running commands in this environment, as those commands will fail.
