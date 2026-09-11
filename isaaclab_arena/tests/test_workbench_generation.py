# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Agent publication opt-out and genuine stage callbacks, without live inference."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from isaaclab_arena.agentic_environment_generation.environment_generation_agent import EnvironmentGenerationAgent
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.tests.utils.agentic_environment_generation import minimal_spec_dict


@pytest.mark.parametrize("method", ["generate_spec", "refine_spec"])
@pytest.mark.parametrize("publish", [False, True])
def test_generation_publication_is_explicit_and_progress_is_observed(method, publish):
    spec = ArenaEnvGraphSpec.from_dict(minimal_spec_dict())
    agent = EnvironmentGenerationAgent.__new__(EnvironmentGenerationAgent)
    agent.inference_backend = SimpleNamespace(model="test", telemetry=None)
    agent.spec_inference = SimpleNamespace(
        infer=Mock(return_value=(spec, None)), repair_with_feedback=Mock(return_value=(spec, None))
    )
    agent.max_retries = 0
    stages = []
    with (
        patch("isaaclab_arena.agentic_environment_generation.graph_rag.GraphRAGRetriever"),
        patch("isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync.sync_spec_to_neo4j") as sync,
    ):
        args = ("create a scene",) if method == "generate_spec" else (spec, "move the cube")
        kwargs = {
            "asset_catalog": object(),
            "relation_catalog": object(),
            "task_catalog": object(),
            "progress": stages.append,
        }
        if not publish:
            kwargs["publish_to_graph"] = False
        result, _ = getattr(agent, method)(*args, **kwargs)
    assert result is not None
    assert sync.call_count == int(publish)
    assert stages[0] == "catalogues_loading"
    assert "spec_inference" in stages
    assert stages[-1] == "generation_completed"
    assert ("graph_publishing" in stages) == publish


@pytest.mark.parametrize("refine", [False, True])
def test_workbench_generation_adapter_validates_and_never_exposes_raw_traces(tmp_path, refine):
    import yaml

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation.web_api.generation import generate

    observed = []
    spec = ArenaEnvGraphSpec.from_dict(minimal_spec_dict())

    class Agent:
        telemetry = SimpleNamespace(converged=False)
        traces = ["Bearer private-secret; untrusted model output"]

        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 1
            assert kwargs["max_tokens"] == 4096
            assert kwargs["load_dotenv"] is False

        def generate_spec(self, prompt, **kwargs):
            assert kwargs["publish_to_graph"] is False
            observed.append("generate")
            kwargs["progress"]("spec_inference")
            return spec, None

        def refine_spec(self, base, prompt, **kwargs):
            assert kwargs["publish_to_graph"] is False
            assert base.to_dict() == spec.to_dict()
            observed.append("refine")
            kwargs["progress"]("spec_inference")
            return spec, None

    inputs = {"prompt": "move the cube", "base_yaml": yaml.safe_dump(spec.to_dict()) if refine else None}
    result = generate(inputs, lambda stage: None, agent_factory=Agent, config={"model": "test"})
    assert result["publication"] == "not_published"
    assert observed == (["refine"] if refine else ["generate"])
    assert "private-secret" not in str(result)
    assert result["warnings"]
    assert Documents(tmp_path).validate(result["yaml_text"])["valid"]


def test_agent_can_disable_dotenv_without_changing_cli_default(stub_openai):
    with patch("isaaclab_arena.agentic_environment_generation.inference_backend._load_dotenv_if_present") as load:
        EnvironmentGenerationAgent(api_key="test-only", load_dotenv=False)
        load.assert_not_called()
        EnvironmentGenerationAgent(api_key="test-only")
        load.assert_called_once_with()
