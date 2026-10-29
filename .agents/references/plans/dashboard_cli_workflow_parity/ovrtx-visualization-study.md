# ovrtx for the Cybernetic-Physics workbench

Research date: 2026-09-15. Scope: documentation/source review and offline v6 design, **not a runtime benchmark, installation, deployment or GPU test**.

## Recommendation

**Evaluate ovstage + ovrtx + ovstream as an isolated live-visualization backend. Keep the existing snapshot path as a fallback and Isaac Sim/Arena authoritative for physics and policy execution.** For v6, restore saved Assets/Scene viewing first and make the proposed live-view permissions explicit without connecting a service.

This is a concrete candidate rather than a speculative video bridge: NVIDIA's official `ovrtx_stream` example renders USD with ovrtx, passes CUDA frames to ovstream, and handles browser drag/zoom camera input without a Kit/Carbonite application.[12] It does not establish compatibility, performance or production readiness in this Arena checkout.

## What NVIDIA actually provides

| Layer | Documented role | Consequence for this dashboard |
| --- | --- | --- |
| ovstage | Runtime scene ownership, hierarchy/attributes and ordinal-keyed updates.[8] | Load a protected USD snapshot and keep transient camera/edit state outside source assets. |
| ovrtx | Native C/Python RTX rendering and sensor outputs.[1][2] | Runs on an RTX-equipped server/worker, not as a React/WebGL library. |
| ovstream | Frames, messages and browser input through WebRTC; other native/local transports are available.[14] | The missing browser delivery layer is documented, but needs integration with our session/permission model. |
| Browser client | NVIDIA's bundled streaming JavaScript speaks StreamSDK-specific signaling.[13] | Do not substitute an unadapted `RTCPeerConnection` or assume generic WebRTC tooling interoperates. |
| Physics | NVIDIA distinguishes rendering/streaming from ovphysx rigid-body/contact/gravity simulation.[15] | Camera movement or rendered-object edits do not prove physical validity. Retain Isaac Sim for the existing Arena workflows. |

The tagged and inspected main version files confirm ovrtx **0.5.0**, while the documentation still labels the product prerelease.[16][6][1]

Introductions discussing migration beginning in 0.4 are not evidence that 0.4 is latest. The 0.5 changelog includes breaking API changes, including tensor/mapping interfaces, full-path render-var identity and Vulkan-only public Windows packages; pin compatible library versions and use matching examples rather than old snippets.[7]

The examples index includes native viewport/material tools as well as sensor demonstrations.[3]

The Vulkan interop example is a native GLFW viewer, while the planet example's streaming refers to Rerun—not a browser WebRTC transport.[11][10]

Renderer configuration documentation warns that the first run compiles and caches shaders; this study does not turn that warning into a measured startup estimate.[9]

## Interaction possibilities

- **Camera navigation:** the official ovrtx/ovstream demo maps browser drag and wheel input back to the camera; any key resumes its example auto-orbit.[12]
- **Object selection:** ovrtx supports click/marquee picking, prim-path lookup and selection outlines. UI coordinates must become normalized RenderProduct coordinates; picking currently requires the selected RenderProduct on CUDA-visible GPU 0.[5]
- **Transform/property editing:** the ovstage/renderer division supports application-driven scene updates. The application must own validation, stage mutation and update ordering; a stream alone does not supply an editor or persistence workflow.[8][12]
- **Inspection and telemetry:** native camera/sensor outputs can support views beyond RGB, but those would be additional workbench features, not automatically restored by displaying video.[1]

Proposed permission levels are: view frames; control camera; select/inspect a prim; propose an edit; explicitly apply an approved edit. They should not collapse into a single “interactive” permission. Pointer input must never automatically start simulation, generation, publication or physical-robot actions.

For future edits, return a proposed scene change to the existing draft/review flow rather than saving source USD or silently modifying a research version. Keep camera-only session changes distinct from environment changes.

## Architecture to investigate

    Approved, dependency-pinned USD snapshot
        -> isolated visualization worker
             ovstage scene state
             ovrtx RenderProducts
             ovstream WebRTC delivery
        -> authenticated dashboard viewport

    Browser camera/pick intent
        -> validated, bounded command queue
        -> renderer-owning execution thread
        -> frame/selection/property response

This is a proposed architecture, not implemented code. Prefer a separate worker over inserting another native renderer into the existing Isaac process until ABI and plugin compatibility have been tested. Reuse existing ownership, budgets, artifact identity and GPU-lease conventions instead of adding a parallel ungoverned job system.

Bind a viewport to an explicit scene revision, camera, renderer configuration and session. Tag input/selection replies with viewport generation/frame identity and reject stale replies after source changes. ovstage ordinals are publication gates: rendering may observe that publication or a later one, so an ordinal is not by itself an immutable historical scene snapshot.[8]

## Deployment and compatibility gates

1. **GPU and driver:** ovrtx requires an RTX-capable NVIDIA GPU and a supported driver. Use the OS/GPU-specific validated matrix, not a generic “CUDA installed” check. CPU output mapping does not establish CPU-only rendering.[4]
2. **Encoder context:** the official ovstream composition example pins both encoder GPU and the producer CUDA context; choosing a GPU alone can yield an encoding failure.[12]
3. **Streaming limits:** the bundled client currently cannot request resolution changes. RTSP has no input channel. WebRTC STUN/TURN is available, but that does not solve authentication, TLS, endpoint exposure or controller ownership.[13][12][14]
4. **Scene fidelity:** test our USD references, textures/materials, scales, up-axis, transforms, robot pose and camera framing against the current Kit captures. No Arena/Isaac Sim 6 material, schema or ABI compatibility has been established here.
5. **Lifecycle:** impose startup/shader-warmup deadlines, maximum resolution/FPS/session duration, queue bounds and cleanup checks. Measure cold/warm startup, VRAM and latency; no performance improvement is claimed from the word “lightweight”.
6. **Input trust:** allow known asset roots and controlled USD dependencies; do not accept arbitrary filesystem paths, Python, shader code or unrestricted mutation commands from browser messages. Keep one explicit controller lease and read-only observers as a possible later extension.
7. **Licensing:** both libraries are prerelease and governed by NVIDIA terms plus bundled third-party terms. ovrtx links the AI product terms, while ovstream links Omniverse-specific terms. Public GitHub availability is not a blanket redistribution/hosted-service license; review the actual combination before customer-facing deployment.[1][14]

## Staged path

- **V6 now:** offline historical asset/scene images, camera availability, zoom, provenance and frozen render/live-view planning. No stream, renderer startup or GPU work.
- **Authorized spike:** pin compatible packages; use a disposable, owned worker and approved GPU lease; render one protected local USD frame. Compare output and cleanup with the existing snapshot renderer. Prefetch dependencies only within an explicitly approved network scope.
- **Local live viewer:** reproduce the official ovrtx + ovstream composition on a loopback/private endpoint, then embed its compatible client in the dashboard. Add bounded camera/picking commands before scene-edit proposals.
- **Broader deployment:** only after measured reliability, session/authorization review, licensing review and concurrency/resource acceptance. No new deployment infrastructure is justified merely by this study.

## V6 historical-image evidence

The offline gallery uses selected original PNGs from `/eval/arena-preview-renderer-verification/run2/isometric.json`, checked against its current SHA-256 `94139b0c124bf923a57b7394492def8127f5b34c6f49757744b5f3bbce31321c`. A curated metadata projection and individual PNG checksums live in `web/arena-workbench/src/preview/render-samples/provenance.json`; the raw cache/journal is not exposed.

The set contains the maple-table scene, isolated table reference and Rubik's cube, all recorded isometric 512×512 captures. The scene visibly contains a suspended mug; this defect is preserved and labelled. The sideways standalone robot capture was deliberately excluded. These are historical Isaac/Kit captures, **not ovrtx output, not the currently selected draft, and not settled-physics or task-success evidence**.

The original probe (`isaaclab_arena_examples/tests/preview_renderer_probe.py:28–53`) associates this format with the maple-table fixture and requests zero policy steps. The saved response does not retain immutable input YAML bytes/hash, source commit or durable job ID. Existing asset metadata declares unverifiable dependencies/no cache reuse. Consequently the gallery must never display a fresh-current-draft badge for these images.

## What remains unknown

Actual host GPU/NVENC suitability; compatible ovstage/ovrtx/ovstream version tuple; Arena USD/material fidelity; cold/warm timing and VRAM; simultaneous viewer capacity; browser/security integration; production licensing. No runtime experiment was performed to fill those gaps.

## Sources

[1] https://nvidia-omniverse.github.io/ovrtx
[2] https://github.com/NVIDIA-Omniverse/ovrtx
[3] https://github.com/NVIDIA-Omniverse/ovrtx/blob/main/examples/README.md
[4] https://nvidia-omniverse.github.io/ovrtx/driver_requirements.html
[5] https://nvidia-omniverse.github.io/ovrtx/scene/picking.html
[6] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/main/VERSION.md
[7] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/main/CHANGELOG.md
[8] https://nvidia-omniverse.github.io/ovrtx/core/ovstage_integration.html
[9] https://nvidia-omniverse.github.io/ovrtx/core/renderer_configuration.html
[10] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/main/examples/python/planet-system/README.md
[11] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/main/examples/c/vulkan-interop/README.md
[12] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovstream/main/examples/python/ovrtx_stream/README.md
[13] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovstream/main/examples/webrtc_client/README.md
[14] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovstream/main/README.md
[15] https://docs.nvidia.com/learning/physical-ai/physical-ai-agent-bootcamp/latest/meet-omniverse-libraries.html
[16] https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/v0.5.0/VERSION.md
