Evaluate with GR00T
===================

GR00T evaluation runs an agentically generated Arena environment graph with a
remote GR00T policy server. The generated environment is passed as a environment graph spec YAML,
while GR00T receives camera observations, and returns DROID actions via remote policy connection.

This page assumes you already generated or selected a environment graph spec YAML.


Start the GR00T Server
----------------------

In the first terminal, start the GR00T policy server:

.. code-block:: bash

   cd submodules/Isaac-GR00T
   uv run python gr00t/eval/run_gr00t_server.py \
      --model-path nvidia/GR00T-N1.6-DROID \
      --embodiment-tag OXE_DROID \
      --device cuda --host 127.0.0.1 --port 5555

Leave this terminal running. The first launch downloads the ``nvidia/GR00T-N1.6-DROID``
weights from HuggingFace; later launches reuse the local cache.

See :doc:`../../quickstart/first_experiments/running_a_real_policy/gr00t` for
details on GR00T server setup, model downloads, and batch-evaluation examples.


Client/server version compatibility
-----------------------------------

The remote policy uses the connected server's modality configuration when
``modality_config_path`` is omitted. Video history, state keys, and action horizon
then describe the served checkpoint rather than the GR00T version installed in
Arena. An explicitly supplied modality file retains precedence and must match the
server. For example, N1.6-DROID expects one video frame and 32 action steps;
using a newer client's local defaults can produce a two-frame observation or a
different action horizon. Changing ``action_horizon`` alone does not repair that
modality mismatch.

Transport compatibility is a separate requirement. A successful ping does not
prove that image arrays survive serialization. If the server reports
``Video key 'exterior_image_1_left' must be a numpy array. Got <class 'dict'>``,
compare the loaded ``gr00t.policy.server_client.MsgSerializer`` implementations
in both containers. Older N1.6 images decode ``__ndarray_class__`` / ``as_npy``
envelopes, whereas newer clients may send msgpack-numpy envelopes.

Keep the N1.6 model and processor implementation when repairing an N1.6 deployment.
After testing the transport module's imports and array roundtrips in that image,
one option is to bind-mount only the compatible ``server_client.py`` read-only
at ``/workspace/gr00t/gr00t/policy/server_client.py``. Do not replace the entire
model checkout merely to align serialization. Preserve ``allow_pickle=False``
and object-array rejection, then verify a real inference response's array types,
shapes, and finite values before launching the simulator. Synthetic transport
checks do not establish manipulation success.

When launching Docker from an editor container, bind sources must be paths on the
Docker host. Discover the matching repository and model-cache sources from Docker
mount inspection; the editor's ``/workspaces`` and ``$HOME`` paths need not refer
to the same host directories. Verify the server's actual model arguments as well
as the endpoint; a client policy YAML does not select the server's checkpoint.


Run the Generated Environment
-----------------------------

In a second terminal, run the policy runner with the generated environment graph spec YAML:

.. code-block:: bash

   python isaaclab_arena/evaluation/policy_runner.py \
      --viz kit \
      --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
      --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
      --remote_host 127.0.0.1 \
      --remote_port 5555 \
      --enable_cameras \
      --num_steps 1000 \
      --env_graph_spec_yaml isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml

The important pieces are:

* ``--policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy``
  selects the GR00T remote closed-loop policy client.
* ``--policy_config_yaml_path`` provides the DROID manipulation policy config.
* ``--remote_host`` and ``--remote_port`` must match the GR00T server.
* ``--enable_cameras`` is required because GR00T consumes visual observations.
* ``--env_graph_spec_yaml`` points the runner at the agentically generated
  environment graph spec.

Add a language instruction when you want to make the GR00T task explicit:

.. code-block:: bash

   python isaaclab_arena/evaluation/policy_runner.py \
      --viz kit \
      --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
      --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
      --remote_host 127.0.0.1 \
      --remote_port 5555 \
      --enable_cameras \
      --num_steps 1000 \
      --language_instruction "Pick up the mustard bottle and place it in the raisin box." \
      --env_graph_spec_yaml isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml

To use with variations, append the variation overrides after the environment source, e.g. to enable camera extrinsics variations:

.. code-block:: bash

   python isaaclab_arena/evaluation/policy_runner.py \
      --viz kit \
      --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
      --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
      --remote_host 127.0.0.1 \
      --remote_port 5555 \
      --language_instruction "Pick up the mustard bottle and place it in the raisin box." \
      --enable_cameras \
      --num_steps 1000 \
      --env_graph_spec_yaml isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml \
      droid_abs_joint_pos.camera_extrinsics_wrist_camera.enabled=true

.. note::

    Variation overrides, such as ``light.hdr_image.enabled=true`` and
    ``droid_abs_joint_pos.camera_extrinsics_wrist_camera.enabled=true``, can be appended
    after the environment source.
