#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import argparse
import json
import os
import struct


def analyze_safetensors(model_path):
    print("\n==================================================")
    print(f"Analyzing Safetensors Model: {model_path}")
    print("==================================================")

    if not os.path.exists(model_path):
        print(f"Error: Model path '{model_path}' does not exist.")
        return

    try:
        with open(model_path, "rb") as f:
            header_size_bytes = f.read(8)
            if len(header_size_bytes) < 8:
                print("Error: File is too small to be a valid safetensors file.")
                return
            header_size = struct.unpack("<Q", header_size_bytes)[0]
            header_json_bytes = f.read(header_size)
            header = json.loads(header_json_bytes.decode("utf-8"))

            keys = [k for k in header.keys() if k != "__metadata__"]
            print(f"Total number of tensors in checkpoint: {len(keys)}\n")

            # Helper function to print tensor info
            def print_tensor_info(key):
                info = header[key]
                print(f"  {key}: shape={info['shape']}, dtype={info['dtype']}")

            # 1. State Encoder (Proprioception Input)
            print("--- 1. State Encoder (Proprioception Input) ---")
            state_enc_keys = [k for k in keys if "state_encoder" in k]
            if state_enc_keys:
                for k in sorted(state_enc_keys):
                    print_tensor_info(k)
            else:
                print("  No 'state_encoder' keys found in this checkpoint.")

            # 2. Action Decoder (Motor Output)
            print("\n--- 2. Action Decoder (Motor Output) ---")
            action_dec_keys = [k for k in keys if "action_decoder" in k]
            if action_dec_keys:
                for k in sorted(action_dec_keys):
                    print_tensor_info(k)
            else:
                print("  No 'action_decoder' keys found in this checkpoint.")

            # 3. Attention Heads / Transformer blocks
            print("\n--- 3. Transformer Attention / MLP Blocks ---")
            attn_keys = [k for k in keys if "attention" in k or "self_attn" in k]
            if attn_keys:
                print(f"  Found {len(attn_keys)} attention-related tensors.")
                # Show first few as example
                for k in sorted(attn_keys)[:10]:
                    print_tensor_info(k)
                if len(attn_keys) > 10:
                    print(f"    ... and {len(attn_keys) - 10} more.")
            else:
                print("  No attention/transformer layers found.")

            # 4. Search for other interesting keys
            print("\n--- 4. Final Projection / Output Head Keys ---")
            final_keys = [k for k in keys if "head" in k or "projection" in k or "output" in k]
            if final_keys:
                for k in sorted(final_keys)[:15]:
                    print_tensor_info(k)
                if len(final_keys) > 15:
                    print(f"  ... and {len(final_keys) - 15} more.")
            else:
                print("  No output/head layers found.")

            # 5. Geometry conditioning (Spatial Forcing / 3D-Mix)
            print("\n--- 5. Geometry Conditioning (Spatial Forcing / 3D-Mix) ---")
            geometry_keys = [k for k in keys if "geometry" in k]
            if geometry_keys:
                for k in sorted(geometry_keys):
                    print_tensor_info(k)
                teacher_keys = [k for k in geometry_keys if "geometry_encoder" in k]
                if teacher_keys:
                    print(
                        f"\n  WARNING: {len(teacher_keys)} frozen-teacher tensors are stored in this"
                        " checkpoint. They are dead payload -- the teacher is rebuilt from"
                        " geometry_encoder_id on load. A checkpoint saved after the state_dict fix"
                        " should have none."
                    )
            else:
                print(
                    "  No geometry tensors in this shard. They are few and land in one"
                    " shard, so check the others before concluding geometry_mode=off."
                )

            # 6. Anything the sections above did not claim.
            #
            # Without this, a newly added module is simply invisible: the sections match on fixed
            # name fragments, so tensors belonging to anything else are silently dropped and the
            # report still looks complete. That is how the geometry tensors went unnoticed.
            print("\n--- 6. Unclassified ---")
            classified = set()
            for fragment in ("state_encoder", "action_decoder", "geometry"):
                classified.update(k for k in keys if fragment in k)
            classified.update(k for k in keys if "attn" in k or "transformer_blocks" in k)
            unclassified = sorted(set(keys) - classified)
            print(f"  {len(unclassified)} of {len(keys)} tensors matched no section above.")
            for k in unclassified[:10]:
                print_tensor_info(k)
            if len(unclassified) > 10:
                print(f"  ... and {len(unclassified) - 10} more")

    except Exception as e:
        print(f"An error occurred while reading the safetensors file: {e}")


def main():
    parser = argparse.ArgumentParser(description="Analyze and debug safetensors checkpoints.")
    parser.add_argument(
        "model_path",
        type=str,
        nargs="?",
        default="model-00002-of-00002.safetensors",
        help="Path to the .safetensors model file (default: model-00002-of-00002.safetensors)",
    )
    args = parser.parse_args()

    # Try resolving path if relative
    model_path = args.model_path
    if not os.path.exists(model_path):
        # Look in workspace models directory recursively
        search_dirs = [os.getcwd(), "/workspaces/IsaacLab-Arena/models", "/workspaces/IsaacLab-Arena"]
        found = False
        for sdir in search_dirs:
            if not os.path.exists(sdir):
                continue
            for root, dirs, files in os.walk(sdir):
                if model_path in files:
                    model_path = os.path.join(root, model_path)
                    found = True
                    break
            if found:
                break

        # If still not found, search for any *.safetensors
        if not found:
            safetensors_files = []
            for sdir in search_dirs:
                if not os.path.exists(sdir):
                    continue
                for root, dirs, files in os.walk(sdir):
                    for file in files:
                        if file.endswith(".safetensors"):
                            safetensors_files.append(os.path.join(root, file))
            if safetensors_files:
                print(f"Requested file '{args.model_path}' not found, but found these .safetensors files:")
                for fpath in safetensors_files[:5]:
                    print(f"  - {fpath}")
                # Use the first one
                model_path = safetensors_files[0]
                print(f"Defaulting to: {model_path}\n")

    analyze_safetensors(model_path)


if __name__ == "__main__":
    main()
