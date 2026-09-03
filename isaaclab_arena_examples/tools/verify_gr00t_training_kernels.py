# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pre-flight check for GR00T fine-tuning kernel support on the local GPU architecture.

Motivation: fused-attention kernels are the usual casualty of a new CUDA architecture, and a
failure surfaces in the *backward* pass, so an inference smoke test does not catch it.

The check that matters depends on which modules are being trained, and the default GR00T
fine-tune config makes that non-obvious:

    tune_llm = False        tune_visual = False        # backbone frozen -> no backward
    tune_projector = True   tune_diffusion_model = True    # action head trained

The frozen Qwen3 backbone is the only consumer of flash-attn (``qwen3_backbone.py:168-178``,
and it silently falls back to SDPA when flash-attn is absent). The DiT action head -- the module
the default config actually backpropagates through -- runs diffusers ``Attention`` under
``_sdpa_context()`` (``dit.py:47``), which is a no-op except on Spark sm121. So on a default
fine-tune the load-bearing kernel is **SDPA backward at the DiT's shapes**, not flash-attn.

This script therefore probes both paths independently and labels which one gates which config,
using the real shapes and masking from ``gr00t/configs/model/gr00t_n1d7.py``.

On why the real shapes matter -- and where they do not. Measured on sm120 / torch 2.7:
head dims 32, 48, 64, 72, 128 and 256 all report every SDPA backend as available, so backend
*dispatch* is not head-dim sensitive in the range that matters here, and a head_dim=64 probe is
not misleading on that count. What the real geometry does buy is memory realism (32 heads x 48 =
1536 inner width is 3x an 8 x 64 = 512 probe) and the correct masking pattern: the DiT's
cross-attention is **not causal**, so a ``causal=True`` probe exercises the backbone's attention
pattern rather than the action head's.

Run inside the GR00T image, which is where flash-attn is installed::

    python isaaclab_arena_examples/tools/verify_gr00t_training_kernels.py
"""

from __future__ import annotations

import os
import traceback

import torch

# Real GR00T N1.7 action-head geometry (gr00t/configs/model/gr00t_n1d7.py:91-106).
DIT_NUM_LAYERS = 16
DIT_NUM_HEADS = 32
DIT_HEAD_DIM = 48
DIT_INNER_DIM = DIT_NUM_HEADS * DIT_HEAD_DIM  # 1536
# The action head feeds state+action tokens in at input_embedding_dim (1536), which equals
# num_heads * head_dim; hidden_size (1024) is the *output* projection width, not the input.
DIT_INPUT_DIM = 1536
DIT_OUTPUT_DIM = 1024
BACKBONE_EMBED_DIM = 2048  # cross-attention key/value width
ACTION_SEQ_LEN = 41  # state token + action horizon
VL_SEQ_LEN = 512  # vision + language tokens, order of magnitude
BATCH = 2


def _section(title: str) -> None:
    print("\n" + "=" * 78)
    print(f" {title}")
    print("=" * 78)


def report_environment() -> tuple[int, int]:
    """Print torch/CUDA/arch details and return the device compute capability."""
    _section("1. Environment")
    print(f"torch                 : {torch.__version__}")
    print(f"torch.version.cuda    : {torch.version.cuda}")
    if not torch.cuda.is_available():
        print("CUDA not available -- nothing further can be verified.")
        raise SystemExit(1)

    capability = torch.cuda.get_device_capability()
    arch_list = torch.cuda.get_arch_list()
    sm_tag = f"sm_{capability[0]}{capability[1]}"
    print(f"device                : {torch.cuda.get_device_name(0)}")
    print(f"compute capability    : {capability[0]}.{capability[1]}  ({sm_tag})")
    print(f"arch list             : {arch_list}")

    if sm_tag in arch_list:
        print(f"-> {sm_tag} is compiled in natively.")
    else:
        # A missing native arch is not fatal: PTX from a lower arch is JIT-compiled at first
        # launch. That costs a one-off delay and can differ numerically, so it is worth
        # distinguishing from a hard lack of support rather than treating it as failure.
        ptx = [a for a in arch_list if a.startswith("compute_")]
        print(f"-> {sm_tag} NOT compiled in. PTX available: {ptx or 'none'}")
        print("   Kernels will JIT from PTX if a compatible compute_* target is present.")

    if capability == (12, 1):
        print("   NOTE: sm121 (Spark) -- dit.py forces the math SDPA backend on this arch.")
    elif capability[0] == 12:
        print("   NOTE: Blackwell, but not sm121. The dit.py math-SDPA guard does NOT apply here;")
        print("         this arch takes the default SDPA dispatch path.")
    return capability


def check_flash_attn() -> bool:
    """Probe flash-attn forward and backward. Gates ``tune_visual`` / ``tune_llm`` only."""
    _section("2. flash-attn  (gates tune_visual=True / tune_llm=True ONLY)")
    try:
        import flash_attn
        from flash_attn import flash_attn_func
    except ImportError as exc:
        print(f"flash-attn not importable: {exc}")
        print("-> The Qwen3 backbone falls back to SDPA (qwen3_backbone.py:175).")
        print("-> Harmless for a DEFAULT fine-tune, which freezes the backbone anyway.")
        return False

    print(f"flash_attn version    : {getattr(flash_attn, '__version__', 'unknown')}")
    # Qwen3-VL head dim, not the DiT's -- this path is the backbone's.
    q, k, v = (
        torch.randn(BATCH, VL_SEQ_LEN, 8, 64, dtype=torch.bfloat16, device="cuda", requires_grad=True)
        for _ in range(3)
    )
    try:
        out = flash_attn_func(q, k, v, causal=True)
        out.sum().backward()
        assert q.grad is not None and torch.isfinite(q.grad).all(), "flash-attn produced non-finite grads"
        print("-> forward + backward OK, grads finite.")
        return True
    except Exception as exc:
        print(f"-> FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


def check_sdpa_at_dit_shapes() -> bool:
    """Probe SDPA forward and backward at the DiT's real shapes. Gates the DEFAULT fine-tune."""
    _section("3. SDPA at real DiT shapes  (gates the DEFAULT fine-tune)")
    print(f"heads={DIT_NUM_HEADS}  head_dim={DIT_HEAD_DIM}  inner={DIT_INNER_DIM}  kv_dim={BACKBONE_EMBED_DIM}")

    ok = True
    shapes = (
        ("self-attention (action tokens)", ACTION_SEQ_LEN),
        ("cross-attention (VL tokens)", VL_SEQ_LEN),
    )
    for label, kv_len in shapes:
        q = torch.randn(
            BATCH, DIT_NUM_HEADS, ACTION_SEQ_LEN, DIT_HEAD_DIM,
            dtype=torch.bfloat16, device="cuda", requires_grad=True,
        )
        k = torch.randn(
            BATCH, DIT_NUM_HEADS, kv_len, DIT_HEAD_DIM,
            dtype=torch.bfloat16, device="cuda", requires_grad=True,
        )
        v = torch.randn_like(k, requires_grad=True)
        try:
            out = torch.nn.functional.scaled_dot_product_attention(q, k, v)
            out.sum().backward()
            finite = q.grad is not None and torch.isfinite(q.grad).all()
            print(f"-> {label}: forward + backward OK, grads finite={bool(finite)}")
            ok = ok and bool(finite)
        except Exception as exc:
            print(f"-> {label}: FAILED: {type(exc).__name__}: {exc}")
            ok = False

    # Report which backends the dispatcher will actually consider for this shape.
    try:
        from torch.backends.cuda import can_use_efficient_attention, can_use_flash_attention
        from torch.backends.cuda import SDPAParams

        params = SDPAParams(
            torch.randn(BATCH, DIT_NUM_HEADS, ACTION_SEQ_LEN, DIT_HEAD_DIM, dtype=torch.bfloat16, device="cuda"),
            torch.randn(BATCH, DIT_NUM_HEADS, VL_SEQ_LEN, DIT_HEAD_DIM, dtype=torch.bfloat16, device="cuda"),
            torch.randn(BATCH, DIT_NUM_HEADS, VL_SEQ_LEN, DIT_HEAD_DIM, dtype=torch.bfloat16, device="cuda"),
            None, 0.0, False, False,
        )
        print(f"   backend availability: flash={can_use_flash_attention(params)} "
              f"mem_efficient={can_use_efficient_attention(params)}")
    except Exception as exc:
        print(f"   (backend introspection unavailable: {type(exc).__name__}: {exc})")

    return ok


def check_real_dit_block() -> bool:
    """Forward and backward through the actual AlternateVLDiT. The definitive check."""
    _section("4. Real AlternateVLDiT forward + backward  (definitive)")
    try:
        from gr00t.model.modules.dit import AlternateVLDiT
    except ImportError as exc:
        print(f"gr00t not importable ({exc}); skipping. Run this inside the GR00T image.")
        return True

    try:
        dit = AlternateVLDiT(
            num_layers=DIT_NUM_LAYERS,
            num_attention_heads=DIT_NUM_HEADS,
            attention_head_dim=DIT_HEAD_DIM,
            output_dim=DIT_OUTPUT_DIM,
            interleave_self_attention=True,
            cross_attention_dim=BACKBONE_EMBED_DIM,
            attend_text_every_n_blocks=2,
        ).to(device="cuda", dtype=torch.bfloat16)

        hidden = torch.randn(BATCH, ACTION_SEQ_LEN, DIT_INPUT_DIM, dtype=torch.bfloat16, device="cuda")
        encoder = torch.randn(BATCH, VL_SEQ_LEN, BACKBONE_EMBED_DIM, dtype=torch.bfloat16, device="cuda")
        timestep = torch.zeros(BATCH, dtype=torch.long, device="cuda")
        image_mask = torch.zeros(BATCH, VL_SEQ_LEN, dtype=torch.bool, device="cuda")
        image_mask[:, : VL_SEQ_LEN // 2] = True
        attn_mask = torch.ones(BATCH, VL_SEQ_LEN, dtype=torch.bool, device="cuda")

        out = dit(
            hidden_states=hidden,
            encoder_hidden_states=encoder,
            timestep=timestep,
            image_mask=image_mask,
            backbone_attention_mask=attn_mask,
        )
        out.sum().backward()

        grads = [p.grad for p in dit.parameters() if p.grad is not None]
        assert grads, "no parameter received a gradient"
        all_finite = all(torch.isfinite(g).all() for g in grads)
        print(f"-> forward + backward OK. {len(grads)} tensors with grads, all finite={all_finite}")
        print(f"   GR00T_DIT_SDPA_MODE = {os.environ.get('GR00T_DIT_SDPA_MODE', '<unset>')}")
        return bool(all_finite)
    except Exception as exc:
        print(f"-> FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        print("\n   Mitigation to try before patching anything:")
        print("     GR00T_DIT_SDPA_MODE=math  (dit.py:38 -- forces the safe math SDPA backend)")
        return False


def main() -> int:
    capability = report_environment()
    flash_ok = check_flash_attn()
    sdpa_ok = check_sdpa_at_dit_shapes()
    dit_ok = check_real_dit_block()

    _section("Verdict")
    print(f"Default fine-tune (tune_visual=False, tune_llm=False):  {'READY' if sdpa_ok and dit_ok else 'BLOCKED'}")
    print("  Requires: SDPA backward at DiT shapes + the real DiT backward.")
    print(f"Escalated fine-tune (tune_visual=True or tune_llm=True): {'READY' if flash_ok else 'DEGRADED'}")
    print("  Requires flash-attn backward; without it the backbone silently uses SDPA,")
    print("  which is slower and more memory-hungry but not incorrect.")
    if capability[0] == 12 and capability != (12, 1):
        print("\nNote: this arch is Blackwell but not sm121, so dit.py's math-SDPA workaround is")
        print("inactive. If the DiT check failed, try GR00T_DIT_SDPA_MODE=math before anything else.")
    return 0 if (sdpa_ok and dit_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
