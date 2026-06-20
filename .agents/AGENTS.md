# Development Environment
 
This project runs in a Dev Container.
 
## Environment Constraints
- Node.js 22 LTS (pre-installed in container)
- Python 3.12 (installed in /opt/venv)
- PostgreSQL accessible on port 5432 (started via docker-compose)
- Redis accessible on port 6379
 
## Command Execution Rules
- Run `npm` commands in the /workspace directory
- Run Python scripts within the virtual environment (/opt/venv)
- Use `npm run db:migrate` for database migrations
- Use `npm run test` to run the full test suite
 
## Prohibited Actions
- Do not install npm packages globally (use node_modules only)
- Do not add system packages via apt (modify the Dockerfile instead)
- Do not edit .env directly (use .env.local)
