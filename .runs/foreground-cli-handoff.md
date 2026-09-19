CLI child current handoff (implementation ongoing with root):

Owned source paths:
- core workflow/cli.py: all four operational commands lazy-dispatch AFTER parser validation; inspect-contract original output/error and no app/probe imports preserved.
- examples foreground_workflow_cli.py: strict exact config v1, safe fixed root import, public JSON/static exitcodes, bounded private PIPE credentials only, no ambient settings, IDs exact. Factory contract documented in module and early note.
- core workflow/bootstrap.py: ScopedHostBootstrap.check implements existing readiness gate; synthetic helper tests check full closure/all model roles before startup, frozen pins, explicit runtime/neo4j start only, no installed whole-stack helper reuse.
- tests/test_environment_workflow_cli.py: stdlib-only source-load/AST parser+adapter tests (currently 14).

Still REQUIRED from root owner/parent: foreground_workflow.application_from_cli(config, credentials, *, allow_startup=False) concrete factory. The existing shared root class is present but exact function currently absent. Root constructor and scene fixture contain sufficient ports; don't report CLI complete until this default configured binding exists and real isolated test invokes main WITHOUT application_factory. See .runs/foreground-cli-binding.md and .runs/foreground-cli-root-action.md.

Config strict keys remain unchanged: {schema_version:1,composition:'isolated-synthetic-v1',database:{uri,database,username},deployment_id,workspace_id,artifact_root,lease_root}. URI requires explicit port and no userinfo/path/query/fragment/whitespace. --principal is same trusted OS operator identity, not external authentication. Credentials optional {}; status/replay/fresh cancel/resume cannot require model config. Password/model data cannot be in profile or argv. Only private same-UID pipe FD >=3 accepted, 128KiB/1second; no credential file reader.

Verification command: python3 isaaclab_arena/tests/test_environment_workflow_cli.py. No package application code executed on host. Parent must integrate real-root CLI proof in fixed workflow-scene/combined cohort; no installs, pulls, shared services, native capture or live credentials were touched.

Reproduction commands are in foreground_workflow_cli.py module docstring. These are interface instructions, NOT yet a claim of positive configured execution until factory lands/combined proof passes.
