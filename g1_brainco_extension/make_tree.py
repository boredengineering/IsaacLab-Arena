import sys
import argparse
from pxr import Usd, UsdPhysics

def print_tree(usd_path, show_arcs=False, show_physics=False, output_file=None):
    """Walks the USD stage and formats it like a tree with physics annotations."""
    stage = Usd.Stage.Open(usd_path)
    if not stage:
        print(f"Error: Could not open stage at {usd_path}")
        return

    out = sys.stdout
    if output_file:
        try:
            out = open(output_file, 'w', encoding='utf-8')
        except IOError as e:
            print(f"Error opening output file: {e}")
            return

    # Keep track of rigid bodies and joint connections
    rigid_bodies = set()
    connected_bodies = set()

    for prim in stage.Traverse():
        depth = str(prim.GetPath()).count('/') - 1
        indent = '    ' * depth
        prim_type = prim.GetTypeName()
        
        # Physics detection
        physics_str = ""
        if show_physics:
            applied_schemas = prim.GetAppliedSchemas()
            schemas = []
            if 'PhysicsRigidBodyAPI' in applied_schemas:
                schemas.append("RigidBody")
                rigid_bodies.add(str(prim.GetPath()))
            if 'PhysicsMassAPI' in applied_schemas:
                schemas.append("Mass")
            if schemas:
                physics_str = f" [Physics: {', '.join(schemas)}]"
                
            if prim.IsA(UsdPhysics.Joint):
                joint = UsdPhysics.Joint(prim)
                b0 = joint.GetBody0Rel().GetTargets()
                b1 = joint.GetBody1Rel().GetTargets()
                b0_str = str(b0[0]) if b0 else "None"
                b1_str = str(b1[0]) if b1 else "None"
                physics_str = f" [Joint: {b0_str} -> {b1_str}]"
                if b0: connected_bodies.add(str(b0[0]))
                if b1: connected_bodies.add(str(b1[0]))

        type_str = f" ({prim_type})" if prim_type else ""
        out.write(f"{indent}└── {prim.GetName()}{type_str}{physics_str}\n")
        
        if show_arcs:
            prim_stack = prim.GetPrimStack()
            for spec in prim_stack:
                if spec.hasReferences:
                    for ref in spec.referenceList.prependedItems:
                        out.write(f"{indent}    └─ [Ref] {ref.assetPath} -> {ref.primPath}\n")
                    # Also print added/appended references
                    for ref in spec.referenceList.addedItems:
                        out.write(f"{indent}    └─ [Added Ref] {ref.assetPath} -> {ref.primPath}\n")
                if spec.hasPayloads:
                    for pl in spec.payloadList.prependedItems:
                        out.write(f"{indent}    └─ [Payload] {pl.assetPath} -> {pl.primPath}\n")
                if spec.hasInheritPaths:
                    for inh in spec.inheritPathList.prependedItems:
                        out.write(f"{indent}    └─ [Inherit] {inh}\n")

    if show_physics:
        out.write("\n================ Physics Diagnostics ================\n")
        # Identify orphaned rigid bodies (excluding the root/pelvis which is intentionally free or fixed to root_joint)
        orphans = []
        for body in rigid_bodies:
            # The root pelvis is typically connected to root_joint, check if it's connected
            if body not in connected_bodies and "pelvis" not in body.lower():
                orphans.append(body)
        
        if orphans:
            out.write("⚠️ WARNING: Found rigid bodies with NO joint connections (will fall under gravity):\n")
            for o in orphans:
                out.write(f"  - {o}\n")
        else:
            out.write("✓ No unconnected rigid bodies found (excluding pelvis).\n")

    if output_file:
        out.close()
        print(f"Tree successfully saved to {output_file}!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="USD Tree Generator for debugging.")
    parser.add_argument("--input", type=str, default="./g1_brainco_extension/assets/g1_with_brainco_hands.usd", help="Path to input USD file")
    parser.add_argument("--output", type=str, default=None, help="Path to output TXT file")
    parser.add_argument("--show-arcs", action="store_true", help="Print composition arcs (references, payloads, inherits)")
    parser.add_argument("--show-physics", action="store_true", help="Print physics annotations and check joint connectivity")
    
    args = parser.parse_args()
    print_tree(args.input, show_arcs=args.show_arcs, show_physics=args.show_physics, output_file=args.output)
