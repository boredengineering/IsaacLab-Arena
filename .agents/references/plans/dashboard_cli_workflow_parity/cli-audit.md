# Read-only dashboard / generation CLI parity audit

Scope: static source inspection in `/workspaces/IsaacLab-Arena`; no package imports, CLI execution, inference, simulator, database access, tests, or source writes. The complete example README, runner, generation agent, version manager, spec_io, GraphRAG retriever and self-healing implementation were read. Supporting entry points and simulator configuration were traced. Existing dirty graph-explorer work was preserved. All statements below are observed source behavior, not live verification. Recommendations are planning only.

## Citation key

References use these exact repository-relative filenames (e.g. `R:744-750` means the runner file below at those lines):

- **D** = `isaaclab_arena_examples/agentic_environment_generation/README.md`
- **R** = `isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py`
- **A** = `isaaclab_arena/agentic_environment_generation/environment_generation_agent.py`
- **C** = `isaaclab_arena/cli/isaaclab_arena_cli.py`
- **L** = `submodules/IsaacLab/source/isaaclab/isaaclab/app/app_launcher.py`
- **V** = `isaaclab_arena/agentic_environment_generation/version_manager.py`
- **I** = `isaaclab_arena/agentic_environment_generation/spec_io.py`
- **G** = `isaaclab_arena/agentic_environment_generation/graph_rag.py`
- **P** = `isaaclab_arena/agentic_environment_generation/lpg_neo4j_sync.py`
- **H** = `isaaclab_arena/agentic_environment_generation/eval_self_healing.py`
- **B** = `isaaclab_arena/agentic_environment_generation/inference_backend.py`
- **W** = `isaaclab_arena_examples/agentic_environment_generation/web_api/generation.py`
- **E** = `isaaclab_arena_examples/agentic_environment_generation/web_api/editor.py`
- **F** = `web/arena-workbench/src/editor.tsx`
- **S** = `isaaclab_arena/environment_spec/arena_env_graph_spec.py`
- **Y** = `isaaclab_arena/environment_spec/arena_env_graph_yaml_loader.py`
- **VC** = `isaaclab_arena/agentic_environment_generation/visual_critic.py`
- **BC** = `isaaclab_arena/environments/arena_env_builder_cfg.py`
- **BUILDER** = `isaaclab_arena/environments/arena_env_builder.py`
- **SC** = `isaaclab_arena/utils/isaaclab_utils/simulation_app.py`
- **VR** = `isaaclab_arena/video/video_recording.py`
- **CR** = `isaaclab_arena/video/camera_observation_video_recorder.py`
- **O** = `docs/pages/example_workflows/agentic_env_gen/index.rst`

## 1. Decision-critical findings

1. **Prompt-first generation is an actual existing CLI workflow, not a template workaround.** README's canonical command is `--mode resolve --prompt "Droid picks up the mustard bottle from the maple table and places it in the grey bin."`, explicitly without `--base_spec` (D:372-391). It retrieves priors, makes model calls, creates version artifacts, and attempts graph publication. It does not run a rollout.
2. **No `--mode generate` exists.** Actual choices are `full`, `resolve`, `build`, `schema`, `catalog`, `auto_heal`, with CLI default **full**, not resolve (R:49-60). A planned UI label such as “Generate from scratch” is not a new existing CLI mode. UI prompt-first default should map to the *resolve workflow without a base*, not accidentally to CLI's simulator-starting default.
3. **Frontend currently forces refinement, but the backend already has a draft from-scratch branch.** F:341-347 always sends `base_yaml: draft` and usually `document_id`; W:90-98 selects refinement when base is not None, generation otherwise. E:190-196 implicitly loads a base when document_id exists, so merely omitting base_yaml while retaining document_id STILL refines. Both base and document reference must be absent (or an explicit future workflow discriminator must prevent implicit loading).
4. **From-scratch selection alone is not full CLI parity.** W:87 uses `max_retries=1`, while CLI agent default is 3 (A:82-90); the repair loop is `min(max_retries, 2)` (A:238,460). W:91 always disables publication; W:110-116 returns a draft only, with no EnvironmentVersionManager call. Current HTTP schema has no workflow/version/publish/heal/build/options fields (E:48-60). The plan must explicitly cover workflows, budgets, artifacts and evidence, not just change one button.
5. **CLI publishes twice on normal successful resolve/full, both generation and refinement.** Agent defaults publish_to_graph=True and publishes before returning (A:143,367-376;386,560-569); runner does not override it (R:267-281), then publishes again after version creation (R:300-331). These are duplicate sync attempts, not necessarily duplicate nodes: P:87 MERGEs by spec.env_name. No runner `--publish` / `--no-publish` / `--rag` switch exists.
6. **`--out_dir` does not redirect successful version snapshots.** R:303 constructs V with default hard-coded lowercase container roots. Output actually goes to `/workspaces/isaaclab_arena/generated_envs/<family>/vN/`; out_dir handles invalid YAML, healing intermediate files and rollout videos (R:289,529,654-658; V:54-68). O:36-37's older successful-output claim is stale.
7. **Version identity is inconsistent across file and graph layers.** `--env_name` changes the manager's family directory, not `spec.env_name` (R:300-305; V:151-153). Graph identity remains `spec.env_name` (P:87-100). `--version` only participates in auto_heal's *implicit base lookup*, not build/full/resolve or matching eval/policy selection (R:432-479). Parent version defaults to latest, not the selected base version (R:546; V:241).

## 2. Actual workflow matrix

| Actual mode / branch | Active work | Required inputs / important exclusions | References |
|---|---|---|---|
| schema | Print Pydantic JSON schema, exit | No agent calls, no SimulationAppContext; parses all flags but ignores workflow payload | R:585-591,736-738 |
| catalog | Print asset/relation/agent-ready task catalogues, exit | No agent instance or simulator; does load catalogue dependencies | R:594-606,740-742; A:809-826,867-883,915-936 |
| resolve, no base | Catalogue -> GraphRAG -> LLM -> prim resolution -> grounding/repair -> agent publish -> versions -> runner publish | Prompt (default available); feedback ignored for synthesis; no simulator rollout | R:239-333,744-746; A:171-376 |
| resolve, base | Load Arena YAML -> feedback or prompt -> refine -> prim/grounding/SHACL/geometry -> publication/versioning | --base_spec; no GraphRAG retrieval in refine | R:261-273; A:403-569 |
| build | Validate explicit YAML path -> warning-only transfer-readiness -> SimulationAppContext -> build -> visual spec check -> zero-action steps -> close | Requires --env_graph_spec_yaml; neither env_name/version nor base_spec substitutes | R:644-728,752-759 |
| full (default) | Starts SimulationAppContext FIRST -> resolve/refine including files/publication -> transfer check -> build -> zero-action steps | Does not consume --env_graph_spec_yaml as a base; requires --base_spec to refine | R:761-766 |
| auto_heal | Resolve input spec/eval/policy -> diagnose -> report policy planner -> apply oracle patches -> intermediates -> new version -> optional diagnostics RDF/DB -> spec DB sync | No new evaluation, no zero-action rollout, no GraphRAG retrieval, no iterative evaluate-until-success controller | R:423-582,748-750 |

“No simulation” for schema/catalog/resolve/auto_heal means no explicit SimulationAppContext launch in dispatch, NOT independence from installed Isaac runtime: R:35-37 imports shared CLI and simulation helpers; C:8 imports AppLauncher; SC:10-15 imports torch/omni. Do not import runner into a general web request process as if it were a pure utility.

README's downstream GR00T/OpenPI evaluations are **separate** workflows, not modes of this runner (D:393-405; O:91-164). If “all documented CLI workflows” includes linked evaluation/variation/experiment guides, track those as a separately scoped coverage matrix; supporting build/full is not GR00T/OpenPI parity. This audit does not claim exhaustive option inventories of those other runners.

## 3. Every runner-specific option

Status: **active** only in listed modes; otherwise **ignored** after argparse validation. `None` is the parser default unless another value is shown. `RF` = resolve/full; `BF` = build/full; `AH` = auto_heal.

| Option | Default / accepted values | Observed semantics and exceptions | Source |
|---|---|---|---|
| --mode | full; full/resolve/build/schema/catalog/auto_heal | Active dispatch; no generate mode | R:49-60,731-767 |
| --eval_dir | None, Path | AH only. Explicit path or latest family eval dir if it exists, else newest mtime among CWD `eval_output/*/*`; not constrained to chosen base/version/family in fallback | R:62-67,451-468 |
| --policy_config | None, Path | AH explicit config or latest version policy then repository DROID default. BF only for resolving checkpoint identity; **does not choose executed policy**, which is always zero_action | R:68-73,180-196,470-493,696-703,756,765 |
| --prompt | `Franka picks up a cube from the maple table and places it into a bowl on the table.` | RF generation text; fallback refinement instructions if no truthy feedback. Not consumed by AH | R:44,74-79,265-281 |
| --model | None | RF forwarded only if truthy; AH forwarded to diagnostic oracle and used only if LLM diagnostic branch runs. Backend resolves provider/env defaults below | R:80-85,252-259,487-492; H:357-393 |
| --base_url | None | Same mode scope as model; OpenAI-compatible endpoint override; CLI permissive, not safe to accept directly from browser | R:86-91,255-256,491 |
| --temperature | 0.2, float | RF and AH LLM branch; no runner range validation | R:92-97,252,492 |
| --num_steps | 20, int | BF zero-action loop budget. AH diagnosis assumes supplied value only if >20; otherwise uses **500**. Does not run those steps in AH. No runner positivity check; <=0 BF resets/closes with empty loop (recorders may have own constraints) | R:98-103,487,703-713 |
| --out_dir | `isaaclab_arena_environments/agent_generated`, Path | RF invalid raw YAML only; success snapshots ignore it. AH intermediate healed YAML/policy. BF `<out_dir>/videos`. Does not change V roots | R:104-109,289,303,529,657; I:17 |
| --api_key | None | RF explicit secret overrides credential discovery; AH only when LLM diagnostic instantiated. Avoid CLI secret argument per README; do not add browser argv secret transport | R:110-118,257-258,489; D:374-378 |
| --env_name | None | RF filesystem family override, not spec/graph rename. AH family and optional implicit base lookup. **Ignored in build**, no load-by-family there | R:119-124,300-305,432-449 |
| --version | None, int | **AH conditional only**: when neither base_spec nor env_graph_spec_yaml supplied and env_name supplied. Uses `args.version or latest`; 0 means latest, negative fails target_v>0. Doesn't bind eval/policy or lineage parent to selected version. **Ignored RF/BF** despite broad help | R:125-130,436-441,453-479,546 |
| --base_spec | None, Path | RF explicitly selects refine; AH first precedence base_spec > env_graph_spec_yaml > family lookup. Ignored build | R:131-136,261-281,433,723-728 |
| --healing_mode | hybrid; hybrid/deterministic/llm | AH only. deterministic rules (may run depth model); llm skips deterministic signatures and calls LLM; hybrid LLM fallback only if **no signatures and success_rate <0.8** | R:137-147,488; H:127,249-274,357-370 |
| --feedback | None, str | RF with base: feedback or prompt. Without base it does **not** affect generation input but STILL overrides lineage prompt and scaffold language instruction: misleading provenance possible | R:148-153,265,275-281,307; V:196,212 |
| --record_viewport_video | False, store_true | BF only; rgb_array + gym RecordVideo; writes to out_dir/videos, no explicit timestamp subdir in this runner | R:154-159,654-662; VR:38-40,84-96 |
| --record_camera_video | False, store_true | BF only; per completed env/camera episode MP4, partial episodes discarded. Does not itself set --enable_cameras | R:160-165,654-662; CR:119-169 |
| --policy_ref | None, str | BF warning-only transfer check; AH report/diagnostics artifact policy identity. Explicit > config checkpoint_uri > config model_path. Unknown/missing identity skips meaningful policy-side diagnosis. Not a policy selector; AH planner does not choose applied patches | R:166-196,199-236,495-508,559-566,756,765 |

Provider resolution is not one universal default: CLI loads absent variables from local `.env` paths (B:25-44,173-174), selects key partly by candidate model name then OPENAI/GEMINI/OPENROUTER/NV fallback (B:175-193), infers provider from base_url/key, and resolves model/endpoint with environment overrides (B:198-254). Built-in defaults are OpenAI `gpt-6-astra`, Gemini `gemini-2.5-flash`, OpenRouter `anthropic/claude-sonnet-4.5`, fallback NVIDIA `azure/anthropic/claude-opus-4-8` / `https://inference-api.nvidia.com` (B:49-53,219-247). These are source defaults, not assertions those models/endpoints are currently available. Dashboard intentionally has fixed provider priority, trusted-server vs temporary-key endpoint controls, load_dotenv=False and bounded transport (W:32-74,87). Preserve the security distinction instead of copying permissive CLI discovery.

## 4. Every inherited parser option

The runner uses the shared parser directly (R:732-734; C:30-38). Static AST enumeration found **18 runner declarations + 13 shared Arena declarations + 17 AppLauncher declarations**. The declaration spelling set contains 49 explicit option strings; add argparse's `-h`, `--help` and BooleanOptionalAction-generated `--no-resolve_on_reset`. `--visualizer` / `--viz` are aliases of one action. This inventory covers the inherited surface as well as runner-specific flags, without importing/executing a parser.

### Shared Arena options

All active simulation settings below are **BF only**, ignored in schema/catalog/resolve/AH. Exceptions and global no-ops are explicit.

| Option | Default | Actual effect / limitation | Source |
|---|---|---|---|
| --disable_fabric | False | Builder use_fabric = not flag | C:49-51; BUILDER:463-465 |
| --seed | 42 | Builder env seed; not LLM determinism | C:52; BUILDER:397 |
| --num_envs | 1 | Builder environment count; positive assertion in typed config | C:53; BC:18,30-31 |
| --env_spacing | 30.0 | Scene separation | C:54; BUILDER:66 |
| --mimic | False | Mimic-specific config/recorders; may require task mimic support | C:55; BUILDER:338-382,417 |
| --distributed | False | AppLauncher rank/device/thread setup; does not spawn torchrun/processes or add runner rank-zero generation guards. Multiple independently launched full processes could each infer/write/publish | C:59-64; L:1023-1053; R:761-766 |
| --no_solve_relations | False flag; solve_relations=True | Turns off builder placement solving; not generation agent grounding/relaxation | C:76-82; BUILDER:215; A:232-234,625-675 |
| --placement_seed | None | Placement solver seed override when solving | C:83-88; BUILDER:102-103 |
| --presets | None | Physics config attribute e.g. physx/newton; no argparse choices; bad attribute can fail; newton adjusts replication | C:89-98; BUILDER:400-410 |
| --resolve_on_reset / --no-resolve_on_reset | None | Tri-state override: omitted preserves placer configuration; explicit true/false overrides it when solving | C:99-107; BUILDER:97-105 |
| --list_variations | False | **No-op in this runner**: parsed but no list/exit caller; not in BC fields. Build/full continue | C:108-113; R:731-767; BC:18-28 |
| --env_graph_spec_yaml | None, str | Active build required path; AH secondary explicit base; ignored RF. Help claims dynamic YAML override flags, but this runner never installs/applies them | C:121-129; R:433,650-659,723-728,731-766; S:204-210 |
| --external_environment_class_path | None | **No-op in this runner**: graph spec always used, no external-class loader and no BC field | C:138-143; R:650-660; BC:18-28 |
| -h / --help | argparse help action | Prints help/exits; standard parser-only action, no workflow | C:32; L:610-614 |

There are no environment subcommands, Hydra trailing overrides, policy_type, policy_device, remote_host/port, num_episodes, max_retries, max_tokens, retrieve-refinement-history, or publish switches in this runner. These belong to other interfaces or are not implemented here. A document's cli_override_specs are validated as part of the model but their flag application isn't wired into this parser/build path (C:121-129; R:650-659,731-734; S:154-168,204-210).

### AppLauncher options

These are **BF only**; accepted but not consumed by no-SimulationApp modes (aside from ordinary parser validation). They are advanced simulator/runtime controls, not all appropriate for unrestricted browser input.

| Option | Parser default | Semantics / caveat | Source |
|---|---|---|---|
| --headless | False | Deprecated flag force-disables visualization; absence of --viz is default headless intent, false is not promise of GUI | L:388-390,488-496,620-625 |
| --livestream | -1 | Explicit 0/1/2; default inherits LIVESTREAM; 1 public / 2 private WebRTC, affects headless | L:391-398,497-503,622 |
| --enable_cameras | False | Enables camera/render dependencies; environment variable fallback. Needed separately for camera observations | L:400-403,504-509,623 |
| --xr | False | XR/VR/AR; may make default device CPU if not explicit | L:510-515,624,1002-1008 |
| --device | cuda:0 | cpu/cuda/cuda:N; builder and AppLauncher; distributed may resolve device | L:516-522,625,997-1058; BC:27 |
| --visualizer / --viz | None | CSV backend selection: kit/newton/rerun/viser or none; global visualization | L:432-441,523-530 |
| --cpu | False | Hidden deprecated switch; **raises on simulator startup**, not alias for --device cpu | L:532,1020-1021 |
| --verbose | False | Debug/verbose logging, takes precedence over info | L:192-198,533-537 |
| --info | False | Info logging | L:192-198,538-542 |
| --experience | empty string | Kit experience auto-selection, or relative path in Isaac Sim/Lab apps, or explicit path | L:411-423,543-552 |
| --deterministic | False | Rendering settings reproducibility, not all simulation/LLM determinism | L:425-426,553-558,627 |
| --rendering_mode | None | performance/balanced/quality; parser has no default despite CFG_INFO saying balanced. None preserves Kit settings with cameras disabled; sets empty rendering selection when cameras enabled | L:559-569,628,1299-1309 |
| --kit_args | empty string | Arbitrary whitespace-split Kit args added to sys.argv; never expose unrestricted browser shell/extension settings | L:570-578,1166-1172 |
| --anim_recording_enabled | False | Enables USD animation recording, separate from MP4 flags | L:579-583,1311-1330 |
| --anim_recording_start_time | 0 | Used only when enabled; must be <stop | L:584-592,1317-1329 |
| --anim_recording_stop_time | 10 | Used only when enabled; early process shutdown can prevent recording | L:593-601,1317-1330 |
| --max_visible_envs | suppressed / absent | Optional visualizer env-count cap | L:602-607,1332-1334 |

## 5. Retrieval, validation and publication are separate contracts

### Actual generation retrieval

- A:185-197 creates GraphRAGRetriever, calls retrieve_prior_subgraphs(prompt, limit=2), formats and appends context. Refinement has no corresponding call (A:403-428). `publish_to_graph=False` disables writes, **not reads**. No CLI RAG disable/limit/filter option exists.
- G:99-120 uses simple ordered keyword substring filters: embodiment g1 > droid > franka; fixture shelving/rack > kitchen/counter > table/desk. Not vector search, not target-object matching, not policy-specific history retrieval.
- Measured priors require success_rate **>0.0**, num_episodes **>=1**, with rate and count from the same best evaluation row, ordered rate then episodes (G:29-63,151-192). If any measured rows exist, it does not fill remaining slots with structural ones. Structural fallback only when none qualify, requires `e.converged=true`, newest first (G:68-96,185-192).
- G:193-197 logs database errors and returns []; thus empty results and DB failure collapse at the agent result boundary. A:195's “verified” trace can describe structural fallback too. Context formatter correctly distinguishes measured and unevaluated (G:199-238), but no immutable deciding evaluation ID, policy ID or exact prior snapshot is returned by `_row_to_prior` (G:123-137). The plan needs structured provenance, not a green “GraphRAG used” inferred from a connected DB.
- `retrieve_refinement_history` and `retrieve_controller_trials` exist (G:240-405), but are not called by this runner's generation/refinement. Do not advertise DCRG-history use just because the class exposes it. Retriever-owned driver is cached (G:143-149); this generation caller does not close it. Shared service design must own connection lifecycle.

### Validation / generation evidence limitations

- From-scratch does spec inference, prim resolution (failure can return None), spatial grounding, bounded SHACL + geometric + visual-spec + PhysX-named checks, repairs and deterministic fallback (A:199-348). Refinement tolerates failed prim inference by retaining spec, and its loop checks only SHACL + geometry, not those visual/physical critics (A:448-541).
- Neither generate nor build supplies rendered_images to VisualSceneCritic (A:268-269; R:672-673). Cloud/local VLM tiers require images and are therefore not reached; geometric/advisory fallback applies (VC:82-125). PhysXPreflightCritic is a heuristic initial-height check, not a simulator rollout (VC:325-354). Tier-4 advisory reports conforms=True / score 8, so cannot become verified visual success (VC:302-318).
- A non-None fallback spec may be returned/published with converged=False; final fallback is not re-run through the full repair validation loop (A:342-376,536-569). Telemetry traces are copied before agent publication, so later publication failures appended to agent.traces are absent from telemetry.traces (A:364,374;557,567). Runner only prints traces for invalid spec, not all successful warnings (R:285-298).
- W:106-115 gives nonconvergence warning but exposes stage strings rather than raw traces for secret safety. Extend with sanitized structured evidence/status, not raw model/DB error dumps.

### Publication hazards

- Agent publication happens before version YAML/lineage is durably created, then runner re-publishes. A local version failure can leave an already published graph; a DB failure may be suppressed after local success (R:300-331; A:367-376). No cross-store transaction.
- P:75-111 updates a mutable EnvironmentGraph keyed only by name, with telemetry and updated_at; regular nodes/relations use MERGE, with no replacement cleanup of removed nodes/edges in sync_spec_to_neo4j (P:129-343). Old structure can persist when reusing the same name. Re-publication isn't a version-aware immutable snapshot.
- Graph derivation only if parent name differs (P:113-127). Same-name refinement/healing has no WAS_DERIVED_FROM edge even though filesystem versions exist. Agent's first refinement sync passes no parent, runner's second attempts parent feedback (R:317-324).
- AH sync supplies no telemetry (R:573-577), so P:76-83 writes zero counters and converged=True by default, possibly overwriting prior generation telemetry. Do not equate this structural flag with a validated/evaluated healed result.
- sync uses sequential session.run calls, not one managed atomic transaction (P:73-354); partial graph state is possible. Final counts are limited topology counts, not an exact content/hash verification (P:345-359). Runner swallows second publication errors entirely (R:330-331,579-580).
- Planned safe common publisher: exactly one explicit publication boundary, owner-scoped credentials, idempotency identity and input hash, immutable/provenance identity rules, transaction or partial-failure manifest, exact read-back. Decide handling of existing mutable names before claiming historical traceability.

## 6. Artifact and auto-heal inventory

### Resolve/full success

- Root **literal from source** `/workspaces/isaaclab_arena/generated_envs` (not audit checkout capitalization, not --out_dir), eval lookup root `/workspaces/isaaclab_arena/eval_output` (V:54-68).
- `<family>/vN/<family>.yaml`, `<family>/vN/policy_config.yaml`, `<family>/latest -> vN`, `<family>/lineage.json`, `<family>/lineage.ttl`, `<family>/README.md` (V:147-250,285-330,368-371,563-565). The documented layout's metadata.json is **not actually written** by create_version. create_version does not create an eval directory or evaluation result.
- Without explicit policy source, scaffold is G1 config if embodiment name contains g1; all others get DROID scaffold, including the default Franka prompt (V:184-222). Runner resolve never passes policy_config_source, so --policy_config does not alter this scaffold (R:304-308). Not a verified compatible checkpoint/config.
- V merely strips env_name; it does not use safe_filename_stem or enforce path containment (V:60-65,149-153). Names with separators/absolute paths, symlinks, concurrent same-family jobs, corrupt lineage and root writability need gates. New-version allocation is read-latest + mkdir(exist_ok=True), non-atomic/unlocked; corrupt ledger returns 0 and may reuse v1 (V:70-86,147-150). Updating latest can delete a real directory if not a symlink (V:224-234). Do not reuse unguarded in concurrent dashboard jobs.
- Lineage prompt/remediations/diagnostics stored in JSON/RDF/README, potentially sensitive; README embeds prompts into shell examples (V:310-330,395-404,545-552). Generated cheatsheets also hard-code container/path assumptions (V:467-553; I:31-278); treat as historical convenience, not safe commands to execute.

### Invalid resolve/full output

R:285-291 writes raw data through I:296-304, at `<out_dir>/<safe_filename_stem(data.env_name or fallback)>.yaml`, then asserts. I:20-23 sanitizes this path, unlike V. It can overwrite an existing same-name invalid dump. If agent returns `(None, None)`, writer calls data.get and raises before the intended artifact/assert (A:145,167-168,207-224; I:298). Preserve invalid result/error distinction in API.

I:282-293's standalone successful writer also overwrites `<out_dir>/README.md`, but **runner success does not call it**. Do not conflate its legacy layout with V artifacts.

### Build/full

- Optional MP4s in `<out_dir>/videos/` directly, not per-version or timestamped subdirectory; timestamped_run_dir exists but isn't invoked here (R:654-662; VR:43-50,84-106). Default camera filenames `robot-cam-env<N>-<camera>-episode-<E>.mp4`; incomplete episodes are discarded and short default 20-step run may yield no camera video (CR:57-59,119-169). Recording flags don't guarantee files or camera enabling.
- AppLauncher/Kit can produce runtime logs and requested USD animation recordings; those are not routed through this runner's --out_dir artifact manifest. Mimic/task recorder configuration may add task-dependent outputs (BUILDER:171-177,338-382). No policy evaluation summary/telemetry emission or EnvironmentVersionManager.record_evaluation_metrics call occurs in R:696-720.
- Lifecycle is process-oriented: SC:145-177 can os._exit on errors/forced completion and owns child cleanup. Shared long-lived API must not execute full/build in its own process. Use established supervised simulation ownership and task/result boundary.

### Auto-heal input selection and side effects

1. Base precedence explicit base_spec > explicit env_graph_spec_yaml > env_name + version/latest. Base file may be older/different family while later lookups silently use latest (R:432-479). Eval fallback can select an unrelated newest run. No exact evaluated-spec hash/policy/version validation occurs at this orchestration boundary.
2. Oracle recursively selects first summary/telemetry, reads episode JSONL; missing/malformed metrics often become zeros, not unknown (H:74-124). Missing eval_dir can thus yield recommendations instead of a decisive missing-evidence failure. No automatic re-evaluation occurs.
3. Deterministic/hybrid can extract `<eval_dir>/extracted_eval_frame_0.png`, search reference datasets, run Depth Anything V2 and save `<frame_stem>_depth_audit.png` beside input frame (H:249-274,472-560). “Deterministic” does not mean no ML/GPU/extra files. It means no generative LLM branch. These writes can occur outside --out_dir.
4. Oracle diagnostic signatures select patches; policy capability planner is **report-only**, no executed next-diagnostic or chosen planner remediation (R:495-530). LLM backend construction is outside `_diagnose_with_llm`'s try, so missing-key constructor error can propagate rather than graceful skip (H:388-393,452-469).
5. Engine creates out_dir and writes policy using original policy basename and healed spec `<spec.env_name>.yaml`, then V copies/snapshots them (H:670-695,747-749; R:525-552). Path(None) fails if no policy config found (H:673); out_dir matching input parent can overwrite original policy/spec. Policy num_steps patches only become recommended_steps metadata; other policy keys written. Spatial engine only applies supported background/robot position_xyz and relation surface_sector; it doesn't apply every recommended field such as sector_bounds (H:683-745).
6. Empty signatures still write intermediates/create a new version, with generic remediation text; not proof a defect was fixed (R:539-549). Parent is latest manager version, not necessarily diagnosed base (R:546).
7. For known policy profile, `<new_v_dir>/policy_diagnostics.ttl` attempted independently of DB, followed by optional diagnostic graph sync; evaluation ID is synthesized `<spec.env_name>_v<new_version>`, not the consumed original evaluation run ID (R:367-420,559-566). Then healed spec sync attempted, without generation telemetry (R:568-580). Recommended next rollout steps are printed, not executed (R:556).

### YAML/includes

CLI loads through ArenaEnvGraphSpec.from_yaml (S:180-191) -> relative top-level external_yaml include, no nested include, duplicate top-level keys rejected (Y:16-61). Version writes serialize flattened parsed model (S:193-201). Dashboard already freezes validated parsed bases before queueing (E:165-169,199-208). Preserve source/include provenance separately from canonical flattened content; do not turn a revision into source overwrite.

## 7. Proposed shared boundaries (NOT implemented)

1. **Typed workflow request/result, not HTTP wrapper around main or raw argv.** Enumerate schema/catalog, prompt-first resolve, explicit refinement, build zero-action, full resolve+build and auto-heal. Keep CLI mode names separate from UI labels. UI defaults prompt-first resolve; loaded draft remains available but does not silently become base. Put refinement in an explicit action.
2. **Share actual agent and catalogue/model loading code.** Existing reusable hooks: A:136-145 / 378-388 (`publish_to_graph`, `progress`); R:585-606 schema/catalog logic; S:180-201 serialization. Extract orchestration around them only after approval. Keep W:61-116 transport budgets, fresh per-job agent, sanitized allowlisted stages and credential lifecycle rather than importing the simulator-heavy runner.
3. **Budget decisions explicit.** UI draft currently permits fewer retries than CLI. Define frozen limits/timeouts/max calls, show intended cost, and test equivalent core behavior under matching budgets. Do not quietly claim exact parity while max_retries=1 vs3 changes validation loops. Provider key reference is frozen; expiry/replacement must not switch queued jobs to another provider.
4. **Retrieve vs publish separately.** Default from-scratch invokes existing GraphRAG retrieval even for draft-only; surface not-attempted / measured / structural / empty / failed and exact immutable provenance. Expose versioned/published completion as an explicit disclosed CLI-equivalent operation; retain draft-only as a clearly different operation. To match README semantics, the plan must include actual version/publish support, not stop at an unpublished scratch branch.
5. **Single side-effect coordinator.** Invoke agent with publish_to_graph=False, then one idempotent authorized persistence/publication phase with version manifest and exact read-back. This deliberately fixes duplicate CLI publication rather than cloning it. Make local-success/DB-failed visible and retry publication without re-running LLM. Share it with CLI to prevent new divergence.
6. **Guard V and paths before reuse.** Configurable allowlisted storage roots (/eval persistent workbench storage as appropriate), safe family identifiers, exact selected parent/eval/policy identities, atomic/locked version allocation, no destructive latest-directory deletion, immutable artifacts and hashes. Export paths differ from input document IDs. Do not permit arbitrary browser read/write paths or raw kit_args/custom credential destinations.
7. **Build/full separate owned simulator jobs.** Reuse core build + typed builder config and existing worker lifecycle, not SC in API process. Preserve num_steps/envs, physics, placement and camera/video controls as supported advanced options with resource bounds. Present zero-action stability/preview distinctly from measured policy evaluation. Explicit invocation only; never automatic upon applying YAML or polling.
8. **Auto-heal separate diagnose/review/apply contract.** Freeze the exact evaluated spec, policy identity/config, telemetry artifacts and version. Show oracle signatures vs advisory planner recommendations; require acknowledgement of scene/policy changes and extra ML/artifact side effects. Reuse H oracle/remediation logic only with trusted bounded inputs; remove unsafe newest-run guessing from web behavior or require explicit user selection. Creating a healed version doesn't mean successful re-evaluation.
9. **Coverage ledger, not an unbounded option form.** Every item in sections 2-4 gets one state: UI supported, advanced operator-only, intentionally unsupported/no-op/deprecated, or separately scoped workflow. No-op flags are not features to reimplement. Document rejected browser features explicitly. Linked GR00T/OpenPI/evaluation/variation flows need their own plan if full README-linked replacement is required.

## 8. Suggested acceptance cases for the implementation plan

These are proposed cases, **not tests executed during this audit**. Use hermetic fakes/static tests first; live inference, Neo4j and GPU acceptance only under separately approved budgets.

- **Mode/schema coverage:** assert exact six CLI modes and default full; reject generate; UI default binds to scratch resolve. Snapshot all parser actions/defaults, including hidden cpu, aliases and no-resolve_on_reset. Label no-op/ignored options rather than imply behavior.
- **README scenario:** enter the exact mustard/table/DROID prompt in an editor with a loaded document; scratch request has neither base_yaml nor implicit document fallback; agent.generate_spec called, refine_spec not called. Repeat with no loaded document and no valid draft. Explicit refine freezes authored YAML/includes and calls refine_spec using feedback, with no GraphRAG retrieval unless a separately approved extension adds it.
- **GraphRAG:** measured >0 and >=1 episode, highest rate/count from same run; no qualifying measured -> converged structural; some measured -> no structural fill; empty DB; DB unavailable; filters for DROID/table; no object/policy match claim. Persist exact priors/context and deciding evidence IDs. Failure vs empty stays distinguishable; no “verified” badge for structural fallback.
- **Security and budget:** all providers' explicit model/endpoint defaults; CLI dotenv vs server prohibition; temporary reference expiry/replacement/replay; no secrets in input/result/artifact/log/cache; rejected untrusted endpoint/kit args; frozen call/retry/time limits; no outbound network in mock tests.
- **Persistence:** one version + one publisher call for success, including refinement; no publish in draft-only; exact graph read-back; database failure after local version; local failure before publish; retry doesn't repeat LLM or allocate duplicate version. Same-name refinements, changed family vs spec name, graph stale nodes and missing parent edges have defined behavior.
- **Paths/versions:** out_dir legacy semantics documented; configurable roots respected; traversal/absolute/symlink family rejected; concurrent same-family runs cannot overwrite; corrupt lineage cannot reuse v1; selected version binds parent/eval/policy; preserve original input YAML/includes. Check real artifact manifest rather than expected directory names or mutable latest.
- **Failure results:** invalid raw dict stored safely if requested; None raw payload handled; prim resolution failures distinguished; nonconverged fallback stays warning; advisory visual tier never verified physical success; caller gets sanitized publication/retrieval status even after telemetry snapshot.
- **Build/full:** explicit build requires env_graph_spec_yaml; no env_name/version implicit build; zero-action exactly requested steps; full simulator/generation ordering consciously retained or documented change; transfer warning never claims applied remediation. Failed startup/cancel/reconnect cannot kill unrelated work or retry inference. Test positive resources and no automatic GPU launch from schema/edit/save/apply.
- **Recording:** each enabled combination, cameras disabled/missing, completed vs partial episodes, default short rollout, both recorders, empty result, name collisions; verify actual new-job MP4 decode. Animation recording bounded start<stop and early-stop absence distinguished. Logs/animation/mimic artifacts not falsely routed under out_dir.
- **Auto-heal selection:** explicit base priority; version/latest/0/negative semantics characterized; explicit eval/policy vs unsafe fallback; reject mismatched run hashes/policy/family; missing metrics are unknown not failure metrics. Default num_steps20 -> diagnosis500; supplied21 retained. Test deterministic/hybrid/llm branch predicates and missing-key constructor failure.
- **Auto-heal patches/artifacts:** no signatures doesn't imply improvement; supported versus ignored spatial fields reported; recommended_steps not executed; original policy/spec not overwritten; distinct oracle applied fixes vs planner advice; optional depth frame/audit artifacts declared; RDF success with DB failure retained; diagnostics refer to real consumed evaluation identity; no automatic re-evaluation.
- **Complete documented workflow gate:** schema/catalog, scratch resolve, refinement, version browsing/lineage/artifacts/publication, build/full zero-action, recording, auto-heal and policy diagnostics each have traceable UI/advanced disposition. Separate snapshots, GR00T/OpenPI policy evaluation, variations/experiments and DCRG controller history from this runner's features; no template-refinement substitution as scratch acceptance.

## Completion / limitations

Only `/tmp/dashboard-cli-audit.md` was created. Existing repository edits were not modified. Static option enumeration and full requested file reads back the inventory; no runtime behavior, model availability, database state, container startup, physical validity or policy success was tested. No inference/DB/CLI execution is needed or authorized to use this report for planning.
