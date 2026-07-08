import xml.etree.ElementTree as ET

urdf_path = '/workspaces/IsaacLab-Arena/isaaclab_arena_g1/assets/urdf/g1_29dof_with_hand.urdf'
tree = ET.parse(urdf_path)
root = tree.getroot()

joints = []
for joint in root.findall('joint'):
    if joint.get('type') != 'fixed':
        joints.append(joint.get('name'))

print("Joints in URDF (alphabetical?):")
# Isaac Sim typically orders joints by parsing order, but we can't be sure unless we see sim order.
# Actually, the user's sim joint pos has length 61.
# G1 Brainco has 61 active joints in Isaac Sim.
for i, j in enumerate(joints):
    print(f"Index {i:2}: {j}")

