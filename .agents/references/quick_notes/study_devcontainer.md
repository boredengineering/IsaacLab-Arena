# Study on how to make the devcontainer moore powerful

### What Happened & What Was Resolved:

1. Container Working Directory: Added -w /workspace/gr00t to run_gr00t_server.sh so the entrypoint script executes from the repository root.
2. Port Conflict Resolution: Host VS Code background services currently hold ports 5555–5557. The server was launched on free port 5558.

──────

### Live Server Status:

* Container: gr00t-server (gr00t-dev:latest)
* Endpoint: tcp://127.0.0.1:5558
* Model Checkpoint: /models/isaaclab_arena/locomanipulation_tutorial/checkpoint-20000
* Embodiment: NEW_EMBODIMENT
* Modality Config: g1_sim_wbc_data_config.py
* ZeroMQ Verification:

```text
{"status": "ok", "message": "Server is running"}
Modalities: ['video', 'state', 'action', 'language']
```

──────

### Useful Management Commands:

* Stream Server Logs:

```bash
docker logs -f gr00t-server
```

* Stop Server:

```bash
./docker/run_gr00t_server.sh -k
```

* Relaunch Command (with port 5558):

```bash
./docker/run_gr00t_server.sh \
    -m /models/isaaclab_arena/locomanipulation_tutorial/checkpoint-20000 \
    -e NEW_EMBODIMENT \
    -c isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_config.py \
    -p 5558 -d
```

### Option 1: Interactive GUI on Host Desktop (Recommended for Visualizing)

1. Open a terminal directly on your host machine (outside VS Code / DevContainer) and start the Arena container:

```bash
cd ~/Documents/GitHub/BoredEngineer/IsaacLab-Arena
```

```bash
./docker/run_docker.sh
```

(This opens an interactive shell inside the Arena container with full X11 display forwarding).

2. Inside that container shell, run the evaluation:

```bash
/isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
    --viz kit \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/g1_locomanip_gr00t_closedloop_config.yaml \
    --remote_host 127.0.0.1 \
    --remote_port 5558 \
    --num_steps 5000 \
    --enable_cameras \
    galileo_g1_locomanip_pick_and_place \
    --object brown_box \
    --embodiment g1_wbc_joint
```

──────

### Option 2: Start Arena in the Background from DevContainer

If you want to manage everything directly from your current DevContainer terminal:

1. Start the Arena container as a background daemon:

```bash
docker run -d \
    --name isaaclab_arena-latest \
    --privileged \
    --ulimit memlock=-1 \
    --ulimit stack=-1 \
    --ipc=host \
    --net=host \
    --gpus=all \
    -v /home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena:/workspaces/isaaclab_arena \
    -v /home/tarfy/datasets:/datasets \
    -v /home/tarfy/models:/models \
    -v /home/tarfy/eval:/eval \
    -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
    -e DISPLAY="${DISPLAY:-:0}" \
    -e ACCEPT_EULA=Y \
    -e PRIVACY_CONSENT=Y \
    -e ISAACLAB_PATH=/workspaces/isaaclab_arena/submodules/IsaacLab \
    isaaclab_arena:latest tail -f /dev/null
```

2. Execute the evaluation via docker exec:

```bash
docker exec -it isaaclab_arena-latest \
    /isaac-sim/python.sh /workspaces/isaaclab_arena/isaaclab_arena/evaluation/policy_runner.py \
    --headless \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/g1_locomanip_gr00t_closedloop_config.yaml \
    --remote_host 127.0.0.1 \
    --remote_port 5558 \
    --num_steps 1200 \
    --num_envs 5 \
    --enable_cameras \
    galileo_g1_locomanip_pick_and_place \
    --object brown_box \
    --embodiment g1_wbc_joint
```

### Run Full Episode Evaluation (--num_steps 1200)

To run full episodes to completion and compute the final task success rate:

```bash
docker exec -it isaaclab_arena-latest su tarfy -c \
    "cd /workspaces/isaaclab_arena && /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
    --headless \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/g1_locomanip_gr00t_closedloop_config.yaml \
    --remote_host 127.0.0.1 \
    --remote_port 5558 \
    --num_steps 1200 \
    --num_envs 5 \
    --enable_cameras \
    galileo_g1_locomanip_pick_and_place \
    --object brown_box \
    --embodiment g1_wbc_joint"
```

```bash
docker exec -it isaaclab_arena-latest su tarfy -c \
    "cd /workspaces/isaaclab_arena && /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
    --viz kit \
    --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
    --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/g1_locomanip_gr00t_closedloop_config.yaml \
    --remote_host 127.0.0.1 \
    --remote_port 5558 \
    --num_steps 1200 \
    --num_envs 5 \
    --enable_cameras \
    galileo_g1_locomanip_pick_and_place \
    --object brown_box \
    --embodiment g1_wbc_joint"
```