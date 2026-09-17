# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure-source staging from one bounded, no-follow capture per selected file."""
import ast
import hashlib
import re
from pathlib import Path

from confined_io import ConfinedRoot, new_destination, read_confined

__all__ = ["stage", "read_confined"]

FIXTURE = "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
BACKEND_FIXTURE = "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
BACKEND_DATA = {
    "isaaclab_arena/tests/test_spec_wire_adapter.py": (
        "isaaclab_arena_environments/robolab/tasks/banana_on_plate.yaml",
        "isaaclab_arena_environments/robolab/scenes/bagel_plate_banana_bowl.yaml",
    ),
    "isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py": (
        "isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml",
        "isaaclab_arena_gr00t/embodiments/droid/gr00t_8dof_joint_space.yaml",
        "isaaclab_arena_gr00t/embodiments/droid/8dof_joint_space.yaml",
        "isaaclab_arena_gr00t/embodiments/droid/13dof_joint_space.yaml",
        "isaaclab_arena_gr00t/tests/test_data/test_g1_locomanip_lerobot/test_g1_locomanip_gr00t_closedloop_config.yaml",
        "isaaclab_arena_gr00t/embodiments/g1/gr00t_43dof_joint_space.yaml",
        "isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml",
    ),
}
BACKEND_TESTS = (
    "isaaclab_arena/tests/test_workbench_editor_revisions.py",
    "isaaclab_arena_examples/tests/test_workbench_editor_revision_api.py",
)
EXPLICIT_BACKEND_TESTS = (
    "isaaclab_arena_examples/tests/test_workbench_readiness.py",
    "isaaclab_arena_examples/tests/test_workbench_paused_start.py",
    "isaaclab_arena_examples/tests/test_workbench_policy_readiness.py",
    "isaaclab_arena_examples/tests/test_workbench_policy_wire.py",
    "isaaclab_arena/tests/test_policy_contract.py",
    "isaaclab_arena_gr00t/tests/test_serving_metadata.py",
    "isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py",
    "isaaclab_arena_examples/tests/test_workbench_generation_diagnostics.py",
    "isaaclab_arena/tests/test_spec_wire_adapter.py",
    "isaaclab_arena/tests/test_spec_inference.py",
    "isaaclab_arena/tests/test_inference_profiles.py",
    "isaaclab_arena_examples/tests/test_workbench_model_settings.py",
    "isaaclab_arena_examples/tests/test_workbench_workflow_authorization.py",
    "isaaclab_arena_examples/tests/test_workbench_execution_grants.py",
    "isaaclab_arena_examples/tests/test_workbench_reauthorization.py",
    "isaaclab_arena/tests/test_inference_backend.py",
    "isaaclab_arena_examples/tests/test_workbench_build.py",
    "isaaclab_arena_examples/tests/test_workbench_build_environment.py",
    "isaaclab_arena_examples/tests/test_workbench_evaluation_harness.py",
    "isaaclab_arena_examples/tests/test_workbench_evaluate.py",
    "isaaclab_arena_examples/tests/test_workbench_research_source_consumers.py",
    "isaaclab_arena_examples/tests/test_workbench_manual_research_versions.py",
    "isaaclab_arena_examples/tests/test_workbench_manual_research_api.py",
    "isaaclab_arena_examples/tests/test_workbench_public_job_protection.py",
    "isaaclab_arena_examples/tests/test_workbench_metadata_protection.py",
    "isaaclab_arena_examples/tests/test_workbench_renewal_public_protection.py",
    "isaaclab_arena_examples/tests/test_workbench_graph_queries.py",
)
FRONTEND = Path("web/arena-workbench")
HARNESS = FRONTEND / "tests/e2e/functional-v7"
PYTHON_PACKAGES = frozenset({
    "isaaclab_arena",
    "isaaclab_arena_examples",
    "isaaclab_arena_environments",
    "isaaclab_arena_g1",
    "isaaclab_arena_gr00t",
    "isaaclab_arena_openpi",
})
REGISTRIES = tuple(
    Path(folder)
    for folder in (
        "isaaclab_arena/assets",
        "isaaclab_arena/relations",
        "isaaclab_arena/tasks",
    )
)
API = Path("isaaclab_arena_examples/agentic_environment_generation/web_api")
MAX_CAPTURE_BYTES = 128 * 1024 * 1024
MAX_CAPTURE_FILES = 10000
FRONTEND_REFERENCES = re.compile(r"""(?:from\s*|import\s*\(|import\s*|new URL\(\s*|url\(\s*)['"](\.[^'"]+)""")


def backend_fixture_paths(names):
    """Select only literal inert data dependencies for already admitted tests."""
    if not names:
        return ()
    return (BACKEND_FIXTURE, *(path for name in names for path in BACKEND_DATA.get(name, ())))


def _frontend_reference(entry, reference):
    """Normalize relative imports lexically without resolving any source link."""
    parts = list(entry.relative_to(FRONTEND).parent.parts)
    for part in reference.split("?", 1)[0].split("#", 1)[0].split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("Frontend import escapes its approved root")
            parts.pop()
        else:
            parts.append(part)
    return FRONTEND.joinpath(*parts)


def stage(root, destination, browser, backend_tests=()):
    """Capture the inert closure, then copy and hash those exact frozen bytes."""
    if (
        browser
        and backend_tests
        or len(backend_tests) != len(set(backend_tests))
        or not set(backend_tests) <= set(BACKEND_TESTS + EXPLICIT_BACKEND_TESTS)
    ):
        raise ValueError("Only unique approved backend test files are permitted")
    captured = {}
    captured_bytes = 0
    with ConfinedRoot(root) as source:
        # Preflight every discovery root before any listing. Recursive walks
        # additionally validate each descendant before listing that descendant.
        for folder in (*REGISTRIES, API, HARNESS):
            source.validate_directory(folder)
        if browser:
            source.validate_directory(FRONTEND)

        def capture(relative):
            nonlocal captured_bytes
            relative = Path(relative)
            if relative not in captured:
                if len(captured) >= MAX_CAPTURE_FILES:
                    raise ValueError("Source closure exceeds file limit")
                data = source.read(relative)
                captured_bytes += len(data)
                if captured_bytes > MAX_CAPTURE_BYTES:
                    raise ValueError("Source closure exceeds byte limit")
                captured[relative] = data
            return captured[relative]

        def available(relative):
            # Once captured, a file is never opened again, including when another
            # import requests it after a pathname replacement.
            return relative in captured or source.is_file(relative)

        todo = source.files(API, {".py"})
        todo.extend(Path(name) for name in backend_tests)
        todo.append(Path("isaaclab_arena/agentic_environment_generation/environment_generation_agent.py"))
        for folder in REGISTRIES:
            todo.extend(source.files(folder, {".py"}, recursive=True))
        selected = set()

        def resolve(module):
            components = module.split(".")
            if components[0] not in PYTHON_PACKAGES:
                return
            if not all(component.isidentifier() for component in components):
                return
            stem = Path(*components)
            for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
                if available(candidate):
                    todo.append(candidate)

        while todo:
            relative = todo.pop()
            if relative in selected:
                continue
            if relative.parts[0] not in PYTHON_PACKAGES:
                raise ValueError("Python source outside approved packages")
            data = capture(relative)
            selected.add(relative)
            package = relative.parent.parts
            for parent in relative.parents:
                if parent == Path():
                    break
                init = parent / "__init__.py"
                if init not in selected and available(init):
                    todo.append(init)
            # ast.parse accepts bytes and honors Python source encoding cookies.
            for node in ast.walk(ast.parse(data, filename=str(relative))):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        resolve(name.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.level > len(package):
                        raise ValueError("Python relative import escapes its package")
                    prefix = list(package[: len(package) - node.level + 1]) if node.level else []
                    module = ".".join(prefix + ([node.module] if node.module else []))
                    resolve(module)
                    for name in node.names:
                        resolve(module + "." + name.name)

        capture(FIXTURE)
        if backend_tests:
            for relative in backend_fixture_paths(backend_tests):
                capture(relative)
        for relative in source.files(HARNESS, {".py", ".mjs"}):
            capture(relative)
        if browser:
            queue = [FRONTEND / "src/main.tsx", FRONTEND / "vite.config.ts"]
            seen = set()
            while queue:
                entry = queue.pop()
                if entry in seen:
                    continue
                if not entry.is_relative_to(FRONTEND):
                    raise ValueError("Frontend source outside approved root")
                data = capture(entry)
                seen.add(entry)
                if entry.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".css"}:
                    continue
                for reference in FRONTEND_REFERENCES.findall(data.decode("utf-8")):
                    base = _frontend_reference(entry, reference)
                    candidates = [
                        base,
                        *(Path(str(base) + suffix) for suffix in (".ts", ".tsx", ".js", ".jsx")),
                        *(base / ("index" + suffix) for suffix in (".ts", ".tsx", ".js", ".jsx")),
                    ]
                    target = next((candidate for candidate in candidates if available(candidate)), None)
                    if target is None:
                        raise ValueError(f"Cannot stage frontend import {reference} from {entry}")
                    queue.append(target)
            for name in ("package.json", "index.html"):
                capture(FRONTEND / name)
        source._check()

    # Do not touch the destination until every source has been safely captured.
    # A destination must be new: neither existing trees nor symlinks are merged.
    manifest = {}
    with new_destination(destination) as output:
        for relative, data in sorted(captured.items()):
            output.write_new(relative, data)
            manifest[str(relative)] = hashlib.sha256(data).hexdigest()
    return manifest
