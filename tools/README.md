# Tools

Utility scripts for debugging and inspecting models and robot configurations used in IsaacLab Arena.

## analyze_model_tensors.py

Reads a `.safetensors` **header only** -- no weights loaded -- and groups the tensors by
architectural component: state encoder, action decoder, attention/MLP blocks, output projections,
geometry conditioning, and anything unclassified.

```bash
python tools/analyze_model_tensors.py <checkpoint>/model-00003-of-00003.safetensors
```

Recovered from `origin/0.2.1-dev`, where a larger `tools/` tree of debug and analysis scratch
scripts still lives (`tools/debug/`, `tools/analyze/`, `tools/extract/`, ...). Those were WBC and
joint-order scratch work; recover individually with
`git show origin/0.2.1-dev:tools/<path>` rather than porting the tree.

Two sections were added when it was recovered:

- **Geometry conditioning**, which also warns when a checkpoint carries the frozen teacher's
  tensors. Those are dead payload: the teacher is rebuilt from `geometry_encoder_id` on load, and a
  checkpoint saved after the `state_dict` fix has none. Useful for telling a pre-fix checkpoint
  (342 teacher tensors, 13.82 GB) from a clean one (0 tensors, 12.61 GB).
- **Unclassified**, a backstop count. The sections match on fixed name fragments, so before this a
  newly added module was silently invisible while the report still looked complete -- which is
  exactly how the geometry tensors went unnoticed.

Note it reports one shard at a time; the geometry tensors are few and land in a single shard.
