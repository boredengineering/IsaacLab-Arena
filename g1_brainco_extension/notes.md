# Notes and Ideas on features to implement

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