# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fresh module-entry processes in one retained disposable DB/artifact scope."""
import json
import os
import subprocess
from pathlib import Path

from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
from isaaclab_arena.tests.test_environment_workflow_scene_engines import configuration
from isaaclab_arena.tests._workflow_scene_fixture import composed_fixture

# Statically capture the fixed application composition; never instantiate it in this interpreter.
from isaaclab_arena_examples.agentic_environment_generation import foreground_workflow_cli  # noqa: F401
from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256


def test_fresh_default_module_run_status_and_dependency_denials():
    import workflow_process_harness as harness

    root = Path("/tmp/workflow-cli")
    root.mkdir(mode=0o700)
    fixture = composed_fixture(root)
    raw = fixture.contract.model_dump(mode="json")
    raw["source"]["prompt"] = "Initial foreground workflow scene fixture"
    for role in ("generation", "assessment"):
        raw["execution"][role + "_model"] = dict(
            profile_id=role,
            billing="free",
            settings_sha256=model_settings_sha256(configuration(), billing="free"),
        )
    raw["budget"].update(
        per_operation_timeout_seconds=30.0,
        total_deadline_seconds=180.0,
        max_model_calls=8,
        max_model_tokens=80000,
        max_runtime_seconds=120.0,
    )
    fixture.area.close()
    (root / "owner").mkdir(mode=0o700)
    database = os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"]
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        connection_timeout=2,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    ) as driver:
        with driver.session(database=database) as session:
            for ddl in Neo4jWorkflowStore.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(10)").consume()
        store = Neo4jWorkflowStore(
            driver,
            database=database,
            deployment_id="fresh-cli",
            workspace_id="fresh-cli",
        )
        store.initialize_scope()
        config = dict(
            schema_version=1,
            composition="isolated-synthetic-v1",
            database=dict(
                uri=os.environ["ARENA_WORKFLOW_NEO4J_URI"],
                database=database,
                username="synthetic",
            ),
            deployment_id="fresh-cli",
            workspace_id="fresh-cli",
            artifact_root=str(root / "artifacts"),
            lease_root=str(root / "owner"),
        )
        (root / "profile.json").write_text(json.dumps(config))
        (root / "profile.json").chmod(0o600)
        (root / "contract.json").write_text(json.dumps(raw))
        commands = []
        admission_before_sdk = []

        def launch(command, identity, checkpoint=None, *, renew=False):
            args, kwargs = harness.cli_spawn_spec()
            proc = subprocess.Popen(args, **kwargs)
            argv = [
                command,
                "--config",
                str(root / "profile.json"),
                "--principal",
                "creator",
            ]
            argv += ["--operation-id", identity, str(root / "contract.json")] if command == "run" else [identity]
            if renew:
                assert command == "resume"
                argv.append("--renew-authorization")
            if command == "run" and identity == "fresh-positive":
                import select

                existing_sdk = set(Path("/evidence").glob("generation-child-*-sdk.json"))
                proc.stdin.write(json.dumps(argv).encode() + b"\n")
                proc.stdin.close()
                proc.stdin = None
                assert select.select([proc.stdout], [], [], 90)[0], "No bounded CLI output"
                first = proc.stdout.readline()
                handle = json.loads(first)
                admission_before_sdk.append(
                    handle.get("event") == "admitted"
                    and proc.poll() is None
                    and all(
                        json.loads(path.read_text())["calls"] == 0
                        for path in set(Path("/evidence").glob("generation-child-*-sdk.json")) - existing_sdk
                    )
                )
                rest, err = proc.communicate(timeout=90)
                out = first + rest
            else:
                out, err = proc.communicate(
                    json.dumps(dict(argv=argv, checkpoint=checkpoint) if checkpoint else argv).encode(), timeout=90
                )
            assert proc.returncode in (0, 3, 5, 6, 7), err.decode(errors="replace")
            lines = [json.loads(line) for line in out.splitlines()]
            assert lines, err.decode(errors="replace")
            proof = json.loads(Path(f"/evidence/workflow-cli-{proc.pid}.json").read_text())
            assert proof["module_entry"] and proof["preimport"]["before_package_imports"]
            assert not any(proof["forbidden"].values())
            assert not Path(f"/proc/{proc.pid}").exists()
            commands.append(dict(command=command, pid=proc.pid, exit=proc.returncode, output=lines))
            Path("/evidence/workflow-cli-transcript.json").write_text(json.dumps(commands))
            return proc.returncode, lines, proof

        # Real run failures, never manually seeded admission/reservation records.
        b1_start = len(commands)
        b1_witnesses = []
        for checkpoint in ("generation_readiness_same_app", "generation_claim"):
            before = set(Path("/evidence").glob("generation-child-*-sdk.json"))
            code, interrupted, proof = launch("run", "b1-" + checkpoint, checkpoint)
            witness = proof["generation_interruption"]
            assert witness["calls_before"] == 0
            run_id = witness["run_id"]
            if checkpoint == "generation_claim":
                assert code != 0 and proof["allowed"]["child_launch"] == 0
                assert set(Path("/evidence").glob("generation-child-*-sdk.json")) == before
                assert witness["owner_dirty"] and len(witness["intents"]) == 1
                original = store.pending_generation(run_id)
                assert original is not None
                code, interrupted, proof = launch("resume", run_id)
                attempt = store.get_generation_attempt(run_id)
                assert attempt is not None, interrupted
                assert attempt.fence.intent_id == original["intent_id"]
                assert attempt.reservation == original["reservation"]
                assert attempt.fence.owner_id == witness["owner"]["owner_id"]
                assert attempt.fence.owner_epoch == witness["owner"]["owner_epoch"]
            else:
                assert witness["same_grant"] and not witness["intents"]
            assert code == 0 and interrupted[-1]["result"]["state"] == "accepted", interrupted
            final = store.result_records(run_id)
            assert final["admitted_at"] == witness["admitted_at"]
            assert len(final["intents"]) == 4 and not store.get_owner().dirty
            added = set(Path("/evidence").glob("generation-child-*-sdk.json")) - before
            assert len(added) == 4 and all(json.loads(p.read_text())["calls"] == 2 for p in added)
            b1_witnesses.append(witness)
        b1_commands = commands[b1_start:]

        # A distinct cancel interpreter must retire an actually active scene owner.
        import select
        import time

        active_start = len(commands)
        active_cancellations = []
        for phase, outage in (("visual", False), ("visual", True), ("generation", False)):
            pause = root / ("pause-" + phase)
            pause.touch()
            active_before = set(Path("/evidence").glob("generation-child-*-active.json"))
            args, kwargs = harness.cli_spawn_spec()
            running = subprocess.Popen(args, **kwargs)
            running.stdin.write(
                json.dumps([
                    "run",
                    "--config",
                    str(root / "profile.json"),
                    "--principal",
                    "creator",
                    "--operation-id",
                    "active-cancel-" + phase + str(outage),
                    str(root / "contract.json"),
                ]).encode()
                + b"\n"
            )
            running.stdin.close()
            running.stdin = None
            assert select.select([running.stdout], [], [], 60)[0]
            first = running.stdout.readline()
            active_run = json.loads(first)["result"]["run_id"]
            deadline = time.monotonic() + 60
            while not (set(Path("/evidence").glob("generation-child-*-active.json")) - active_before):
                assert running.poll() is None and time.monotonic() < deadline
                time.sleep(0.05)
            (active_file,) = set(Path("/evidence").glob("generation-child-*-active.json")) - active_before
            active_pid = json.loads(active_file.read_text())["pid"]
            assert Path(f"/proc/{active_pid}").exists()
            (root / "active-target.json").write_text(json.dumps(dict(run_id=active_run, pid=active_pid)))
            initial = store.result_records(active_run)
            code, cancelled, proof = launch("cancel", active_run, "cancel_unavailable" if outage else "cancel_check")
            assert proof["first_store_access"] == dict(child_absent=True, bolt_before=0, unavailable=outage)
            assert cancelled[-1]["result"]["local_stop"]["delivery"] == "delivered"
            if outage:
                assert cancelled[-1]["result"]["state"] == "unknown"
                assert cancelled[-1]["result"]["durable_cancellation"] == "unconfirmed"
                assert store.get_run(active_run).state != "cancelled" and store.get_owner().dirty
                assert running.poll() is None, "owner must retain exact cleanup for bounded durable retry"
                code, cancelled, proof = launch("cancel", active_run, "cancel_check")
            rest, err = running.communicate(timeout=35)
            pause.unlink()
            owner_lines = [json.loads(x) for x in (first + rest).splitlines()]
            commands.append(dict(command="run", pid=running.pid, exit=running.returncode, output=owner_lines))
            Path("/evidence/workflow-cli-transcript.json").write_text(json.dumps(commands))
            assert store.get_run(active_run).state == "cancelled", cancelled
            assert store.get_owner().dirty is False, "external cancellation cleaned child but left owner dirty"
            assert not Path(f"/proc/{active_pid}").exists()
            final = store.result_records(active_run)
            assert (
                len(initial["intents"]) == len(final["intents"]) == (2 if phase == "visual" else 1)
            ), "cancel must fence further release"
            assert owner_lines[-1]["result"]["owner"]["dirty"] is False
            assert owner_lines[-1]["result"]["state"] == "cancelled"
            assert not tuple((root / "owner").glob("stop-*.sock"))
            active_cancellations.append(
                dict(
                    run_id=active_run,
                    pid=active_pid,
                    outage=outage,
                    phase=phase,
                    delivery_before_db=True,
                    owner_retired=True,
                    no_further_release=True,
                )
            )
        # Fixed admission and completed-generation handoff races, no model substitution.
        for checkpoint in ("admission", "handoff"):
            pause = root / ("pause-" + checkpoint)
            pause.touch()
            args, kwargs = harness.cli_spawn_spec()
            early = subprocess.Popen(args, **kwargs)
            argv = [
                "run",
                "--config",
                str(root / "profile.json"),
                "--principal",
                "creator",
                "--operation-id",
                "cancel-race-" + checkpoint,
                str(root / "contract.json"),
            ]
            early.stdin.write(json.dumps(dict(argv=argv, checkpoint=checkpoint)).encode() + b"\n")
            early.stdin.close()
            early.stdin = None
            assert select.select([early.stdout], [], [], 60)[0]
            first = early.stdout.readline()
            early_run = json.loads(first)["result"]["run_id"]
            if checkpoint == "handoff":
                deadline = time.monotonic() + 60
                while not (root / "handoff-ready.json").exists():
                    assert early.poll() is None and time.monotonic() < deadline
                    time.sleep(0.05)
                assert json.loads((root / "handoff-ready.json").read_text())["run_id"] == early_run
            code, cancelled, proof = launch("cancel", early_run)
            assert cancelled[-1]["result"]["local_stop"]["delivery"] == "delivered"
            assert cancelled[-1]["result"]["durable_cancellation"] == "confirmed"
            pause.unlink()
            rest, err = early.communicate(timeout=30)
            early_proof = json.loads(Path(f"/evidence/workflow-cli-{early.pid}.json").read_text())
            assert early_proof["allowed"]["child_launch"] == (0 if checkpoint == "admission" else 1)
            assert len(store.result_records(early_run)["intents"]) == (0 if checkpoint == "admission" else 1)
            assert early.returncode == 7 and not store.get_owner().dirty
            commands.append(
                dict(
                    command="run",
                    pid=early.pid,
                    exit=early.returncode,
                    output=[json.loads(x) for x in (first + rest).splitlines()],
                )
            )
        # The original fresh-positive run below proves later clean acquisition.
        code, unreachable, proof = launch("cancel", active_run)
        assert unreachable[-1]["result"]["local_stop"]["delivery"] == "no_owner"
        assert unreachable[-1]["result"]["durable_cancellation"] == "confirmed"
        active_commands = commands[active_start:]

        code, lines, proof = launch("run", "fresh-positive")
        assert code == 0, lines
        result = lines[-1]["result"]
        assert result["state"] == "accepted", result
        assert proof["allowed"]["child_launch"] == 4
        assert store.get_owner().dirty is False
        # ArtifactArea.open validates under its nonblocking writer lock.
        for command in ("status", "cancel", "resume"):
            code, readback, proof = launch(command, result["run_id"])
            assert code == 0
            observed = dict(readback[-1]["result"])
            if command == "cancel":
                assert observed.pop("local_stop")["delivery"] == "no_owner"
                assert observed.pop("durable_cancellation") == "unconfirmed"
            assert observed == result
            assert proof["allowed"]["child_launch"] == 0
        for role in (
            "runtime",
            "neo4j",
            "generation_model",
            "assessment_model",
            "capture",
            "gpu",
        ):
            invalid = json.loads(json.dumps(raw))
            field = {"neo4j": "database", "gpu": "runtime"}.get(role, role)
            invalid["execution"][field]["settings_sha256"] = "b" * 64
            (root / "contract.json").write_text(json.dumps(invalid))
            before = set(Path("/evidence").glob("generation-child-*-sdk.json"))
            code, rejected, proof = launch("run", "missing-" + role)
            assert code == 3 and proof["allowed"]["child_launch"] == 0
            if role in {"generation_model", "assessment_model"}:
                assert rejected == [{"schema_version": 1, "error": "model_profile_not_ready"}]
            assert not any(frame.get("event") == "admitted" for frame in rejected)
            assert set(Path("/evidence").glob("generation-child-*-sdk.json")) == before
        # Fresh-process positive resume: both sides of the durable reservation.
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract
        from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import application_from_cli

        (root / "contract.json").write_text(json.dumps(raw))
        for checkpoint in ("pending", "reserved"):
            seed = application_from_cli(config, {})
            contract = parse_contract(json.dumps(raw))
            pending = seed.service.submit("creator", "resume-" + checkpoint, canonical_json(contract)).run
            if checkpoint == "reserved":
                seed.authority.bind_run(
                    "creator",
                    pending.operation_id,
                    contract,
                    run_id=pending.run_id,
                    catalogue_sha256=seed.catalogue_sha256,
                )
                seed.authority.bind_workflow_models("creator", contract, run_id=pending.run_id)
                intent_id = store.reserve_generation(
                    pending.run_id,
                    pending.version,
                    "original-reservation",
                    seed.authority.require_execute("creator", contract, run_id=pending.run_id),
                    seed.generation_reservation,
                    readiness=seed._ready(contract),
                )
            original = store.result_records(pending.run_id)
            seed.close()
            if checkpoint == "reserved":
                code, paused, proof = launch("resume", pending.run_id, "before_claim")
                assert paused[-1]["result"]["state"] == "running", paused
                assert proof["allowed"]["child_launch"] == 1
                retained_generation = store.get_generation_attempt(pending.run_id)
                before_scene = store.scene_snapshot(pending.run_id)
                assert before_scene.intent.worker_fence is None
                code, paused, proof = launch("resume", pending.run_id, "after_observation")
                assert paused[-1]["result"]["state"] == "running", paused
                assert proof["allowed"]["child_launch"] == 1
                observed = store.scene_snapshot(pending.run_id)
                assert observed.intent.action == "repair" and observed.intent.worker_fence is None
                assert store.result_records(pending.run_id)["selected_evidence_id"] is not None
            code, resumed, proof = launch("resume", pending.run_id, renew=True)
            assert code == 0 and resumed[-1]["result"]["state"] == "accepted", resumed
            assert proof["allowed"]["child_launch"] == (2 if checkpoint == "reserved" else 4)
            final = store.result_records(pending.run_id)
            assert final["admitted_at"] == original["admitted_at"]
            if checkpoint == "reserved":
                assert store.get_generation_attempt(pending.run_id).fence.intent_id == intent_id
                assert store.get_generation_attempt(pending.run_id) == retained_generation
            assert len(final["intents"]) == 4 and store.get_owner().dirty is False
        positive_owner_retired = not store.get_owner().dirty
        seed = application_from_cli(config, {})
        uncertain = seed.service.submit("creator", "resume-uncertain", canonical_json(contract)).run
        seed.close()
        code, blocked, proof = launch("resume", uncertain.run_id, "after_release")
        assert code != 0 and blocked[-1]["result"]["state"] == "reconciliation_required"
        assert proof["allowed"]["child_launch"] == 2
        unknown = store.scene_snapshot(uncertain.run_id)
        assert unknown.intent.status == "reconciliation_required"
        sdk_before = {
            p.name: json.loads(p.read_text())["calls"] for p in Path("/evidence").glob("generation-child-*-sdk.json")
        }
        code, blocked, proof = launch("resume", uncertain.run_id)
        assert code != 0 and blocked[-1]["result"]["disposition"] == "blocked"
        assert proof["allowed"]["child_launch"] == 0
        assert sdk_before == {
            p.name: json.loads(p.read_text())["calls"] for p in Path("/evidence").glob("generation-child-*-sdk.json")
        }
        Path("/evidence/workflow-cli.json").write_text(
            json.dumps(
                dict(
                    commands=commands,
                    b1_commands=[c["pid"] for c in b1_commands],
                    b1_witnesses=b1_witnesses,
                    active_commands=[c["pid"] for c in active_commands],
                    active_cancellations=active_cancellations,
                    admission_race_no_worker=True,
                    completed_handoff_no_restart=True,
                    completed_cancel_no_worker=True,
                    unreachable_owner_bounded=True,
                    state=result["state"],
                    admission_before_sdk=admission_before_sdk,
                    same_database=True,
                    default_factory=True,
                    synthetic_capture=True,
                    prior="explicit unavailable fallback; no live retrieval",
                    owner_retired=positive_owner_retired,
                    uncertainty_retained=store.get_owner().dirty,
                    sdk_calls=sdk_before,
                )
            )
        )
        assert admission_before_sdk == [True], "Missing flushed pre-SDK admission handle"
