# Notes and Ideas on features to implement

The project certainly need a change since the Code Structure is flawed

```text
g1_brainco_extension/
├── data/                  # Local assets (USDs, meshes)
├── embodiments/
│   └── g1_brainco.py      # Custom robot model & asset registration
├── environments/
│   └── pick_drink.py      # Task definition & background setup
├── mdp/
│   ├── robot_configs.py   # Robot-specific constants (friction, postures)
│   └── actions/
│       ├── wbc_action.py  # Mapping logic Sim <-> WBC
│       └── wbc_action_cfg.py
├── assets.py              # Custom asset registration (CokeCan, etc.)
└── README.md
```

should change the folder structure to

```{{text}}
g1_brainco_extension/
├── assets/                  # Local assets
├── datasets/                # dataset for the robot
├── embodiments/
│   ├── mdp/
│   │   ├── robot_configs.py   # Robot-specific constants (friction, postures)
│   │   └── actions/
│   │       ├── wbc_action.py  # Mapping logic Sim <-> WBC
│   │       └── wbc_action_cfg.py
│   └── g1_brainco.py        # Custom robot model & asset registration
├── environments/
│   └── pick_drink.py      # Task definition & background setup
├── task/
│   ├── g1_brainco_locomanip_pick_and_place_task.py
│   └── g1_brainco_pick_and_place_task.py
├── policy/
│   ├── config/
│   │   ├── g1_brainco_locomanip_gr00t_closedloop_config.yaml
│   │   └── g1_brainco_static_gr00t_closedloop_config.yaml
│   └── g1_brainco_gr00t_closedloop_policy.py
├── assets.py              # Custom asset registration (CokeCan, etc.)
└── README.md
```

## notes

Using the ObjectReference from isaaclab_arena.assets.object_reference seems to be a way to get the table top as reference to spawn objects on top of it dynamically.

```python
from isaaclab_arena.assets.object_reference import ObjectReference
```

The ObjectReference is implemented here in gr1_table_multi_object_no_collision_environment.py inside isaaclab_arena_environments.

```python
# Table surface as anchor for On relations
tabletop_reference = ObjectReference(
    name="table",
    prim_path="{ENV_REGEX_NS}/office_table/Geometry/sm_tabletop_a01_01/sm_tabletop_a01_top_01",
    parent_asset=table_background,
)
tabletop_reference.add_relation(IsAnchor())
```

Given the proper reference like the tabletop_reference then it implements the list of objects.

```python
object_names = getattr(args_cli, "objects", None) or DEFAULT_TABLE_OBJECTS
placeable_assets = []
for name in object_names:
    obj = self.asset_registry.get_asset_by_name(name)()
    obj.add_relation(On(tabletop_reference))
    placeable_assets.append(obj)
# NoCollision between all pairs is added automatically by ArenaEnvBuilder before solving.
```

Some examples separate the configurations of the embodiment into env vars.


For the galileo_g1_static_pick_and_place_environment.py the embodiment properties are being imported from isaaclab_arena_environments.mdp.galileo_g1_static_pick_and_place.robot_configs

So they are using robot_configs.

```python
from isaaclab_arena_environments.mdp.galileo_g1_static_pick_and_place.robot_configs import (
    G1_STATIC_FINGER_DYNAMIC_FRICTION,
    G1_STATIC_FINGER_FRICTION_MATERIAL_PATH,
    G1_STATIC_FINGER_PRIM_NAME_MARKERS,
    G1_STATIC_FINGER_STATIC_FRICTION,
    G1_STATIC_OPEN_ARM_JOINT_POS,
)
```

The variables from the robot_configs are setting up the properties for set_finger_contact_friction().

```python
embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(
    enable_cameras=args_cli.enable_cameras,
    lock_waist=args_cli.lock_waist,
)
embodiment.set_finger_contact_friction(
    material_path=G1_STATIC_FINGER_FRICTION_MATERIAL_PATH,
    static_friction=G1_STATIC_FINGER_STATIC_FRICTION,
    dynamic_friction=G1_STATIC_FINGER_DYNAMIC_FRICTION,
    prim_name_markers=G1_STATIC_FINGER_PRIM_NAME_MARKERS,
)
```

G1_STATIC_OPEN_ARM_JOINT_POS

```python
# Robot pose is tuned for the same-shelf static task: slightly forward toward
# the table while preserving the lateral offset that keeps both arms usable.
# The controller dynamically lifts the pelvis to ~z=0.74 at runtime;
# init_state.pos.z=0 is correct.
embodiment.set_initial_pose(Pose(position_xyz=(0.25, 0.08, 0.0), rotation_xyzw=(0.0, 0.0, 0.0, 1.0)))
embodiment.set_joint_initial_pos(G1_STATIC_OPEN_ARM_JOINT_POS)
```

The args_cli.embodiment is the following property:

```python
# Default embodiment is g1_wbc_agile_pink: AGILE end-to-end velocity policy for
# whole-body balance + PinkIK upper body. The static task never walks, so AGILE's
# single-policy backend is a better fit than HOMIE's stand+walk split (which
# ``g1_wbc_pink`` ships). Same 23-D action layout and OpenXR retargeter as the
# locomanip env -- the only knob that flips is which lower-body ONNX policy gets
# loaded by the WBC factory. ``g1_wbc_pink`` is still accepted as an override
# for users who specifically want HOMIE.
parser.add_argument("--embodiment", type=str, default="g1_wbc_agile_pink")
```

The lock waist is important since most of these models are not Whole Body.

```python
# The static task is upper-body-only by design, so we lock the 3 waist
# joints by default. Pass ``--no-lock_waist`` to fall back to the default
# AGILE-pink behaviour (waist active in Pink IK for extended arm reach).
parser.add_argument(
    "--lock_waist",
    action=argparse.BooleanOptionalAction,
    default=True,
    help=(
        "Remove waist_yaw/roll/pitch from the upper-body Pink IK active set so "
        "the torso stays fixed during teleoperation and recorded observations. "
        "On by default for this static task; pass --no-lock_waist to allow the "
        "IK to use the waist for extended arm reach (the production AGILE-pink "
        "default)."
    ),
```

should add the task description in to code ?

It is recurrent structure to have to define the task such as:

```python
from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
```

Possibly using the PickAndPlaceTask from the: from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask. Might not be an ideal solution for defined the Task for the G1 robot.

Need to evaluate if it need better task denifinition like in IsaacLab for RL.


How to make task taking the example from: g1_locomanip_pick_and_place_task.py

This is used for galileo_g1_locomanip_pick_and_place_environment.py where they implement body locomotaion with manipulation

```python
from isaaclab_arena.tasks.task_base import TaskBase
```


```python
class G1LocomanipPickAndPlaceTask(TaskBase):
```

The G1LocomanipPickAndPlaceTask inherits the task base and it is add

```python
class G1LocomanipPickPlaceMimicEnvCfg(MimicEnvCfg):
```

In this class we are adding all the subclasses for the robot to break down the task into a MDP type of process with a well degine strategy and termination.

## Reviewing g1_locomanip_pick_and_place_task.py

✦ In the context of the Isaac Lab Arena project, the G1LocomanipPickAndPlaceTask represents a sophisticated intersection of locomotion and manipulation (hence "Locomanipulation").

Scientifically and educationally, here is a breakdown of what this task is doing and why it is structured this way.

1. The Scientific Core: Locomanipulation

Locomanipulation is the ability of a robot to coordinate its movement (locomotion) with its handling of objects (manipulation). In the case of the Unitree G1 humanoid, this is a "Whole-Body Control" (WBC) challenge. 

* Challenge: The robot must maintain balance (centroidal dynamics) while walking, turning, and reaching for a box on a shelf.
* Approach: The task breaks down a long-horizon objective into discrete, manageable subtasks.

2. Educational Breakdown of the Task Class

The G1LocomanipPickAndPlaceTask (found in g1_locomanip_pick_and_place_task.py) acts as the objective manager. It defines the "What" independently of the "How":

* Success Metrics: It uses a SuccessRateMetric. Educationally, this is the simplest way to measure performance: Did the box end up in the bin?
* Termination Logic:
    * Success: Defined by objects_in_proximity. It checks if the pick_up_object is within a specific 3D box around the destination_bin.
    * Failure: Defined by object_dropped. If the object's height falls below a threshold (-0.6m), the episode ends. This teaches the agent that "losing the object" is a terminal failure.
* Mimicry Configuration (MimicEnvCfg): This is the most "scientific" part of the code. It defines a state machine for Data Generation and Imitation Learning:
    * Body Subtasks: navigate_to_table → navigate_turn_inplace → navigate_to_bin.
    * Arm Subtasks: idle → grasp_and_idle.
    * This structure allows researchers to train policies (like NVIDIA's GR00T) by showing it demonstrations of these individual "primitives."

3. Integration in the Galileo Environment

In galileo_g1_locomanip_pick_and_place_environment.py, this task is brought to life:

* The Scene: A specific background called galileo_locomanip.
* The Robot: The g1_wbc_pink embodiment, which uses a Whole-Body Controller.
* Navigation Subgoals: The environment provides specific (x, y, θ) waypoints. For example:

```python
action_cfg.g1_action.navigation_subgoals = [
    ([0.18, 0.18, 0.0], False),     # Move to shelf
    ([0.18, 0.18, -1.78], True),    # Turn in place
    ([-0.0955, -1.1070, -1.78], False), # Move to bin
]
```

This shows that the "Task" provides the objective, while the "Environment" provides the specific roadmap for the G1 robot to follow.

Summary Comparison
┌────────────────────────────┬────────────────────────────────────────┬─────────────────────────────────┐
│ Component                  │ Responsibility                         │ Educational takeaway            │
├────────────────────────────┼────────────────────────────────────────┼─────────────────────────────────┤
│ Task (G1Locomanip...)      │ Define Success/Failure, Subtask labels │ Objectives & Semantics          │
│ Environment (GalileoG1...) │ Layout objects, Set waypoints          │ Scenarios & Spacial Constraints │
│ Embodiment (g1_wbc_pink)   │ Move joints, Balance, Walk             │ Physics & Control               │
└────────────────────────────┴────────────────────────────────────────┴─────────────────────────────────┘

By separating these, Isaac Lab Arena allows you to swap the robot (e.g., use a GR1 instead of G1) or the scene (e.g., a kitchen instead of a shelf) without rewriting the logic of what "Pick and Place" actually means.

Reflection: Scientifically, this architecture mirrors how we think about human behavior. We have a high-level goal (Task), we operate in a specific room (Scene), and we use our physical body (Embodiment) to execute the movements. The G1LocomanipPickAndPlaceTask is the "brain's" high-level plan for that specific 30-second interaction.

## How to use Newton

Attention !!!

Only dexsuite_lift has Newton

The environment does not contain a physics-specific callback. Physics backend selection is handled globally by the --presets CLI flag (e.g. --presets newton), which is applied by ArenaEnvBuilder after all environment-specific configuration.

This is handled inside the arena_env_builder.py inside isaaclab_arena/environments/ 

here is a segment of the code around line 270

```python
# Apply the environment configuration callback if it is set
# This can be used to modify the simulation configuration, etc.
if self.arena_env.env_cfg_callback is not None:
    env_cfg = self.arena_env.env_cfg_callback(env_cfg)

# Apply the --presets CLI flag (e.g. --presets newton).
# This runs after the callback so the user's CLI choice is the final authority.
presets = getattr(self.args, "presets", None)
if presets is not None:
    from isaaclab_arena.environments.isaaclab_arena_manager_based_env import ArenaPhysicsCfg

    env_cfg.sim.physics = getattr(ArenaPhysicsCfg(), presets)

    # Set replicate_physics for shared physics representations.
    # For Newton, wihotut this flag, the simulation initialization
    # takes a very long time for large number of parallel environments.
    if presets == "newton":
        env_cfg.scene.replicate_physics = True
```

