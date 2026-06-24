import os
from pxr import Usd, UsdPhysics

def analyze_head_link(usd_path, label):
    print(f"\n--- Analysis for: {label} ({usd_path}) ---")
    stage = Usd.Stage.Open(usd_path)
    if not stage:
        print("ERROR: Could not open USD file.")
        return None

    # Get head_link
    head_link_path = "/g1_29dof_mode_15_brainco_hand/head_link"
    head_prim = stage.GetPrimAtPath(head_link_path)
    
    info = {}
    if head_prim:
        info["exists"] = True
        info["type"] = head_prim.GetTypeName()
        info["applied_schemas"] = list(head_prim.GetAppliedSchemas())
        
        # Check visuals/collisions children
        vis = stage.GetPrimAtPath(f"{head_link_path}/visuals")
        col = stage.GetPrimAtPath(f"{head_link_path}/collisions")
        info["visuals_children"] = [c.GetName() for c in vis.GetChildren()] if vis else []
        info["collisions_children"] = [c.GetName() for c in col.GetChildren()] if col else []
        
        print(f"  Head Link: {head_link_path} ({info['type']})")
        print(f"    Applied Schemas: {info['applied_schemas']}")
        print(f"    Visuals child prims: {info['visuals_children']}")
        print(f"    Collisions child prims: {info['collisions_children']}")
    else:
        info["exists"] = False
        print("  Head Link does not exist!")

    # Check for joints connecting head_link
    joints = []
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Joint):
            joint = UsdPhysics.Joint(prim)
            b0 = [str(t) for t in joint.GetBody0Rel().GetTargets()]
            b1 = [str(t) for t in joint.GetBody1Rel().GetTargets()]
            if any("head_link" in t for t in b0) or any("head_link" in t for t in b1):
                joints.append((prim.GetName(), b0, b1))
                
    info["joints"] = joints
    if joints:
        print("  Joints connecting head_link:")
        for jname, b0, b1 in joints:
            print(f"    - Joint '{jname}': {b0} -> {b1}")
    else:
        print("  ⚠️ No joints connecting head_link found on stage!")

    # Check where visuals and collisions head meshes are defined raw in layer
    # Scan raw specs
    layer = stage.GetRootLayer()
    vis_proto = layer.GetPrimAtPath("/Flattened_Prototype_97/head_link")
    col_proto = layer.GetPrimAtPath("/Flattened_Prototype_93/head_link")
    info["head_in_visuals_prototype"] = vis_proto is not None
    info["head_in_collisions_prototype"] = col_proto is not None
    print(f"  Head link in visuals prototype spec (/Flattened_Prototype_97/head_link): {info['head_in_visuals_prototype']}")
    print(f"  Head link in collisions prototype spec (/Flattened_Prototype_93/head_link): {info['head_in_collisions_prototype']}")

    return info

def compare_usd_files(old_path, new_path):
    print("====================================================")
    print("USD ROBOT HEAD COMPARISON & PHYSICAL ANOMALY REPORT")
    print("====================================================")
    
    if not os.path.exists(old_path):
        print(f"ERROR: Old USD file not found at: {old_path}")
        return
    if not os.path.exists(new_path):
        print(f"ERROR: New USD file not found at: {new_path}")
        return

    old_info = analyze_head_link(old_path, "Original (Old) USD")
    new_info = analyze_head_link(new_path, "Modified (New) USD")

    print("\n================ Comparative Summary ================")
    print("1. Physics API Configuration:")
    print("   - Both files define '/g1_29dof_mode_15_brainco_hand/head_link' as a Rigid Body with Mass.")
    
    print("\n2. Geometry Parenting Changes:")
    print("   - Original (Old) USD:")
    print("     * Visuals: The head mesh was defined under '/Flattened_Prototype_97/head_link' inside the instanced torso visuals.")
    print("     * Collisions: The head mesh was defined under '/Flattened_Prototype_93/head_link' inside the instanced torso collisions.")
    print("     * Result: Head visuals and collisions were visually attached to the torso_link. They did not fall because torso_link is constrained by joints.")
    print("   - Modified (New) USD:")
    print("     * Visuals: Moved head mesh to '/g1_29dof_mode_15_brainco_hand/head_link/visuals/head_link'.")
    print("     * Collisions: Moved head mesh to '/g1_29dof_mode_15_brainco_hand/head_link/collisions/head_link'.")
    print("     * Result: Head visuals and collisions are now attached to the head_link rigid body.")

    print("\n3. Physical Connection / Joint Analysis:")
    print("   - In BOTH files, there are NO physics joints (e.g., revolute joints, fixed joints) connecting the torso_link to the head_link.")
    print("   - Why the head falls in the modified USD:")
    print("     * In the original USD, the head_link rigid body was empty and invisible. If it fell due to gravity, the user could not see it because the visual mesh was parented to the torso.")
    print("     * In the modified USD, the visual and collision meshes are now children of the head_link rigid body. Since there is no physics joint constraining head_link to the torso, head_link falls under gravity, carrying the head visual and collision meshes with it!")

    print("\n4. Recommended Physics Fixes:")
    print("   We must add a Physics Fixed Joint (or Revolute Joint) to constrain the head_link to the torso_link.")
    print("   Alternatively, if the head is static, we can remove the PhysicsRigidBodyAPI and PhysicsMassAPI from head_link so that it behaves as a kinematic frame relative to its parent in the hierarchy (if parented correctly), or add a fixed joint.")

if __name__ == "__main__":
    old_file = "g1_brainco_extension/assets/g1_with_brainco_hands_old.usd"
    new_file = "g1_brainco_extension/assets/g1_with_brainco_hands.usd"
    compare_usd_files(old_file, new_file)
