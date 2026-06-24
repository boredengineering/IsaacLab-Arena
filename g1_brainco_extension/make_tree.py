# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

import sys
import argparse
from pxr import Usd

def print_tree(usd_path, show_arcs=False, output_file=None):
    """Walks the USD stage and formats it like a tree."""
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

    for prim in stage.Traverse():
        depth = str(prim.GetPath()).count('/') - 1
        indent = '    ' * depth
        prim_type = prim.GetTypeName()
        type_str = f" ({prim_type})" if prim_type else ""
        
        out.write(f"{indent}└── {prim.GetName()}{type_str}\n")
        
        if show_arcs:
            prim_stack = prim.GetPrimStack()
            for spec in prim_stack:
                if spec.hasReferences:
                    for ref in spec.referenceList.prependedItems:
                        out.write(f"{indent}    └─ [Ref] {ref.assetPath} -> {ref.primPath}\n")
                if spec.hasPayloads:
                    for pl in spec.payloadList.prependedItems:
                        out.write(f"{indent}    └─ [Payload] {pl.assetPath} -> {pl.primPath}\n")
                if spec.hasInheritPaths:
                    for inh in spec.inheritPathList.prependedItems:
                        out.write(f"{indent}    └─ [Inherit] {inh}\n")

    if output_file:
        out.close()
        print(f"Tree successfully saved to {output_file}!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="USD Tree Generator for debugging.")
    parser.add_argument("--input", type=str, default="./g1_brainco_extension/assets/g1_with_brainco_hands.usd", help="Path to input USD file")
    parser.add_argument("--output", type=str, default=None, help="Path to output TXT file")
    parser.add_argument("--show-arcs", action="store_true", help="Print composition arcs (references, payloads, inherits)")
    
    args = parser.parse_args()
    print_tree(args.input, show_arcs=args.show_arcs, output_file=args.output)
