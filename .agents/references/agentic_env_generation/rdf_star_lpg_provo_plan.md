# Master Plan: RDF-star, Labeled Property Graphs (LPG), and PROV-O Architecture for IsaacLab-Arena

> [!IMPORTANT]
> **STATUS: PENDING REVIEW / RFC (Request For Comments)**
> This architectural plan is staged for design review. Core Phases 1–3 (Ontology, SHACL Validation, Lowering, Bidirectional Lifting, PROV-O Serialization, and Video Recording) have been implemented and verified with live LLM generation (`gemini-3.6-flash`). Please review the proposed **MCP Servers**, **Agent Skills**, and **Architectural Options & Trade-offs** in Sections 8–10, and provide feedback or click **Proceed** to authorize further scaling.

Implementation blueprint, codebase gap analysis, scaffolded **RDF-star / JSON-LD 1.1 / W3C PROV-O** ontology architecture, and comprehensive **MCP Server & Skill Integration Roadmap** for elevating **IsaacLab-Arena**'s agentic environment generation into an enterprise-grade **Semantic Web & Property Graph Pipeline**.

---

## 1. Executive Summary & Dual-Plane Vision

The current environment generation pipeline in `isaaclab_arena/agentic_environment_generation/` compiles unstructured natural-language prompts into declarative environment specifications (`ArenaEnvGraphSpec`). 

This architecture addresses three foundational requirements:
1. **Reified Spatial Relations**: Topological relations (`on`, `inside`, `nav_corridor`) natively carry continuous metric constraints (bounding intervals, contact normals, surface anchors, locomotion clearance radii) via RDF-star and LPG properties.
2. **End-to-End Provenance & Auditability**: A formal W3C PROV-O causal graph links every evaluation outcome (e.g. GR00T VLA scoring $0\%$ vs. $100\%$) back to the prompt, LLM model version, temperature, asset hash, or curriculum mutation that spawned the scene.
3. **Declarative Invariant Validation**: Schema and task invariants are checked via formal declarative semantic constraint languages (W3C SHACL) with automated diagnostic self-healing loops.

```mermaid
flowchart TD
    subgraph KNOWLEDGE_PLANE ["1. Semantic & Provenance Plane (RDF-star / LPG / PROV-O)"]
        PROV["W3C PROV-O Lineage:<br/>• Agent (Gemini-3.6, Claude-3.7)<br/>• Activity (PromptSynthesis, CurriculumMutation)<br/>• Entity (TaskSpec, SceneGraph)"]
        JSON_LD["JSON-LD 1.1 / JSON-star Schema<br/>(Strict Structured Output Contract)"]
        LPG_STORE["Native Property Graph (Neo4j / Cypher):<br/>(:RigidObject)-[:PLACED_ON {height: 0.75}]->(:Fixture)"]
        RDF_STAR["RDF-star Knowledge Graph:<br/>&lt;&lt; :box :placedOn :shelf &gt;&gt;<br/>  :contactAnchor :middle_tier ;<br/>  :metricBounds [x, y, z] ;<br/>  :clearance 0.08 ."]
        SHACL["SHACL-star Validation Engine:<br/>• Mandatory Ground Plane Invariant<br/>• Kinematic Workspace Manifold Gate<br/>• Pink WBC Single-Thread Invariant<br/>• Locomotion Corridor Clearance Gate"]
        
        PROV --> JSON_LD
        JSON_LD --> LPG_STORE
        LPG_STORE <-->|"Isomorphic Mapping"| RDF_STAR
        RDF_STAR --> SHACL
    end

    subgraph COMPILER_PLANE ["2. Lowering & Compilation Plane"]
        LOWER["Lowering Compiler (rdf_lowering.py):<br/>SPARQL-star / Cypher Query &lt;== Bidirectional Lifting ==&gt; ArenaEnvGraphSpec"]
        SHACL --> LOWER
    end

    subgraph SIMULATION_PLANE ["3. Physical Simulation Plane (Isaac Sim / PhysX / GR00T)"]
        DOCKER_SIM["IsaacLab-Arena Docker Runtime:<br/>• Continuous Dynamics (50-1000 Hz)<br/>• Whole-Body Control (Pink / Joint WBC)<br/>• Multi-Camera Sensors (RGB-D)"]
        GR00T_SRV["Isaac-GR00T Foundation Model Server:<br/>• Host / ZeroMQ (Port 5556 / 5558)"]
        LOWER --> DOCKER_SIM
        DOCKER_SIM <-->|"ZeroMQ IPC (50 Hz)"| GR00T_SRV
    end

    subgraph TELEMETRY_PLANE ["4. Telemetry Backpropagation Loop"]
        FEEDBACK["telemetry_to_prov.py:<br/>• Tier 3 Physics Settle Metrics<br/>• Tier 4 Task Success Phi(S_T)<br/>• Mean Step Latency & Trajectory MSE"]
        DOCKER_SIM --> FEEDBACK
        FEEDBACK --> PROV
    end
```

---

### 1.1 The Complete Mental Model: Semantic-Physical Life of an Environment

```mermaid
flowchart TD
    subgraph STAGE_1 ["1. Intent Synthesis & Reification"]
        NL_PROMPT["Natural Language Prompt<br/>'Unitree G1 pick up brown box from shelf...'"]
        LLM["LLM (Gemini 3.6 Flash / Claude 3.7)<br/>via OpenAI-Compatible Endpoint"]
        RAW_SPEC["Raw Environment Graph Spec<br/>(Pydantic / JSON-LD 1.1)"]
        NL_PROMPT --> LLM
        LLM --> RAW_SPEC
    end

    subgraph STAGE_2 ["2. Semantic Invariant & SHACL Gate"]
        LIFT["spec_to_rdf_graph()<br/>(Bidirectional Lifting)"]
        RDF_STAR_NODE["RDF-star In-Memory Graph<br/>&lt;&lt; :brown_box :placedOn :wireshelving &gt;&gt;<br/>  :surfaceAnchor 'shelf_tier_1' ;<br/>  :nominalHeight 0.75 ."]
        SHACL_GATE["SHACL-star Validator (pyshacl)<br/>• Terrain Plane Invariant<br/>• WBC Single-Thread Invariant<br/>• Corridor Clearance &gt;= 0.60m<br/>• Fixture Containment Gate"]
        RAW_SPEC --> LIFT
        LIFT --> RDF_STAR_NODE
        RDF_STAR_NODE --> SHACL_GATE
    end

    subgraph STAGE_3 ["3. LPG Dual-Store Sync & Query"]
        NEO4J_STORE["Neo4j Property Graph (neo4j-arena)<br/>• (:RigidObject)-[:PLACED_ON {height: 0.75}]->(:Fixture)<br/>• (:Embodiment)-[:STANDS_NEAR {distance: 0.85m}]->(:Fixture)<br/>• Cypher Spatial & Reachability Queries"]
        SHACL_GATE ==>|"Valid Graph"| NEO4J_STORE
    end

    subgraph STAGE_4 ["4. Compilation & PhysX Simulation"]
        LOWER_COMP["lower_rdf_graph_to_spec()<br/>(SPARQL-star Lowering Compiler)"]
        YAML_SPEC["Validated Executable Spec YAML<br/>(g1_pick_and_place_brown_box.yaml)"]
        BUILDER_PIPE["ArenaEnvBuilder & Task Factory<br/>(Scene Assembly & PhysX Spawners)"]
        PHYSX_RUN["Isaac Sim / PhysX 6.0 Runtime<br/>• G1 Bipedal Locomotion (Pink WBC)<br/>• Stable Collision Settling<br/>• Viewport Video / GUI (--viz kit)"]
        
        SHACL_GATE ==> LOWER_COMP
        LOWER_COMP --> YAML_SPEC
        YAML_SPEC --> BUILDER_PIPE
        BUILDER_PIPE --> PHYSX_RUN
    end

    subgraph STAGE_5 ["5. Telemetry & Provenance Backpropagation"]
        EVAL_PIPE["policy_runner.py Rollout<br/>(ZeroActionPolicy / GR00T Policy)"]
        PROV_GRAPH["telemetry_to_prov.py<br/>(W3C PROV-O Graph: eval_telemetry.ttl)<br/>:eval_run prov:wasGeneratedBy :eval_act ;<br/>  prov:used :scene_graph, :model_checkpoint ;<br/>  arena:metric_success_rate 1.0 ."]
        
        PHYSX_RUN --> EVAL_PIPE
        EVAL_PIPE --> PROV_GRAPH
        PROV_GRAPH -.->|"Causal Feedback Loop"| NL_PROMPT
    end

    SHACL_GATE -.->|"Violation Traces<br/>(Self-Healing Loop)"| LLM
```

#### The 5 Pillars of the Mental Model

1. **Dual-Plane Duality (Semantic Plane $\leftrightarrow$ Simulation Plane)**:
   * *Semantic Plane*: Operates on entities, continuous edge properties (`surface_anchor`, `nominal_height`, `clearance`), and lineage graphs.
   * *Simulation Plane*: Operates on continuous physical dynamics, collision meshes, sensor streams, and joint torques.
   * *Compiler Bridge*: SPARQL-star lowering compiler (`rdf_lowering.py`) and Cypher synchronizer (`lpg_neo4j_sync.py`) perform bidirectional translations.

2. **Hierarchical Spatial Containment**:
   * Prevents objects from scattering across massive building USD bounds by strictly enforcing parent-child spatial hierarchies:
     $$\text{Building} \xrightarrow{\text{CONTAINS\_FIXTURE}} \text{Shelf/Table} \xrightarrow{\text{PLACED\_ON } \{\text{anchor, height}\}} \text{Manipuland}$$
     $$\text{Shelf/Table} \xleftarrow{\text{STANDS\_NEAR } \{\text{dist: 0.85m, facing: shelf}\}} \text{Humanoid Robot}$$

3. **Declarative SHACL-star Invariant Gates**:
   * Eliminates invalid physical setups (void spawns, single-threaded QP solver multi-env violations, unnavigable gaps $<0.60\text{m}$) before simulation boot. Violations trigger an automated LLM self-healing repair prompt.

4. **Enterprise LPG Dual-Store (Neo4j)**:
   * Graph persistence on Bolt port `7687` allows complex spatial topology queries, pathfinding, and interactive visual exploration in Neo4j Bloom.

5. **W3C PROV-O Telemetry & Auditability**:
   * Evaluated outcomes are serialized into `eval_telemetry.ttl`, enabling root-cause attribution linking physical task success/failure back to the prompt, model checkpoint, and scene parameters.

---

## 2. The Labeled Property Graph (LPG) Architecture

The **Labeled Property Graph (LPG)** is implemented across three coordinated layers:

```mermaid
flowchart TD
    subgraph LPG_LAYER_1 ["Layer 1: Storage & Graph Analytics (Neo4j / Cypher / Memgraph)"]
        LPG_STORE["Native Property Graph Store:<br/>• Nodes: (:Embodiment {id: 'g1', mass: 35.0})<br/>• Edges: -[:PLACED_ON {height: 0.75, clearance: 0.08}]->"]
    end

    subgraph LPG_LAYER_2 ["Layer 2: Semantic Isomorphism & Invariant Gate (RDF-star / SHACL)"]
        RDF_STAR["RDF-star Triples (W3C standard for LPG):<br/>&lt;&lt; :box :placedOn :shelf &gt;&gt; :nominalHeight 0.75 ."]
    end

    subgraph LPG_LAYER_3 ["Layer 3: Python In-Memory Runtime (NetworkX / ArenaEnvGraphSpec)"]
        PY_GRAPH["ArenaEnvGraphSpec (In-Memory LPG Model):<br/>• AssetSpec Nodes + SpatialRelationSpec Edges with Properties"]
    end

    LPG_LAYER_1 <-->|Isomorphic Projection| LPG_LAYER_2
    LPG_LAYER_2 ==> LPG_LAYER_3
```

### 2.1 Native LPG Cypher Schema & Examples

#### A. Creating the Scene as an LPG (Cypher):
```cypher
// 1. Create Nodes with Labels and Properties
CREATE (g1:Embodiment {
    id: "g1_robot", 
    registry_name: "g1_wbc_joint", 
    controller: "g1_decoupled_wbc_pink_action", 
    spawn_xyz: [0.0, 0.18, 0.0]
})
CREATE (room:Fixture {
    id: "galileo_room", 
    registry_name: "galileo_locomanip", 
    usd_path: "isaaclab_arena/assets/galileo_locomanip.usd"
})
CREATE (box:RigidObject {
    id: "brown_box", 
    registry_name: "brown_box", 
    is_target: true
})
CREATE (bin:RigidObject {
    id: "blue_sorting_bin", 
    registry_name: "blue_sorting_bin", 
    is_receptacle: true
})

// 2. Create Directed Relationships WITH First-Class Properties (LPG)
CREATE (box)-[:PLACED_ON {
    surface_anchor: "shelf_tier_1", 
    nominal_height: 0.0707, 
    bound_x: [0.5535, 0.6035], 
    bound_y: [0.1550, 0.2050], 
    clearance: 0.05
}]->(room)

CREATE (bin)-[:PLACED_ON {
    surface_anchor: "floor_deposit_zone", 
    nominal_height: -0.2641, 
    bound_x: [-0.2600, -0.2300], 
    bound_y: [-1.6400, -1.6100]
}]->(room)

CREATE (box)-[:NAV_CORRIDOR_TO {
    distance_m: 1.85, 
    min_clearance_radius: 0.60
}]->(bin);
```

### 2.2 Camera Semantic Representation & Viewport Grounding

To prevent "black screen" viewports (where the camera points into empty building space or unanchored voids), Cameras are modeled as first-class semantic entities in RDF-star and Neo4j LPG:

```mermaid
flowchart TD
    classDef scene fill:#1E293B,stroke:#64748B,stroke-width:2px,color:#F8FAFC;
    classDef fixture fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef object fill:#1D4ED8,stroke:#60A5FA,stroke-width:2px,color:#F8FAFC;
    classDef robot fill:#4C1D95,stroke:#A78BFA,stroke-width:2px,color:#F8FAFC;
    classDef camera fill:#9F1239,stroke:#FB7185,stroke-width:2px,color:#F8FAFC;

    SCENE[":scene_001<br/><i>a arena:EnvironmentGraph</i>"]:::scene
    CAM[":task_viewer_cam<br/><i>a arena:Camera</i><br/>[eyeOffset: -1.5, -1.5, 1.5]<br/>[fov: 65.0°]"]:::camera
    FIXTURE[":wireshelving<br/><i>a arena:Furniture, arena:Fixture</i>"]:::fixture
    OBJ[":brown_box<br/><i>a arena:RigidObject</i>"]:::object
    ROBOT[":g1_robot<br/><i>a arena:Embodiment</i>"]:::robot

    SCENE -->|"arena:hasCamera"| CAM
    SCENE -->|"arena:hasFixture"| FIXTURE
    SCENE -->|"arena:hasObject"| OBJ
    SCENE -->|"arena:hasEmbodiment"| ROBOT

    CAM -->|"arena:observes"| FIXTURE
    CAM -->|"arena:lookAtTarget"| OBJ
    ROBOT -->|"arena:standsNear (dist: 0.85m)"| FIXTURE
    OBJ -->|"arena:placedOn"| FIXTURE
```

```turtle
# RDF-star Camera Triples
:scene_001 arena:hasCamera :task_viewer_cam .

:task_viewer_cam a arena:Camera ;
    arena:observes :wireshelving ;
    arena:lookAtTarget :brown_box ;
    arena:eyeOffset [-1.5, -1.5, 1.5] ;
    arena:fov "65.0"^^xsd:float .
```

* **Root Cause of Black Screen**: In massive environment USDs (e.g. `galileo` spanning $\pm 100\text{m}$), unanchored furniture placements scatter outside the active room zone. When the viewport camera targets the unanchored object, it points into the outer void.
* **Solution**:
  1. Primary interaction furniture (`wireshelving`, `table`) carries an explicit workspace initial pose (e.g., `position_xyz: [0.0, 1.1, 0.0]`) and is marked `is_anchor`.
  2. The camera is semantically linked to observe the primary fixture/manipuland, ensuring the viewport is always centered on the robot and workspace.

---

## 3. Implemented Codebase Touchpoints

| Module Path | Implementation Status | Core Responsibilities |
| :--- | :--- | :--- |
| [`isaaclab_arena/agentic_environment_generation/rdf_lowering.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/rdf_lowering.py) | **COMPLETED & TESTED** | Bidirectional lifting (`spec_to_rdf_graph`) and SPARQL-star lowering (`lower_rdf_graph_to_spec`). |
| [`isaaclab_arena/agentic_environment_generation/rdf_validation.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/rdf_validation.py) | **COMPLETED & TESTED** | Evaluates in-memory graphs against W3C SHACL shapes via `pyshacl`. |
| [`isaaclab_arena/agentic_environment_generation/ontology/arena_constraints.shacl.ttl`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/ontology/arena_constraints.shacl.ttl) | **COMPLETED & TESTED** | Enforces Mandatory Terrain, Pink WBC Single-Thread Invariant, and Corridor Clearance $\ge 0.60\text{m}$. |
| [`isaaclab_arena/agentic_environment_generation/environment_generation_agent.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/environment_generation_agent.py) | **COMPLETED & TESTED** | Integrated SHACL validation gate directly inside `generate_spec()`. |
| [`isaaclab_arena/agentic_environment_generation/inference_backend.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/inference_backend.py) | **COMPLETED & TESTED** | OpenAI-compatible structured output runner with support for `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `GEMINI_API_KEY`. |
| [`isaaclab_arena/agentic_environment_generation/prim_path_inference.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/prim_path_inference.py) | **COMPLETED & TESTED** | Resilient USD prim resolution with fallback handling for remote S3 layers. |
| [`isaaclab_arena/evaluation/telemetry_to_prov.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/evaluation/telemetry_to_prov.py) | **COMPLETED & TESTED** | Serializes rollout metrics and execution activities into `eval_telemetry.ttl`. |
| [`isaaclab_arena/evaluation/policy_runner.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/evaluation/policy_runner.py) | **COMPLETED & TESTED** | Hooked rank-0 PROV-O telemetry serialization before evaluation reporting. |
| [`isaaclab_arena/agentic_environment_generation/lpg_neo4j_sync.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/lpg_neo4j_sync.py) | **COMPLETED & TESTED** | Native Cypher LPG synchronization, rich edge properties, and spatial hierarchy querying. |
| [`isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py) | **COMPLETED & TESTED** | CLI runner supporting `--mode {full, resolve, build}`, `--base_url`, video recording, and automated Neo4j sync. |

---

## 4. Scaffolded Core RDF-star & JSON-LD 1.1 Schemas

### 4.1 Global JSON-LD Context (`arena_context.jsonld`)

```json
{
  "@context": {
    "@version": 1.1,
    "arena": "https://isaac-sim.github.io/arena/schema#",
    "prov": "http://www.w3.org/ns/prov#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",

    "EnvironmentGraph": "arena:EnvironmentGraph",
    "Terrain": "arena:Terrain",
    "Embodiment": "arena:Embodiment",
    "Fixture": "arena:Fixture",
    "RigidObject": "arena:RigidObject",
    "EvaluationRun": "arena:EvaluationRun",

    "id": "@id",
    "type": "@type",
    "env_name": "arena:envName",
    "has_terrain": { "@id": "arena:hasTerrain", "@type": "@id" },
    "has_embodiment": { "@id": "arena:hasEmbodiment", "@type": "@id" },
    "has_fixture": { "@id": "arena:hasFixture", "@type": "@id" },
    "has_object": { "@id": "arena:hasObject", "@type": "@id" },
    "registry_name": "arena:registryName",
    "usd_path": "arena:usdPath",
    "controller_binding": "arena:controllerBinding",
    "surface_anchor": "arena:surfaceAnchor",
    "nominal_height": { "@id": "arena:nominalHeight", "@type": "xsd:float" },
    "bound_x": { "@id": "arena:boundX", "@container": "@list" },
    "bound_y": { "@id": "arena:boundY", "@container": "@list" },
    "clearance": { "@id": "arena:requiredClearance", "@type": "xsd:float" },

    "placed_on": { "@id": "arena:placedOn", "@type": "@id" },
    "placed_inside": { "@id": "arena:placedInside", "@type": "@id" },
    "nav_corridor_to": { "@id": "arena:navCorridorTo", "@type": "@id" },

    "was_generated_by": { "@id": "prov:wasGeneratedBy", "@type": "@id" },
    "was_derived_from": { "@id": "prov:wasDerivedFrom", "@type": "@id" },
    "used": { "@id": "prov:used", "@type": "@id" }
  }
}
```

---

### 4.2 RDF-star Turtle-star Ontology Schema (`arena_schema.ttl`)

```mermaid
flowchart TD
    classDef meta fill:#0F172A,stroke:#38BDF8,stroke-width:2px,color:#F8FAFC;
    classDef classNode fill:#1E293B,stroke:#94A3B8,stroke-width:2px,color:#F8FAFC;
    classDef subClassNode fill:#0F766E,stroke:#2DD4BF,stroke-width:2px,color:#F8FAFC;

    ENV["arena:EnvironmentGraph<br/><i>a owl:Class</i>"]:::meta
    PROV_ENT["prov:Entity<br/><i>a owl:Class</i>"]:::meta

    SCENE_ENT["arena:SceneEntity<br/><i>a owl:Class</i>"]:::classNode
    EVAL_RUN["arena:EvaluationRun<br/><i>a owl:Class</i>"]:::classNode

    TERRAIN["arena:Terrain"]:::subClassNode
    EMBODIMENT["arena:Embodiment"]:::subClassNode
    FIXTURE["arena:Fixture"]:::subClassNode
    FURNITURE["arena:Furniture"]:::subClassNode
    USD_PRIM["arena:USDPrim"]:::subClassNode
    SURFACE_ANCHOR["arena:SurfaceAnchor"]:::subClassNode
    RIGID_OBJ["arena:RigidObject"]:::subClassNode
    RECEPTACLE["arena:Receptacle"]:::subClassNode
    CAMERA["arena:Camera"]:::subClassNode

    ENV -.->|"rdfs:subClassOf"| PROV_ENT
    SCENE_ENT -.->|"rdfs:subClassOf"| PROV_ENT
    EVAL_RUN -.->|"rdfs:subClassOf"| PROV_ENT

    TERRAIN -.->|"rdfs:subClassOf"| SCENE_ENT
    EMBODIMENT -.->|"rdfs:subClassOf"| SCENE_ENT
    FIXTURE -.->|"rdfs:subClassOf"| SCENE_ENT
    USD_PRIM -.->|"rdfs:subClassOf"| SCENE_ENT
    SURFACE_ANCHOR -.->|"rdfs:subClassOf"| SCENE_ENT
    RIGID_OBJ -.->|"rdfs:subClassOf"| SCENE_ENT
    CAMERA -.->|"rdfs:subClassOf"| SCENE_ENT

    FURNITURE -.->|"rdfs:subClassOf"| FIXTURE
    RECEPTACLE -.->|"rdfs:subClassOf"| RIGID_OBJ

    ENV -->|"arena:hasTerrain"| TERRAIN
    ENV -->|"arena:hasEmbodiment"| EMBODIMENT
    ENV -->|"arena:hasFixture"| FIXTURE
    ENV -->|"arena:hasObject"| RIGID_OBJ
    ENV -->|"arena:hasCamera"| CAMERA

    FIXTURE -->|"arena:attachedToPrim"| USD_PRIM
    FIXTURE -->|"arena:hasSubSurface"| SURFACE_ANCHOR
    RIGID_OBJ -->|"arena:placedOnSubSurface"| SURFACE_ANCHOR
    EMBODIMENT -->|"arena:standsAtAffordance"| FIXTURE
    CAMERA -->|"arena:observes"| SCENE_ENT
```

```turtle
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

# Classes
arena:EnvironmentGraph a owl:Class, rdfs:Class ;
    rdfs:label "Environment Graph" ;
    rdfs:comment "Declarative attributed scene graph for IsaacLab-Arena." ;
    rdfs:subClassOf prov:Entity .

arena:SceneEntity a owl:Class ;
    rdfs:label "Scene Entity" ;
    rdfs:subClassOf prov:Entity .

arena:Terrain a owl:Class ;
    rdfs:subClassOf arena:SceneEntity .

arena:Embodiment a owl:Class ;
    rdfs:subClassOf arena:SceneEntity .

arena:Fixture a owl:Class ;
    rdfs:subClassOf arena:SceneEntity .

arena:RigidObject a owl:Class ;
    rdfs:subClassOf arena:SceneEntity .

arena:EvaluationRun a owl:Class ;
    rdfs:subClassOf prov:Entity .

# Properties
arena:hasTerrain a owl:ObjectProperty ;
    rdfs:domain arena:EnvironmentGraph ;
    rdfs:range arena:Terrain .

arena:hasEmbodiment a owl:ObjectProperty ;
    rdfs:domain arena:EnvironmentGraph ;
    rdfs:range arena:Embodiment .

arena:placedOn a owl:ObjectProperty ;
    rdfs:domain arena:RigidObject ;
    rdfs:range arena:SceneEntity .

arena:navCorridorTo a owl:ObjectProperty ;
    rdfs:domain arena:Fixture ;
    rdfs:range arena:Fixture .
```

---

## 5. W3C PROV-O Genealogy & Telemetry Engine

```mermaid
flowchart LR
    AGENT["prov:Agent<br/>:agent_gemini_3_6"] -->|prov:wasAssociatedWith| ACT1["prov:Activity<br/>:activity_prompt_synthesis"]
    SPEC["prov:Entity<br/>:grounded_task_spec_v1"] -->|prov:used| ACT1
    ACT1 -->|prov:wasGeneratedBy| SCENE["prov:Entity<br/>:scene_g1_locomanip_001"]
    
    SCENE -->|prov:used| ACT2["prov:Activity<br/>:activity_gr00t_eval_5558"]
    POLICY["prov:Entity<br/>:checkpoint_20000"] -->|prov:used| ACT2
    ACT2 -->|prov:wasGeneratedBy| EVAL["prov:Entity<br/>:eval_run_20260827_01<br/>• taskSuccess=1.0<br/>• meanLatencyMs=18.2<br/>• settleDivergence=0.0"]
```

### PROV-O Evaluation Run Triples (`eval_telemetry.ttl`)

```mermaid
flowchart TD
    classDef agent fill:#312E81,stroke:#818CF8,stroke-width:2px,color:#F8FAFC;
    classDef activity fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#F8FAFC;
    classDef entity fill:#1E293B,stroke:#94A3B8,stroke-width:2px,color:#F8FAFC;
    classDef metric fill:#701A75,stroke:#F472B6,stroke-width:2px,color:#F8FAFC;

    AGENT[":agent_gemini_3_6<br/><i>a prov:Agent</i><br/>[model: gemini-3.6-flash]"]:::agent
    ACT_SYNTH[":activity_prompt_synthesis<br/><i>a prov:Activity</i>"]:::activity
    SPEC[":grounded_task_spec_v1<br/><i>a prov:Entity</i>"]:::entity
    SCENE[":scene_g1_locomanip_001<br/><i>a arena:EnvironmentGraph, prov:Entity</i>"]:::entity
    CHECKPOINT[":checkpoint_20000<br/><i>a prov:Entity</i><br/>[weights: GR00T-v2.0]"]:::entity
    ACT_EVAL[":activity_gr00t_eval_5558<br/><i>a prov:Activity</i><br/>[started: 2026-08-27T20:55:00Z]"]:::activity
    EVAL_RUN[":eval_run_20260827_01<br/><i>a arena:EvaluationRun, prov:Entity</i><br/><b>taskSuccess:</b> true<br/><b>completedSteps:</b> 1200<br/><b>latency:</b> 18.2ms"]:::metric

    AGENT -->|"prov:wasAssociatedWith"| ACT_SYNTH
    ACT_SYNTH -->|"prov:used"| SPEC
    ACT_SYNTH -->|"prov:wasGeneratedBy"| SCENE

    AGENT -->|"prov:wasAssociatedWith"| ACT_EVAL
    ACT_EVAL -->|"prov:used"| SCENE
    ACT_EVAL -->|"prov:used"| CHECKPOINT
    EVAL_RUN -->|"prov:wasGeneratedBy"| ACT_EVAL
    EVAL_RUN -->|"arena:evaluatedGraph"| SCENE
```

```turtle
@prefix :      <https://isaac-sim.github.io/arena/instances/> .
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

:activity_gr00t_eval_5558 a prov:Activity ;
    prov:startedAtTime "2026-08-27T20:55:00Z"^^xsd:dateTime ;
    prov:endedAtTime "2026-08-27T20:56:45Z"^^xsd:dateTime ;
    prov:used :scene_g1_locomanip_001, :checkpoint_20000 .

:checkpoint_20000 a prov:Entity ;
    arena:modelWeightsPath "/models/isaaclab_arena/locomanipulation_tutorial/checkpoint-20000" ;
    arena:embodimentTag "NEW_EMBODIMENT" .

:eval_run_20260827_01 a arena:EvaluationRun, prov:Entity ;
    prov:wasGeneratedBy :activity_gr00t_eval_5558 ;
    arena:evaluatedGraph :scene_g1_locomanip_001 ;
    arena:taskSuccess "true"^^xsd:boolean ;
    arena:completedSteps 1200 ;
    arena:metric_mean_latency_ms "18.2"^^xsd:float ;
    arena:metricsPayload "{\"mean_latency_ms\": 18.2, \"completed_steps\": 1200}" .
```

---

## 6. SHACL-star Semantic Validation Engine (`arena_constraints.shacl.ttl`)

```mermaid
flowchart TD
    classDef shape fill:#451A03,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef target fill:#1E293B,stroke:#38BDF8,stroke-width:2px,color:#F8FAFC;
    classDef pass fill:#064E3B,stroke:#10B981,stroke-width:2px,color:#F8FAFC;
    classDef fail fill:#7F1D1D,stroke:#EF4444,stroke-width:2px,color:#F8FAFC;

    GRAPH_TARGET["arena:EnvironmentGraph<br/><i>(Target Node)</i>"]:::target
    EMB_TARGET["arena:Embodiment<br/><i>(Target Node)</i>"]:::target
    CAM_TARGET["arena:Camera<br/><i>(Target Node)</i>"]:::target

    S1["arena:MandatoryTerrainShape<br/>[minCount: 1, maxCount: 1]"]:::shape
    S2["arena:PinkWBCEnvironmentCountShape<br/>[SPARQL: num_envs == 1]"]:::shape
    S3["arena:LocomotionCorridorClearanceShape<br/>[SPARQL: clearance &gt;= 0.60m]"]:::shape
    S4["arena:HierarchicalPlacementShape<br/>[SPARQL: manipuland on fixture]"]:::shape
    S5["arena:CameraObservationShape<br/>[minCount: 1 target]"]:::shape
    S6["arena:RobotAffordanceReachabilityShape<br/>[SPARQL: 0.50m &lt;= dist &lt;= 1.20m]"]:::shape

    VALIDATOR["W3C pyshacl Engine<br/><i>(validate_rdf_environment_graph)</i>"]:::target

    PASS_RES["conforms = True<br/><i>Lower to ArenaEnvGraphSpec</i>"]:::pass
    FAIL_RES["conforms = False<br/><i>Self-Healing LLM Repair Prompt</i>"]:::fail

    S1 -->|"sh:targetClass"| GRAPH_TARGET
    S3 -->|"sh:targetClass"| GRAPH_TARGET
    S4 -->|"sh:targetClass"| GRAPH_TARGET
    S2 -->|"sh:targetClass"| EMB_TARGET
    S6 -->|"sh:targetClass"| EMB_TARGET
    S5 -->|"sh:targetClass"| CAM_TARGET

    GRAPH_TARGET --> VALIDATOR
    EMB_TARGET --> VALIDATOR
    CAM_TARGET --> VALIDATOR

    VALIDATOR -->|"Pass"| PASS_RES
    VALIDATOR -->|"Violations"| FAIL_RES
```

```turtle
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .


# 1. Mandatory Physical Ground Surface Invariant
arena:MandatoryTerrainShape a sh:NodeShape ;
    sh:targetClass arena:EnvironmentGraph ;
    sh:property [
        sh:path arena:hasTerrain ;
        sh:minCount 1 ;
        sh:maxCount 1 ;
        sh:message "FATAL: Every EnvironmentGraph MUST contain exactly 1 physical terrain ground plane." ;
    ] .

# 2. Pink WBC Single-Threaded Pinocchio Invariant
arena:PinkWBCEnvironmentCountShape a sh:NodeShape ;
    sh:targetClass arena:Embodiment ;
    sh:sparql [
        a sh:SPARQLConstraint ;
        sh:message "CRITICAL: When using Pink WBC (g1_decoupled_wbc_pink_action), num_envs MUST equal 1 due to single-threaded Pinocchio QP solver." ;
        sh:select """
            SELECT $this
            WHERE {
                $this arena:controllerBinding "g1_decoupled_wbc_pink_action" .
                $this arena:numEnvs ?envs .
                FILTER (?envs > 1)
            }
        """ ;
    ] .

# 3. Room-Scale Locomotion Corridor Clearance Constraint
arena:LocomotionCorridorClearanceShape a sh:NodeShape ;
    sh:targetClass arena:EnvironmentGraph ;
    sh:sparql [
        a sh:SPARQLConstraint ;
        sh:message "ERROR: Free-space bipedal locomotion corridor clearance radius must be >= 0.60m." ;
        sh:select """
            SELECT $this
            WHERE {
                << ?src arena:navCorridorTo ?dst >> arena:minClearanceRadius ?r .
                FILTER (?r < 0.60)
            }
        """ ;
    ] .
```

---

## 7. Lowering Compiler Architecture (`rdf_lowering.py`)

```python
# Bidirectional lifting & SPARQL-star lowering
from isaaclab_arena.agentic_environment_generation.rdf_lowering import (
    lower_rdf_graph_to_spec,
    spec_to_rdf_graph,
)
from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph

# 1. Lift Pydantic Spec to RDF-star Triples
rdf_graph = spec_to_rdf_graph(spec)

# 2. Validate against W3C SHACL Constraints
conforms, report = validate_rdf_environment_graph(rdf_graph)
assert conforms, f"SHACL Violation:\n{report}"

# 3. Lower RDF-star Graph back into Executable ArenaEnvGraphSpec
compiled_spec = lower_rdf_graph_to_spec(rdf_graph)
```

---

## 8. Integrated MCP Servers & Skills Ecosystem

```mermaid
flowchart TD
    subgraph ACTIVE_MCPS ["Active Runtime MCP Servers"]
        M_FS["filesystem<br/>• Read/write TTL, JSON-LD, and specs"]
        M_ANS["ansible<br/>• Automated sim cluster deployment"]
        M_GCP["gcp-cloud<br/>• Cloud GPU provisioning for evals"]
        M_PW["playwright<br/>• Visual web UI inspection (LeRobot/Neo4j)"]
        M_TF["terraform<br/>• Cloud infrastructure as code"]
    end

    subgraph EXT_MCPS ["Target Graph & Simulation MCP Servers"]
        E_NEO["neo4j/mcp (neo4j-mcp-server)<br/>• Cypher graph mutations & LPG schema"]
        E_GDS["neo4j-contrib/gds-agent<br/>• Graph data science & shortest path"]
        E_RDF["emekaokoye/mcp-rdf-explorer<br/>• RDF-star SPARQL inspection"]
        E_USD["NVIDIA-Omniverse/kit-usd-agents<br/>• USD Code, OmniUI, Kit MCPs"]
        E_SIM["whats2000/isaacsim-mcp-server<br/>• Live socket control (42+ tools)"]
    end

    subgraph AGENT_SKILLS ["Repository & NVIDIA Agent Skills"]
        S_RDF["agentic-rdf-star-env-gen<br/>• Main pipeline orchestrator"]
        S_I4H["i4h-workflow suite<br/>• Scene edit, dataset mimic, rollout validate"]
        S_OPT["cuopt-numerical-optimization-api<br/>• GPU-accelerated spatial CSP placement"]
        S_DATA["data-designer<br/>• Synthetic dataset distribution builder"]
        S_USD["omniverse-usd-performance-tuning<br/>• USD hierarchy & memory optimizer"]
        S_CUDF["accelerated-computing-cudf<br/>• GPU DataFrame analytics for massive scenes"]
    end

    ACTIVE_MCPS <--> S_RDF
    EXT_MCPS <--> S_RDF
    S_RDF --> S_OPT
    S_RDF --> S_I4H
    S_RDF --> S_USD
```

---

## 9. Architectural Exploration Options & Trade-Offs

| Dimension | Option A: In-Memory RDFLib/SHACL *(Active)* | Option B: Neo4j LPG Dual-Store *(Active)* | Option C: RDF-star + cuOpt CSP | Option D: Live Sim MCP Loop |
| :--- | :--- | :--- | :--- | :--- |
| **Primary Strength** | Zero infra overhead; purely in-process Python | Rich Cypher graph querying & visual exploration (Bloom) | Solves highly complex 3D object clutter & collision constraints on GPU | Immediate interactive visual feedback inside Isaac Sim viewport |
| **Infrastructure** | None (`pip install rdflib pyshacl`) | Docker container (`neo4j:5.26`) | NVIDIA GPU with cuOpt library | Running Isaac Sim Kit instance + MCP socket |
| **Verification Speed** | Ultra-fast (<15ms per scene) | Fast (~25ms via Bolt) | Ultra-fast GPU solve (<10ms) | Real-time interactive |
| **Graph Scaling** | Up to $10^5$ triples | Up to $10^8$ nodes/edges | Continuous bounds | Single active stage |
| **Current Status** | **Implemented & Verified** | **Implemented & Verified** | Exploration Option | Exploration Option |

---

## 10. Actionable Plan to Add Skills and MCP Servers

### Step 1: Install Python Graph Semantic Stack *(Completed)*
```bash
pip install rdflib==7.6.0 pyshacl==0.40.1 neo4j==6.2.0
```

### Step 2: Register Neo4j MCP Server & Container (`neo4j-mcp-server`)
1. Run local Neo4j Community instance via Docker with advertised ports:
   ```bash
   docker run -d --name neo4j-arena \
       -p 7475:7474 -p 7688:7687 \
       -e NEO4J_AUTH=neo4j/isaaclab_arena_password \
       -e NEO4J_dbms_default__advertised__address=localhost \
       -e NEO4J_dbms_connector_bolt_advertised__address=localhost:7688 \
       -e NEO4J_dbms_connector_http_advertised__address=localhost:7475 \
       neo4j:5.26-community
   ```
2. Configure MCP server in Antigravity / Claude config:
   ```json
   {
     "mcpServers": {
       "neo4j": {
         "command": "uvx",
         "args": [
           "neo4j-mcp-server",
           "--neo4j-uri", "bolt://localhost:7688",
           "--neo4j-user", "neo4j",
           "--neo4j-password", "isaaclab_arena_password"
         ]
       }
     }
   }
   ```

---

## 11. Phased Implementation Roadmap & Live Status

```mermaid
gantt
    title RDF-star & PROV-O Migration Roadmap
    dateFormat  YYYY-MM-DD
    section Completed
    Phase 1: Core Ontologies & Schemas     :done, p1, 2026-08-27, 1d
    Phase 2: SHACL Validation & Agent Loop :done, p2, 2026-08-28, 1d
    Phase 3: Lowering, Lifting & PROV-O    :done, p3, 2026-08-28, 1d
    Phase 4: Neo4j LPG Dual-Store Sync     :done, p4, 2026-08-28, 1d
    section Next Phases
    Phase 5: Automated G1 100-Scene Evals  :active, p5, 2026-08-29, 4d
```

---

## 12. Coherent Testing, Visual Inspection & Validation Protocol

To maintain complete confidence throughout development, the pipeline adopts a **4-Tier Verification Ladder**:

```mermaid
flowchart TD
    T1["Tier 1: Fast Pytest Suite (&lt;5s)<br/>• RDF-star SPARQL queries<br/>• SHACL constraint shapes<br/>• Bidirectional graph lifting<br/>• PROV-O serialization"]
    T2["Tier 2: Knowledge Graph Resolution (--mode resolve)<br/>• LLM prompt synthesis<br/>• In-memory RDF-star graph construction<br/>• SHACL-star validation & self-healing"]
    T3["Tier 3: Zero-Action Physics Settling (--mode build)<br/>• PhysX gravity & collision settlement<br/>• Bipedal humanoid balance check<br/>• Headless MP4 video recording / Live Viewport"]
    T4["Tier 4: Closed-Loop Policy Rollout (policy_runner.py)<br/>• GR00T / OpenPI closed-loop execution (50 Hz)<br/>• Task success metric logging<br/>• Automated eval_telemetry.ttl PROV-O export"]

    T1 --> T2
    T2 --> T3
    T3 --> T4
```

---

### 12.1 Tier 1: Automated Unit & Semantic Tests (In Docker)

Execute the full suite of unit, RDF lowering, SHACL validation, and PROV-O tests:

```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh -m pytest \
  isaaclab_arena/tests/test_rdf_validation.py \
  isaaclab_arena/tests/test_rdf_lowering.py \
  isaaclab_arena/tests/test_telemetry_to_prov.py \
  isaaclab_arena/tests/test_environment_generation_agent.py -v
```

---

### 12.2 Tier 2: Agentic Synthesis & SHACL Gate (`--mode resolve`)

Synthesize an environment and validate it through SHACL **without booting the full PhysX engine**:

```bash
docker exec -it \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -e OPENAI_API_KEY="$GEMINI_API_KEY" \
  -e OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --model "gemini-3.6-flash" \
  --prompt "Unitree G1 humanoid pick up brown box from the shelf in galileo room and place it into the blue sorting bin" \
  --out_dir /workspaces/isaaclab_arena/generated_envs/g1_box_pnp
```

---

### 12.3 Tier 3: Zero-Action Physics Settlement & Visual Inspection (`--mode build`)

Once the environment graph YAML is generated, verify that all objects, robots, and collision meshes settle stably without tumbling off rims:

#### A. Headless with MP4 Video Recording (Remote / Cloud / Docker):
```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode build \
  --headless \
  --num_envs 1 \
  --num_steps 100 \
  --enable_cameras \
  --record_viewport_video \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_box_pnp/g1_pick_and_place_brown_box.yaml
```

#### B. Interactive GUI Viewport (Local Workstation with Display):
```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode build \
  --num_envs 1 \
  --num_steps 300 \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_box_pnp/g1_pick_and_place_brown_box.yaml
```

#### C. All-in-One End-to-End Generation & Video Recording (`--mode full`):
```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode full \
  --headless \
  --num_envs 1 \
  --num_steps 100 \
  --enable_cameras \
  --record_viewport_video \
  --api_key "$GEMINI_API_KEY" \
  --base_url "https://generativelanguage.googleapis.com/v1beta/openai/" \
  --model "gemini-3.6-flash" \
  --prompt "Unitree G1 humanoid pick up brown box from the wireshelving in galileo room and place it into the blue sorting bin" \
  --out_dir /workspaces/isaaclab_arena/generated_envs/g1_box_pnp
```

---

### 12.4 Tier 4: Closed-Loop Policy Evaluation & PROV-O Lineage Export

Evaluate a trained policy (GR00T / OpenPI) and automatically capture the W3C PROV-O lineage graph:

```bash
docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --environment_name g1_pick_and_place_brown_box \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_policy.GR00TPolicy \
  --num_episodes 10 \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/g1_box_pnp_eval
```

Inspect the generated provenance graph `eval_telemetry.ttl`:
```bash
cat /workspaces/isaaclab_arena/eval_output/g1_box_pnp_eval/eval_telemetry.ttl
```

---

### 12.5 Visualizer & Headless Execution Conventions (`--viz` vs `--headless`)

In Isaac Lab 3.0 Beta / Isaac Sim 6.0:
* **Default Mode is Headless**: Omit `--viz` entirely for standard headless simulation in Docker.
* **Why `--viz kit --headless` Fails**:
  * Passing `--viz kit` instructs Isaac Lab to load the `isaaclab_visualizers.kit.KitVisualizerCfg` extension.
  * Adding `--headless` disables all visualizer instances at the `AppLauncher` level.
  * `SimulationContext` detects this conflict and raises:
    ```text
    RuntimeError: Explicitly requested visualizer(s) ['kit'] could not be configured.
    ```
* **Interactive GUI Visualization (`--viz kit`) Runbook**:
  1. **Grant X11 Display Permission (Run on Host)**:
     ```bash
     xhost +local:root
     ```
  2. **Launch with Kit Viewport (Omit `--headless`)**:
     * **Agentic Generated Environment**:
       ```bash
       docker exec -it \
         -e DISPLAY="$DISPLAY" \
         isaaclab_arena-latest /isaac-sim/python.sh \
         isaaclab_arena/evaluation/policy_runner.py \
         --viz kit \
         --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_box_pnp/g1_pick_and_place_brown_box.yaml \
         --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
         --enable_cameras \
         --num_steps 100 \
         --num_envs 1
       ```
     * **First-Party Environment Task (e.g., Robolab)**:
       ```bash
       docker exec -it \
         -e DISPLAY="$DISPLAY" \
         isaaclab_arena-latest /isaac-sim/python.sh \
         isaaclab_arena/evaluation/policy_runner.py \
         --viz kit \
         --env_graph_spec_yaml /workspaces/isaaclab_arena/isaaclab_arena_environments/robolab/tasks/mustard_above_raisin.yaml \
         --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
         --enable_cameras \
         --num_steps 100 \
         --num_envs 1
       ```
* **Headless Video Recording Alternative (Remote / Cloud / Docker)**:
  * When no X11 display is available, omit `--viz` and use offscreen rendering:
    ```bash
    docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
      isaaclab_arena/evaluation/policy_runner.py \
      --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_box_pnp/g1_pick_and_place_brown_box.yaml \
      --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
      --num_steps 100 \
      --num_envs 1 \
      --enable_cameras \
      --record_viewport_video \
      --output_base_dir /workspaces/isaaclab_arena/eval_output/g1_pnp_test
    ```

---

### 12.6 Tier 2b: Neo4j LPG & Cypher Spatial Inspection

Inspect and query the generated Labeled Property Graph (LPG) in Neo4j:

1. **List Stored Environments**:
   ```bash
   docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
     isaaclab_arena_examples/agentic_environment_generation/inspect_lpg.py --list
   ```

2. **Inspect Entities, Spatial Anchors & Containment Chains**:
   ```bash
   docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
     isaaclab_arena_examples/agentic_environment_generation/inspect_lpg.py \
     --env_name test_g1_shelf_pnp_lpg
   ```

3. **Execute Ad-Hoc Cypher Spatial Queries**:
   ```bash
   docker exec -it isaaclab_arena-latest /isaac-sim/python.sh \
     isaaclab_arena_examples/agentic_environment_generation/inspect_lpg.py \
     --cypher "MATCH (s)-[r]->(t) WHERE r.surface_anchor IS NOT NULL RETURN s.id, type(r), r.surface_anchor, r.nominal_height, t.id"
   ```

4. **Neo4j Web Browser (Bloom Graph UI)**:
   * Open **`http://localhost:7475`** (or `http://127.0.0.1:7475`) in your host browser.
   * In the connection modal, configure:
     * **Connect URL**: `bolt://localhost:7688` (or `neo4j://localhost:7688`)
     * **Username**: `neo4j`
     * **Password**: `isaaclab_arena_password`
   * In the top Cypher query bar, run:
     ```cypher
     MATCH (n)-[r]->(m) RETURN n, r, m
     ```

---

## 13. Telescopic USD Scene Hierarchy & Dollhouse Unpacking Architecture

### 13.1 The "Dollhouse" Mental Model

A complex 3D simulation environment (e.g. a warehouse, kitchen, or laboratory USD) is not a single flat mesh, but a **structured architectural dollhouse**. Within this dollhouse, spatial containment unfolds telescopically across 6 discrete abstraction tiers:

```mermaid
flowchart TD
    subgraph TIER_0 ["Tier 0: Root World Stage & Background Dollhouse"]
        USD_BG["Scene USD Stage (e.g., galileo_simplified.usd, robocasa_kitchen.usd)<br/>• Root Transform, Physics Scene, Environment Lighting"]
    end

    subgraph TIER_1 ["Tier 1: Introspected Scene Sub-Zones & Built-in Prims"]
        USD_PRIM_1["Built-in Storage Bay<br/>/World/galileo/StorageBay_01"]
        USD_PRIM_2["Built-in Reception Counter<br/>/World/galileo/ReceptionCounter"]
        USD_PRIM_3["Built-in Floor Staging Area<br/>/World/galileo/FloorZone_North"]
        USD_BG -->|USD Stage Introspection| USD_PRIM_1
        USD_BG -->|USD Stage Introspection| USD_PRIM_2
        USD_BG -->|USD Stage Introspection| USD_PRIM_3
    end

    subgraph TIER_2 ["Tier 2: Spawned Furniture & Fixtures"]
        FURN_1["Wire Shelving Unit<br/>(:wireshelving a arena:Furniture)"]
        FURN_2["Sorting Bin Receptacle<br/>(:blue_sorting_bin a arena:Receptacle)"]
        USD_PRIM_1 -->|ATTACHED_TO_PRIM| FURN_1
        USD_PRIM_3 -->|ATTACHED_TO_PRIM| FURN_2
    end

    subgraph TIER_3 ["Tier 3: Introspected Fixture Sub-Surfaces & Tiers"]
        SHELF_T1["Shelf Tier 1 (Lower Surface: z=0.45m)"]
        SHELF_T2["Shelf Tier 2 (Middle Surface: z=0.75m)"]
        SHELF_T3["Shelf Tier 3 (Upper Surface: z=1.15m)"]
        FURN_1 -->|HAS_SUB_SURFACE| SHELF_T1
        FURN_1 -->|HAS_SUB_SURFACE| SHELF_T2
        FURN_1 -->|HAS_SUB_SURFACE| SHELF_T3
    end

    subgraph TIER_4 ["Tier 4: Manipulands & Dynamic Rigid Objects"]
        OBJ_1["Brown Packaging Box<br/>(:brown_box a arena:RigidObject)"]
        SHELF_T2 -->|"PLACED_ON_TIER (clearance: 0.02m)"| OBJ_1
    end

    subgraph TIER_5 ["Tier 5: Embodiment Standoff & Affordance Waypoints"]
        ROBOT["Unitree G1 Bipedal Humanoid<br/>(:g1_robot a arena:Embodiment)"]
        FURN_1 -->|"STANDS_AT_AFFORDANCE (offset: [0.0, -0.85, 0.0], yaw: 90°)"| ROBOT
    end

    subgraph TIER_6 ["Tier 6: Observational & Viewport Cameras"]
        CAM["Task Viewport Camera<br/>(:spectator_cam a arena:Camera)"]
        OBJ_1 -->|"OBSERVES_INTERACTION_ZONE (eye: [-1.2, -1.0, 1.8], fov: 65°)"| CAM
    end
```

### 13.2 Telescopic RDF-star & LPG Schema Representation

In the Property Graph, this multi-tier containment is encoded directly as attributed edges:

```mermaid
flowchart TD
    %% Styling
    classDef scene fill:#1E293B,stroke:#64748B,stroke-width:2px,color:#F8FAFC;
    classDef prim fill:#0F766E,stroke:#14B8A6,stroke-width:2px,color:#F8FAFC;
    classDef fixture fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef surface fill:#D97706,stroke:#FDE68A,stroke-width:1px,color:#1E293B;
    classDef object fill:#1D4ED8,stroke:#60A5FA,stroke-width:2px,color:#F8FAFC;
    classDef robot fill:#4C1D95,stroke:#A78BFA,stroke-width:2px,color:#F8FAFC;
    classDef camera fill:#9F1239,stroke:#FB7185,stroke-width:2px,color:#F8FAFC;

    %% Entities
    GALILEO[":galileo<br/><i>a arena:BackgroundScene</i>"]:::scene
    STORAGE_BAY[":galileo_storage_bay_01<br/><i>a arena:USDPrim</i>"]:::prim
    WIRESHELVING[":wireshelving<br/><i>a arena:Furniture, arena:Fixture</i>"]:::fixture
    TIER_2[":shelf_tier_2<br/><i>a arena:SurfaceAnchor</i>"]:::surface
    BROWN_BOX[":brown_box<br/><i>a arena:RigidObject</i>"]:::object
    G1_ROBOT[":g1_robot<br/><i>a arena:Embodiment</i>"]:::robot
    VIEWER_CAM[":task_viewer_cam<br/><i>a arena:Camera</i>"]:::camera

    %% Telescopic Hierarchy
    GALILEO -->|"arena:hasSubPrim"| STORAGE_BAY
    WIRESHELVING -->|"arena:attachedToPrim"| STORAGE_BAY
    WIRESHELVING -->|"arena:hasSubSurface"| TIER_2
    
    %% RDF-star Reified Relations
    BROWN_BOX -->|"arena:placedOnSubSurface<br/><b>clearance:</b> 0.02m"| TIER_2
    G1_ROBOT -->|"arena:standsAtAffordance<br/><b>standoff:</b> 0.85m"| WIRESHELVING
    VIEWER_CAM -->|"arena:observesInteraction<br/><b>fov:</b> 65°"| WIRESHELVING
    VIEWER_CAM -->|"arena:lookAtTarget"| BROWN_BOX
```

```turtle
# 1. Background Scene Introspection

:galileo a arena:BackgroundScene ;
    arena:usdPath "assets/galileo_simplified.usd" ;
    arena:hasSubPrim :galileo_storage_bay_01, :galileo_floor_zone_north .

:galileo_storage_bay_01 a arena:USDPrim ;
    arena:primPath "/World/galileo/StorageBay_01" ;
    arena:primType "Xform" ;
    arena:worldCenter [ 0.0, 1.1, 0.0 ] ;
    arena:bounds [ -1.0, 1.0, -0.5, 0.5, 0.0, 2.5 ] .

# 2. Spawning Furniture inside the Dollhouse Room
:wireshelving a arena:Furniture, arena:Fixture ;
    arena:registryName "wireshelving_a01_vomp_robolab" ;
    arena:attachedToPrim :galileo_storage_bay_01 ;
    arena:hasSubSurface :shelf_tier_1, :shelf_tier_2, :shelf_tier_3 .

:shelf_tier_2 a arena:SurfaceAnchor ;
    arena:anchorName "shelf_tier_2" ;
    arena:nominalHeight 0.75 ;
    arena:usableArea [ 0.80, 0.40 ] .

# 3. Placing Manipuland on the Shelf Tier
<< :brown_box arena:placedOnSubSurface :shelf_tier_2 >>
    arena:clearance "0.02"^^xsd:float ;
    arena:contactNormal [ 0.0, 0.0, 1.0 ] .

# 4. Robot Affordance Standoff
<< :g1_robot arena:standsAtAffordance :wireshelving >>
    arena:standoffDistance "0.85"^^xsd:float ;
    arena:relativeHeading "front_facing" ;
    arena:kinematicReachability true .

# 5. Semantic Camera Grounding
<< :task_viewer_cam arena:observesInteraction :wireshelving >>
    arena:lookAtTarget :brown_box ;
    arena:eyeOffset [ -1.5, -1.5, 1.5 ] ;
    arena:fov "65.0"^^xsd:float .
```

### 13.3 Cypher Telescopic Query Patterns (Neo4j)

```cypher
// Query: Find the complete telescopic path from building down to manipuland and observing camera
MATCH path = (bg:BackgroundScene)-[:CONTAINS_PRIM]->(zone:USDPrim)
             <-[:ATTACHED_TO_PRIM]-(furn:Furniture)
             -[:HAS_SUB_SURFACE]->(tier:SurfaceAnchor)
             <-[:PLACED_ON_SUB_SURFACE]-(obj:RigidObject)
MATCH (furn)<-[:STANDS_AT_AFFORDANCE]-(bot:Embodiment)
MATCH (obj)<-[:OBSERVES_INTERACTION_ZONE]-(cam:Camera)
RETURN bg.id AS room, zone.prim_path AS room_zone, furn.id AS fixture, 
       tier.anchorName AS shelf_tier, obj.id AS object, 
       bot.id AS robot, cam.id AS camera;
```

### 13.4 Two-Pass Telescopic Resolution Engine

1. **Pass 1 (USD Dollhouse Introspection & Zone Selection)**:
   * The agent queries the Background USD Prim Tree (using `load_usd_prim_tree()`) to inspect available sub-prims (rooms, tables, bays, counters).
   * Generates `ObjectReference`s mapping semantic task zones to USD prim paths.

2. **Pass 2 (Furniture & Manipuland Telescopic Lowering)**:
   * Spawns furniture fixtures anchored to the selected room prims.
   * Places manipulands onto fixture surface tiers rather than floor bounds.
   * Computes robot affordance standoff poses ($\approx 0.85\text{m}$ in front of the fixture).
   * Generates camera eye and lookat targets focused on the interaction envelope.

3. **SHACL Telescopic Invariant Gate**:
   * Rejects any scene where an object is placed in a non-existent prim path or an unanchored building coordinate.
   * Ensures the camera viewing vector intersects the bounding box of the active interaction zone.

---

## 14. Scene Relationship Exploration Algorithms & Robot-Centric Multi-Camera Framing

### 14.1 Insights from `g1_brainco_extension` (`0.2.1-dev`)

In the `g1_brainco_extension` project on branch `0.2.1-dev`, composing an apple pick-and-place task in `galileo_simplified.usd` revealed critical geometric and semantic realities for complex USD environments:

1. **Camera-to-Robot Grounding**: Perspective and observation cameras cannot be statically defined in world space. When a robot turns, relocates, or works in a different bay, a static camera ends up behind building walls or pointing into empty voids. The spectator/perspective camera must maintain an **invariant geometric transform relative to the robot base and its manipulation workspace**.
2. **The Camera Triad**:
   * **Ego Head Camera (`arena:EgoCamera`)**: Mounted on `head_link`, looking down at the dual-arm workspace for neural policy input (GR00T / OpenPI).
   * **Top-Down Camera (`arena:TopCamera`)**: Positioned orthogonally above the interaction centroid looking straight down, providing spatial layout clarity and container boundary verification.
   * **Perspective Viewport Camera (`arena:PerspectiveCamera`)**: Positioned at a fixed azimuth/elevation over the robot's shoulder (e.g. $45^\circ$ azimuth, $35^\circ$ elevation, $1.6\text{m}$ standoff) focusing on the midpoint between the robot's hands and the target manipuland.
3. **Active Workspace Subgraph Isolation**: In massive USD scenes ($>200\text{m}$ building models), $>95\%$ of meshes are decorative or distant. The environment generator must isolate the **minimal active interaction subgraph** (Support Fixture $\to$ Robot Standoff $\to$ Manipulands $\to$ Camera Triad) and deactivate unreferenced clutter prims in the immediate task volume.

---

### 14.2 Robot-Centric Multi-Camera Knowledge Graph

```mermaid
flowchart TD
    classDef robot fill:#4C1D95,stroke:#A78BFA,stroke-width:2px,color:#F8FAFC;
    classDef camera fill:#9F1239,stroke:#FB7185,stroke-width:2px,color:#F8FAFC;
    classDef workspace fill:#0F766E,stroke:#2DD4BF,stroke-width:2px,color:#F8FAFC;
    classDef object fill:#1D4ED8,stroke:#60A5FA,stroke-width:2px,color:#F8FAFC;
    classDef fixture fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;

    ROBOT[":g1_robot<br/><i>a arena:Embodiment</i><br/>[basePose: (x_r, y_r, yaw_r)]"]:::robot
    SHELF[":wireshelving<br/><i>a arena:Furniture</i>"]:::fixture
    APPLE[":apple<br/><i>a arena:RigidObject</i>"]:::object
    PLATE[":plate<br/><i>a arena:Receptacle</i>"]:::object

    WS_CENTER["Active Workspace Centroid<br/><i>P_ws = 0.5 * (P_apple + P_plate)</i>"]:::workspace

    TOP_CAM[":top_camera<br/><i>a arena:TopCamera</i><br/>[eye: P_ws + (0, 0, 1.4m)]<br/>[lookAt: P_ws]"]:::camera
    PERSP_CAM[":perspective_camera<br/><i>a arena:PerspectiveCamera</i><br/>[mode: over_the_shoulder]<br/>[standoff: 1.6m, az: 45°, el: 35°]"]:::camera
    HEAD_CAM[":head_camera<br/><i>a arena:EgoCamera</i><br/>[prim: head_link/RobotHeadCam]"]:::camera

    ROBOT -->|"arena:standsAtAffordance (dist: 0.85m)"| SHELF
    APPLE -->|"arena:placedOnSubSurface"| SHELF
    PLATE -->|"arena:placedOnSubSurface"| SHELF
    APPLE -->|"arena:destinationLocation"| PLATE

    ROBOT -->|"arena:hasOnboardCamera"| HEAD_CAM
    ROBOT -->|"arena:framesPerspectiveView"| PERSP_CAM
    WS_CENTER -->|"arena:orthogonallyObservedBy"| TOP_CAM

    PERSP_CAM -->|"arena:lookAtTarget"| WS_CENTER
    HEAD_CAM -->|"arena:gazeTarget"| APPLE
```

---

### 14.3 Four Core Algorithms for Scene Relationship Exploration

#### Algorithm 1: Robot-Centric Perspective & Top Camera Framing
Computes invariant camera eye/lookat coordinates dynamically from the robot's base frame and active manipulation centroid:

```python
def compute_robot_relative_camera_poses(
    robot_pos: tuple[float, float, float],
    robot_yaw_rad: float,
    manipuland_pos: tuple[float, float, float],
    destination_pos: tuple[float, float, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute exact camera coordinates for the Perspective, Top, and Ego triad."""
    import numpy as np

    # 1. Interaction Workspace Centroid
    if destination_pos is not None:
        ws_centroid = 0.5 * (np.array(manipuland_pos) + np.array(destination_pos))
    else:
        ws_centroid = np.array(manipuland_pos)

    # 2. Robot Direction Vectors
    u_fwd = np.array([np.cos(robot_yaw_rad), np.sin(robot_yaw_rad), 0.0])
    u_lat = np.array([-np.sin(robot_yaw_rad), np.cos(robot_yaw_rad), 0.0])

    # 3. Perspective Viewport Camera (Over-the-shoulder, 45 deg lateral, 35 deg elevation)
    d_back = 1.10   # meters behind robot
    d_side = 0.65   # meters to the side (right shoulder)
    h_elev = 0.85   # meters above pelvis
    r_pelvis_z = robot_pos[2] + 0.75

    persp_eye = (
        np.array([robot_pos[0], robot_pos[1], r_pelvis_z])
        - d_back * u_fwd
        + d_side * u_lat
        + np.array([0.0, 0.0, h_elev])
    )

    # 4. Top-Down Orthogonal Camera
    h_top = 1.35  # meters above workspace plane
    top_eye = ws_centroid + np.array([0.0, 0.0, h_top])

    return {
        "perspective_camera": {
            "eye": tuple(float(x) for x in persp_eye),
            "lookat": tuple(float(x) for x in ws_centroid),
            "fov": 65.0,
            "mode": "over_the_shoulder",
        },
        "top_camera": {
            "eye": tuple(float(x) for x in top_eye),
            "lookat": tuple(float(x) for x in ws_centroid),
            "fov": 60.0,
            "mode": "top_down_orthogonal",
        },
    }
```

---

#### Algorithm 2: Active Interaction Subgraph Isolation ("What Matters" Extractor)
Filters complex building stages (e.g. `galileo_simplified.usd`) and isolates the active task volume:

1. **Anchor Discovery**: Find the primary fixture supporting the task (`shelf`, `table`, `counter`).
2. **Radial Clearance Sphere**: Compute active radius $R_{\text{active}} = 1.5\text{m}$ around the fixture centroid.
3. **USD Prim Pruning**: Query all USD prims within $R_{\text{active}}$. Prims not belonging to the fixture, manipuland, or destination are flagged for `prestartup` deactivation (e.g. `deactivate_background_prims`), preventing collision mesh interference with the robot's arms.
4. **Floor Patch Grounding**: Measure the support top height $z_{\text{shelf}}$ and project ground contact plane $z_{\text{floor}} = z_{\text{shelf}} - h_{\text{fixture\_height}}$, ensuring feet rest flush without penetration.

---

#### Algorithm 3: Frustum-Occlusion Raycast & Line-of-Sight Visibility Discovery
Ensures the perspective camera is never placed behind background building columns or high structural beams:

1. **Candidate Trajectory**: Generate a candidate camera arc $\mathcal{C}(\theta)$ for azimuth angles $\theta \in [20^\circ, 70^\circ]$ relative to the robot's facing vector.
2. **Raycast Query**: Cast rays from $\mathcal{C}(\theta)$ to the robot hands and the target object against the background USD collision mesh.
3. **Occlusion Score**: Select the azimuth $\theta^*$ with zero ray intersections and maximum clearance from adjacent obstacle hulls.

---

#### Algorithm 4: Dual-Arm Reachability & Kinematic Standoff Alignment
Positions the robot base optimally relative to the fixture edge:

1. **Edge Extraction**: Find the front bounding edge of the support surface along the active interaction axis.
2. **Standoff Distance**: Position the robot pelvis at $d_{\text{standoff}} = -0.03\text{m}$ inside the front bounding edge along $X$, with lateral offset $y_{\text{robot}} = 0.08\text{m}$ centered between the pick object ($y = -0.105\text{m}$) and destination plate ($y = +0.105\text{m}$).
3. **Arm Reach Verification**: Verify that both pick and place targets lie within the Pink IK reach ellipsoid ($\le 0.72\text{m}$ from the respective shoulder joint).

---

### 14.4 RDF-star Schema Extensions for Robot-Centric Cameras (`arena_schema.ttl`)

```turtle
# Camera Sub-Classes
arena:TopCamera a owl:Class ;
    rdfs:subClassOf arena:Camera ;
    rdfs:comment "Orthogonal overhead camera centered directly on the manipulation workspace." .

arena:PerspectiveCamera a owl:Class ;
    rdfs:subClassOf arena:Camera ;
    rdfs:comment "Over-the-shoulder or third-person viewport camera relative to the robot." .

arena:EgoCamera a owl:Class ;
    rdfs:subClassOf arena:Camera ;
    rdfs:comment "Onboard egocentric camera mounted on the robot head link." .

# Object Properties
arena:framesPerspectiveView a owl:ObjectProperty ;
    rdfs:domain arena:Embodiment ;
    rdfs:range arena:PerspectiveCamera .

arena:orthogonallyObservedBy a owl:ObjectProperty ;
    rdfs:domain arena:SceneEntity ;
    rdfs:range arena:TopCamera .

# Reified RDF-star Triples
<< :perspective_cam arena:framesPerspectiveView :g1_robot >>
    arena:cameraMode "over_the_shoulder" ;
    arena:azimuthOffset "45.0"^^xsd:float ;
    arena:elevationOffset "35.0"^^xsd:float ;
    arena:standoffDistance "1.6"^^xsd:float ;
    arena:targetAsset :brown_box .
```

---

## 15. Inside-Out Dynamic Relationship Expansion Architecture

### 15.1 Paradigm Shift: Inside-Out vs. Top-Down Scene Generation

Traditional environment synthesis attempted a **Top-Down** approach: starting from a massive 200m building mesh and randomly trying to scatter furniture and robots within it, resulting in empty voids, collision jams, and disconnected cameras.

The LPG and RDF-star architecture instead operates **Inside-Out**, expanding symmetrically from the most critical interaction relationships towards the surrounding background:

```mermaid
flowchart TD
    classDef core fill:#991B1B,stroke:#F87171,stroke-width:2px,color:#F8FAFC;
    classDef anchor fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef robot fill:#4C1D95,stroke:#A78BFA,stroke-width:2px,color:#F8FAFC;
    classDef camera fill:#9F1239,stroke:#FB7185,stroke-width:2px,color:#F8FAFC;
    classDef scene fill:#1E293B,stroke:#64748B,stroke-width:2px,color:#F8FAFC;

    subgraph RANK_0 ["Rank 0: Task Goal Core (Active Manipulation Pair)"]
        TASK_CORE["Task Objective: Pick(o_1) & Place(o_2)<br/>• Active Manipulation Centroid: P_task = 0.5*(P_o1 + P_o2)<br/>• Interaction Envelope Radius: r = 0.40m"]:::core
    end

    subgraph RANK_1 ["Rank 1: Dynamic Surface Anchor Construction"]
        ANCHOR["Dynamic Support Anchor (Shelf Tier / Table Top)<br/>• Surface Bounds encompassing o_1, o_2 with clearance<br/>• Anchor Height: z_surface = 0.75m"]:::anchor
    end

    subgraph RANK_2 ["Rank 2: Robot Kinematic Affordance Standoff"]
        BOT_STAND["Embodiment Base Alignment<br/>• Standoff: d_standoff = -0.03m from front edge<br/>• Heading: yaw facing P_task<br/>• Dual-Arm Pink IK Reach Ellipsoid Check"]:::robot
    end

    subgraph RANK_3 ["Rank 3: Observation Camera Triad Grounding"]
        CAM_RIG["Camera Triad<br/>• Perspective: Over-the-shoulder (az: 45°, el: 35°, d: 1.6m)<br/>• Top: Orthogonal overhead (z = z_task + 1.35m)<br/>• Ego: head_link pitch-gaze"]:::camera
    end

    subgraph RANK_4 ["Rank 4: Surrounding USD Scene & Physics Floor Raycasting"]
        ROOM_SURROUND["Background Scene USD & Collision Envelope<br/>• Floor Raycast: z_floor = z_anchor - h_fixture<br/>• Workspace Prim Pruning: Deactivate clutter in r &lt;= 1.5m"]:::scene
    end

    TASK_CORE ==>|1. Expands To Support| ANCHOR
    ANCHOR ==>|2. Expands To Standoff| BOT_STAND
    BOT_STAND ==>|3. Expands To Gaze| CAM_RIG
    ANCHOR ==>|4. Expands To Room| ROOM_SURROUND
    BOT_STAND ==>|4. Expands To Floor| ROOM_SURROUND
```

---

### 15.2 Rank-Ordered Expansion Protocol

1. **Rank 0 (Task Goal Core)**:
   * The user prompt specifies the goal pair: e.g. `pick_up_object: apple`, `destination_location: plate`.
   * These objects form the initial core interaction seed.
2. **Rank 1 (Dynamic Surface Anchor)**:
   * The LPG identifies the support relation. Rather than hardcoding spatial bounding boxes, the anchor is a dynamic surface representation derived from the task objects' combined footprint plus clearance:
     $$\mathcal{B}_{\text{anchor}} = \text{AABB}(o_1) \cup \text{AABB}(o_2) \oplus \delta_{\text{clearance}}$$
3. **Rank 2 (Robot Affordance Standoff)**:
   * The robot is positioned at the front edge of the dynamic anchor along the task interaction axis, facing the task centroid.
4. **Rank 3 (Camera Triad Grounding)**:
   * The perspective viewport camera is locked into an invariant over-the-shoulder vector from the robot's pelvis frame pointing at the task centroid.
   * The top camera is locked directly above the task centroid.
5. **Rank 4 (Surrounding Scene & Floor Raycasting)**:
   * Floor contact is resolved dynamically by projecting raycasts downward from the anchor and robot feet onto the USD collision mesh ($z_{\text{floor}}$), eliminating hardcoded floor plane injections.
   * Background prims within the active task radius $R_{\text{active}} \le 1.5\text{m}$ that are not part of the task graph are automatically deactivated pre-startup.

---

### 15.3 Cypher Inside-Out Expansion Query

```cypher
// 1. Start from Task Goal Pair (Rank 0)
MATCH (task:TaskSpec)-[:TARGETS_OBJECT]->(o1:RigidObject)
MATCH (task)-[:TARGETS_DESTINATION]->(o2:RigidObject)

// 2. Expand outwards to Dynamic Support Anchor (Rank 1)
MATCH (o1)-[:PLACED_ON_SUB_SURFACE]->(anchor:SurfaceAnchor)<-[:PLACED_ON_SUB_SURFACE]-(o2)
MATCH (furn:Furniture)-[:HAS_SUB_SURFACE]->(anchor)

// 3. Expand outwards to Robot Standoff (Rank 2)
MATCH (furn)<-[:STANDS_AT_AFFORDANCE]-(robot:Embodiment)

// 4. Expand outwards to Camera Triad (Rank 3)
MATCH (robot)-[:FRAMES_PERSPECTIVE_VIEW]->(cam_persp:PerspectiveCamera)
MATCH (anchor)-[:ORTHOGONALLY_OBSERVED_BY]->(cam_top:TopCamera)

// 5. Expand outwards to Room & Floor (Rank 4)
MATCH (furn)-[:ATTACHED_TO_PRIM]->(room_zone:USDPrim)<-[:CONTAINS_PRIM]-(room:BackgroundScene)

RETURN task.description, o1.id, o2.id, anchor.anchorName, robot.id, 
       cam_persp.id, cam_top.id, room.id;
```

---

## 16. Recursive USD Prim Scene Graph Mapping & Bidirectional LPG $\leftrightarrow$ RDF-star Isomorphism Engine

### 16.1 The Challenge: Progressive Scene Graph Decomposition of `galileo.usd`

Massive environment assets like `galileo.usd` (spanning $\pm 100\text{m}$ with hundreds of nested sub-prims, warehouse racks, storage bays, and collision meshes) cannot be treated as opaque monolithic background meshes. Doing so leaves the AI agent blind to the internal rooms, shelves, collision barriers, and floor planes.

To solve this, the pipeline incorporates an **Automated Recursive Scene Graph Lifter** that extracts the full hierarchy of USD Prims into a **Dual-Store LPG (Neo4j) & RDF-star Knowledge Graph**, enabling progressive multi-depth AI exploration:

```mermaid
flowchart TD
    classDef stage fill:#0F172A,stroke:#38BDF8,stroke-width:2px,color:#F8FAFC;
    classDef zone fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#F8FAFC;
    classDef fixture fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef surface fill:#D97706,stroke:#FDE68A,stroke-width:1px,color:#1E293B;
    classDef task fill:#991B1B,stroke:#F87171,stroke-width:2px,color:#F8FAFC;
    classDef agent fill:#4C1D95,stroke:#A78BFA,stroke-width:2px,color:#F8FAFC;

    subgraph USD_STAGE ["USD Stage Decomposition (galileo.usd)"]
        D0["Depth 0: Root USD Stage<br/>/World/galileo (200m x 200m building)"]:::stage
        D1["Depth 1: Functional Sub-Zones<br/>• /World/galileo/StorageBay_01<br/>• /World/galileo/ReceptionCounter<br/>• /World/galileo/WorkshopZone"]:::zone
        D2["Depth 2: Fixtures & Obstacles<br/>• /World/galileo/StorageBay_01/wireshelving<br/>• /World/galileo/StorageBay_01/pallet_rack"]:::fixture
        D3["Depth 3: Sub-Surfaces & Tiers<br/>• shelf_tier_1 (z=0.45m)<br/>• shelf_tier_2 (z=0.75m)<br/>• shelf_tier_3 (z=1.15m)"]:::surface
        D4["Depth 4: Task Placement & Affordance<br/>• brown_box placedOnSubSurface shelf_tier_2<br/>• g1_robot standsAtAffordance (dist: 0.85m)<br/>• Camera Triad (Ego / Top / Over-the-Shoulder)"]:::task
    end

    subgraph PROGRESSIVE_AGENT ["Recursive AI Agent Exploration Loop"]
        LLM_AGENT["Antigravity AI Agent / LLM Orchestrator<br/>(Progressive Cypher / SPARQL Reasoning)"]:::agent
        NEO_LPG["Neo4j LPG Store<br/>(High-Performance Spatial Graph Queries)"]:::stage
        RDF_STAR_STORE["RDF-star / SHACL Store<br/>(Formal Ontological Invariant Gate)"]:::stage
    end

    D0 --> D1
    D1 --> D2
    D2 --> D3
    D3 --> D4

    D0 -.->|USD Parser & BBoxCache| NEO_LPG
    D1 -.->|USD Parser & BBoxCache| NEO_LPG
    D2 -.->|USD Parser & BBoxCache| NEO_LPG
    D3 -.->|USD Parser & BBoxCache| NEO_LPG

    NEO_LPG <-->|"Bidirectional Isomorphism Engine<br/>(LPG &lt;==&gt; RDF-star)"| RDF_STAR_STORE

    LLM_AGENT <-->|"1. Query Available Zones"| NEO_LPG
    LLM_AGENT <-->|"2. Query Fixtures in Zone"| NEO_LPG
    LLM_AGENT <-->|"3. Query Surface Tiers"| NEO_LPG
    LLM_AGENT -->|"4. Assert Task & Affordances"| RDF_STAR_STORE
```

---

### 16.2 The Bidirectional LPG $\leftrightarrow$ RDF-star Isomorphism Engine

The system maintains formal mathematical isomorphism between the Property Graph (LPG in Neo4j) and the RDF-star Semantic Graph:

| Property Graph Concept (LPG / Neo4j) | RDF-star Semantic Mapping (W3C standard) | Example in `galileo.usd` |
| :--- | :--- | :--- |
| **Node Label (`:USDPrim`)** | `rdf:type arena:USDPrim` | `:galileo_bay_01 a arena:USDPrim .` |
| **Node Property (`prim_path`)** | RDF Datatype Property `arena:primPath` | `:galileo_bay_01 arena:primPath "/World/galileo/StorageBay_01" .` |
| **Node Property (`world_bbox`)** | RDF Literal / List `arena:worldBoundingBox` | `:galileo_bay_01 arena:bounds [-1.0, 1.0, -0.5, 0.5, 0.0, 2.5] .` |
| **Directed Relationship (`[:ATTACHED_TO_PRIM]`)** | RDF Object Property `arena:attachedToPrim` | `:wireshelving arena:attachedToPrim :galileo_bay_01 .` |
| **Edge Property (`{nominal_height: 0.75, clearance: 0.05}`)** | **RDF-star Reified Triples (First-Class Metadata)** | `<< :box arena:placedOnSubSurface :shelf_tier_2 >> arena:nominalHeight 0.75 ; arena:clearance 0.05 .` |

#### Isomorphism Conversion Code Contract:
```python
def lpg_edge_to_rdf_star(subject_id: str, rel_type: str, object_id: str, properties: dict) -> str:
    """Converts a Neo4j LPG edge with properties into an RDF-star reified triple."""
    subj = f":{subject_id}"
    pred = f"arena:{rel_type.lower()}"
    obj = f":{object_id}"
    
    reified_header = f"<< {subj} {pred} {obj} >>"
    property_lines = []
    for k, v in properties.items():
        if isinstance(v, (int, float)):
            property_lines.append(f'    arena:{k} "{v}"^^xsd:float')
        elif isinstance(v, str):
            property_lines.append(f'    arena:{k} "{v}"')
        elif isinstance(v, (list, tuple)):
            property_lines.append(f'    arena:{k} {list(v)}')
            
    return reified_header + "\n" + " ;\n".join(property_lines) + " .\n"
```

---

### 16.3 The 5-Step Recursive Agent Exploration Protocol

When given a high-level task prompt (*"Unitree G1 pick up brown box from wireshelving in Galileo and place into blue sorting bin"*), the Antigravity Agent recursively queries and maps the environment:

#### Step 1: Macro Zone Discovery (Recursion Depth 0 $\to$ 1)
The agent queries the top-level zones in `galileo.usd`:
```cypher
MATCH (bg:BackgroundScene {name: 'galileo'})-[:HAS_USD_ZONE]->(zone:USDPrim)
RETURN zone.prim_path AS prim, zone.zone_type AS type, zone.world_center AS center
```
*Result*: Agent selects `/World/galileo/StorageBay_01` based on task semantics (storage/shelving).

#### Step 2: In-Zone Fixture & Obstacle Discovery (Recursion Depth 1 $\to$ 2)
The agent queries existing fixtures or anchors inside the selected bay:
```cypher
MATCH (zone:USDPrim {prim_path: '/World/galileo/StorageBay_01'})-[:CONTAINS_FIXTURE]->(f:Furniture)
RETURN f.id, f.registry_name, f.bounds
```
*Result*: Discovers `wireshelving` fixture or creates local anchor at bay coordinates `[0.0, 1.1, 0.0]`.

#### Step 3: Micro Surface & Tier Discovery (Recursion Depth 2 $\to$ 3)
The agent queries the functional surface tiers of the fixture:
```cypher
MATCH (f:Furniture {id: 'wireshelving'})-[:HAS_SUB_SURFACE]->(tier:SurfaceAnchor)
RETURN tier.anchorName, tier.nominal_height, tier.usable_area
```
*Result*: Selects `shelf_tier_2` ($z=0.75\text{m}$) for pick object and floor deposit zone for receptacle.

#### Step 4: Affordance & Camera Grounding (Recursion Depth 3 $\to$ 4)
* Places `brown_box` onto `shelf_tier_2` with $0.02\text{m}$ clearance.
* Solves `g1_robot` standing standoff $0.85\text{m}$ in front of the shelf facing $+X$.
* Computes Robot-Centric Camera Triad:
  - Perspective camera: $1.1\text{m}$ behind, $0.65\text{m}$ right, $0.85\text{m}$ above pelvis looking at the shelf.
  - Top camera: $1.35\text{m}$ above workspace centroid looking down.

#### Step 5: Physics Verification & Clutter Pruning (Recursion Depth 4)
* Queries USD collision mesh directly beneath the robot feet to resolve exact $z_{\text{floor}} = -0.795\text{m}$.
* Queries all background prims within $1.5\text{m}$ of the workspace centroid and generates deactivation terms for non-task props.

---

### 16.4 Implementation Touchpoints in Codebase

| Component | Target File | Implementation Plan |
| :--- | :--- | :--- |
| **USD Stage Introspector** | [`isaaclab_arena/agentic_environment_generation/usd_stage_introspection.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/usd_stage_introspection.py) | Use `pxr.Usd` and `UsdGeom.BBoxCache` to extract rooms, collision hulls, and surface tiers into structured JSON. |
| **LPG Neo4j Sync** | [`isaaclab_arena/agentic_environment_generation/lpg_neo4j_sync.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/lpg_neo4j_sync.py) | Synchronize full USD Prim hierarchies (`:USDPrim`, `:HAS_USD_ZONE`, `[:ATTACHED_TO_PRIM]`) to Neo4j. |
| **RDF-star Lowering Compiler** | [`isaaclab_arena/agentic_environment_generation/rdf_lowering.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/rdf_lowering.py) | Lift and lower telescopic sub-prims, surface anchors, and camera triad between RDF-star and `ArenaEnvGraphSpec`. |
| **Camera Controller** | [`isaaclab_arena/utils/cameras.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/utils/cameras.py) | Implement [`compute_robot_relative_viewer_cfg()`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/utils/cameras.py#L182-L248) and hook into [`ArenaEnvBuilder`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/environments/arena_env_builder.py#L326-L338). |
| **Recursive Agent Loop** | [`isaaclab_arena/agentic_environment_generation/environment_generation_agent.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/environment_generation_agent.py) | Multi-pass agent that explores USD zones, grounds surface tiers, and validates against SHACL constraints. |

---

### 16.5 Neo4j Bloom Query for Galileo Exploration

To explore the mapped `galileo.usd` scene graph interactively in Neo4j Bloom / Browser:

```cypher
// Interactive Query: Visualize Galileo Room, Fixtures, Surface Tiers, Robot Standoff, and Cameras
MATCH (bg:BackgroundScene {name: 'galileo'})-[:HAS_USD_ZONE]->(zone:USDPrim)
OPTIONAL MATCH (zone)<-[:ATTACHED_TO_PRIM]-(furn:Furniture)
OPTIONAL MATCH (furn)-[:HAS_SUB_SURFACE]->(tier:SurfaceAnchor)
OPTIONAL MATCH (tier)<-[:PLACED_ON_SUB_SURFACE]-(obj:RigidObject)
OPTIONAL MATCH (furn)<-[:STANDS_AT_AFFORDANCE]-(robot:Embodiment)
OPTIONAL MATCH (robot)-[:FRAMES_PERSPECTIVE_VIEW]->(cam:PerspectiveCamera)
RETURN bg, zone, furn, tier, obj, robot, cam;
```

---

## 17. Generalist USD Traversal Engine & Directed Cyclic Random Graph (DCRG) Architecture

### 17.1 Mathematical Formulation: Scene Graphs as Directed Cyclic Random Graphs (DCRG)

In generalized robotics simulation and physical AI, an environment cannot be simplified into a simple acyclic tree. Physical environments and task workflows form a **Directed Cyclic Random Graph (DCRG)**:

$$\mathcal{G} = (\mathcal{V}, \mathcal{E}, \mathcal{P}, \mathcal{R})$$

Where:
* $\mathcal{V}$ is the set of heterogeneous scene vertices (Rooms, Fixtures, Surface Anchors, Manipulands, Embodiments, Cameras, Lighting, Tasks).
* $\mathcal{E} \subseteq \mathcal{V} \times \mathcal{V} \times \mathcal{T}$ is the set of directed typed edges (`CONTAINS`, `SUPPORTS`, `REACHES`, `OBSERVES`, `OBSTRUCTS`, `FEEDS_INTO`).
* **Cyclicity**: The graph contains closed directed cycles:
  - *Kinematic-Obstacle Cycle*: $\text{Robot} \xrightarrow{\text{MANIPULATES}} \text{Object} \xrightarrow{\text{RESTS\_ON}} \text{Table} \xrightarrow{\text{IMPEDES\_PATH}} \text{Robot}$.
  - *Perception Feedback Cycle*: $\text{Camera} \xrightarrow{\text{FRAMES}} \text{RobotGaze} \xrightarrow{\text{TRACKS}} \text{Target} \xrightarrow{\text{DEFINES\_LOOKAT}} \text{Camera}$.
  - *State Transition Cycle*: $\text{State}_{\text{Pick}} \xrightarrow{\text{SUCCESS}} \text{State}_{\text{Place}} \xrightarrow{\text{RESET}} \text{State}_{\text{Pick}}$.
* $\mathcal{P}(\text{state} \mid \mathcal{G})$ is the set of stochastic probability distributions (Domain Randomization):
  - Spatial pose ranges: $\vec{x}_{\text{pose}} \sim \mathcal{U}[\vec{x}_{\text{min}}, \vec{x}_{\text{max}}]$ on dynamic polygon manifolds $\mathcal{S}_{\text{surface}}$.
  - Physical distributions: Friction $\mu \sim \mathcal{N}(\mu_0, \sigma_\mu^2)$, Mass $m \sim \mathcal{U}[m_{\text{min}}, m_{\text{max}}]$, Camera focal jitter $\Delta f$.

```mermaid
flowchart LR
    classDef robot fill:#4C1D95,stroke:#A78BFA,stroke-width:2px,color:#F8FAFC;
    classDef object fill:#1D4ED8,stroke:#60A5FA,stroke-width:2px,color:#F8FAFC;
    classDef fixture fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef camera fill:#9F1239,stroke:#FB7185,stroke-width:2px,color:#F8FAFC;
    classDef room fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#F8FAFC;

    ROOM["Room Zone<br/><i>/World/Zone</i>"]:::room
    ROBOT["G1 Humanoid<br/><i>:g1_robot</i>"]:::robot
    OBJ["Manipuland<br/><i>:target_object</i>"]:::object
    TABLE["Support Fixture<br/><i>:workstation</i>"]:::fixture
    CAM["Observer Camera<br/><i>:perspective_cam</i>"]:::camera

    ROOM -->|"CONTAINS_FIXTURE"| TABLE
    ROOM -->|"ENCLOSES_SPACE"| ROBOT
    TABLE -->|"PROVIDES_SUPPORT {mu ~ U[0.4, 0.8]}"| OBJ
    ROBOT -->|"REACHES_INTO {ellipsoid_dist &lt;= 0.72m}"| OBJ
    ROBOT -->|"STANDS_NEAR {clearance: 0.85m}"| TABLE
    TABLE -->|"OBSTRUCTS_FEET_ZONE"| ROBOT
    CAM -->|"FRAMES_PERSPECTIVE_VIEW"| ROBOT
    CAM -->|"LOOK_AT_TARGET"| OBJ
    OBJ -->|"OCCLUDES_CAMERA_RAYCAST"| CAM
```

---

### 17.2 Intentions & Redesign of `usd_stage_introspection.py`

Rather than relying on brittle hardcoded strings (`"shelf"`, `"table"`, `"bay"`), `usd_stage_introspection.py` is being refactored into a **Generalist Geometric & Physical USD Traversal Engine**:

```mermaid
flowchart TD
    classDef step fill:#1E293B,stroke:#64748B,stroke-width:2px,color:#F8FAFC;
    classDef geom fill:#0F766E,stroke:#2DD4BF,stroke-width:2px,color:#F8FAFC;
    classDef phys fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef graph fill:#4C1D95,stroke:#A78BFA,stroke-width:2px,color:#F8FAFC;

    STAGE["Arbitrary USD Stage<br/>(galileo.usd, robocasa_kitchen.usd, factory.usd)"]:::step

    subgraph ENGINE ["Generalist USD Traversal Engine (usd_stage_introspection.py)"]
        CRAWLER["1. Universal USD Crawler<br/>• pxr.Usd.Stage traversal<br/>• pxr.UsdGeom.BBoxCache (OBB/AABB)"]:::geom
        SURFACE_EXTRACT["2. Geometric Surface Extractor<br/>• Mesh face normal filtering: n_z &gt;= 0.95<br/>• Planar polygon clustering (area &gt;= 0.04 m²)"]:::geom
        PHYS_CLASSIFIER["3. Physics & Semantic Classifier<br/>• UsdPhysics.CollisionAPI (Static Fixtures)<br/>• UsdPhysics.RigidBodyAPI (Dynamic Objects)<br/>• UsdPhysics.Joint (Articulated Mechanisms)"]:::phys
        DCRG_BUILDER["4. DCRG Spatial Relation Builder<br/>• Spatial containment matrices<br/>• Contact manifolds & clearance envelopes<br/>• Stochastic domain randomization bounds"]:::graph
    end

    LPG_STORE["Neo4j LPG Store<br/>(Directed Cyclic Graph)"]:::step
    RDF_STORE["RDF-star / SHACL Store<br/>(Reified Probabilistic Triples)"]:::step

    STAGE --> CRAWLER
    CRAWLER --> SURFACE_EXTRACT
    CRAWLER --> PHYS_CLASSIFIER
    SURFACE_EXTRACT --> DCRG_BUILDER
    PHYS_CLASSIFIER --> DCRG_BUILDER

    DCRG_BUILDER --> LPG_STORE
    DCRG_BUILDER --> RDF_STORE
```

#### Key Functional Enhancements:
1. **Geometric Surface Extractor (No string heuristics)**:
   - Reads raw mesh vertices (`UsdGeom.Mesh.GetPointsAttr()`) and face indices.
   - Computes face normal vectors $\vec{n} = \frac{(v_1 - v_0) \times (v_2 - v_0)}{\|(v_1 - v_0) \times (v_2 - v_0)\|}$.
   - Filters horizontal faces ($\vec{n} \cdot \hat{z} \ge 0.95$) and clusters contiguous coplanar patches into **Dynamic `SurfaceAnchor`s** with exact polygon boundaries and nominal heights.
2. **Physics & Articulation Classification**:
   - Inspects `UsdPhysics` APIs: Static colliders become `:Fixture`, unconstrained rigid bodies become `:RigidObject`, and jointed chains become `:ArticulatedFixture`.
3. **Spatial Containment & Contact Graph**:
   - Automatically computes 3D AABB inclusion: If $\text{AABB}(A) \subset \text{AABB}(B)$, creates `(A)-[:ENCLOSED_BY]->(B)`.
   - If $\text{BottomFace}(A)$ rests within $\Delta z \le 0.02\text{m}$ of $\text{TopFace}(B)$, creates `(A)-[:RESTS_ON]->(B)`.

---

### 17.3 Recursive Progressive Agent Traversal over DCRGs

To prevent infinite loops when an LLM agent queries a cyclic graph, the agent traversal protocol employs **Ranked Subgraph Focus with Cycle Detection**:

```python
class RecursiveSceneGraphExplorer:
    """Recursively queries the Directed Cyclic Random Graph with cycle prevention."""

    def __init__(self, neo4j_driver):
        self.driver = neo4j_driver
        self.visited_nodes: set[str] = set()

    def explore_zone_recursively(self, zone_id: str, max_depth: int = 4) -> dict[str, Any]:
        """Progressively expands outward from zone_id up to max_depth."""
        query = """
        MATCH path = (root {id: $zone_id})-[r*1..4]-(neighbor)
        WHERE ALL(n IN nodes(path) WHERE single(x IN nodes(path) WHERE x = n))
        RETURN nodes(path) AS entities, relationships(path) AS relations
        """
        with self.driver.session() as session:
            result = session.run(query, zone_id=zone_id)
            return self._format_dcrg_subgraph(result)
```

---

### 17.4 RDF-star Representation of Probabilistic DCRGs

In RDF-star, stochastic bounds and cyclic relations are reified with first-class distribution metadata:

```turtle
# 1. Dynamic Surface Anchor with Stochastic Sampling Polygon
:shelf_tier_2 a arena:SurfaceAnchor ;
    arena:nominalHeight "0.75"^^xsd:float ;
    arena:polygonVertices ( [ -0.4, -0.2, 0.75 ] [ 0.4, -0.2, 0.75 ] [ 0.4, 0.2, 0.75 ] [ -0.4, 0.2, 0.75 ] ) .

# 2. Reified Random Placement Distribution
<< :brown_box arena:placedOnSubSurface :shelf_tier_2 >>
    arena:poseDistribution "uniform_box" ;
    arena:positionLow [ -0.15, -0.10, 0.76 ] ;
    arena:positionHigh [ 0.15, 0.10, 0.76 ] ;
    arena:yawRange [ -0.25, 0.25 ] ;
    arena:frictionRange [ 0.5, 0.8 ] .

# 3. Kinematic-Obstacle Cycle
<< :g1_robot arena:standsAtAffordance :wireshelving >>
    arena:standoffDistance "0.85"^^xsd:float .

<< :wireshelving arena:impedesFootprint :g1_robot >>
    arena:minClearanceRadius "0.45"^^xsd:float .
```

---

## 18. The Causality Light Cone Architecture: Entropy Collapse & Progressive Graph Hops

### 18.1 The Paradigm: Creating Causality in High-Entropy USD Environments

In an ungrounded USD stage (or a raw language prompt), there is initially **zero physical and spatial causality**:
* Objects are unanchored floating coordinate noise scattered across unbounded $\mathbb{R}^3$.
* Fixtures have no established floor contact and may spawn into building walls.
* Robots have no reachability guarantee and can spawn in mid-air or out of manipulation range.
* Cameras have no gaze coupling and point into black voids or behind structural pillars.

When an environment lacks causality, every asset is an independent random variable with maximum entropy ($\mathcal{H} \to \infty$). The purpose of the agentic graph generation pipeline is **creating causality**: injecting physical, geometric, and semantic dependency chains where none existed before.

```mermaid
flowchart TD
    classDef past fill:#064E3B,stroke:#34D399,stroke-width:2px,color:#F8FAFC;
    classDef seed fill:#991B1B,stroke:#F87171,stroke-width:2px,color:#F8FAFC;
    classDef future fill:#1D4ED8,stroke:#60A5FA,stroke-width:2px,color:#F8FAFC;
    classDef outside fill:#334155,stroke:#64748B,stroke-width:1px,color:#94A3B8;

    subgraph PAST_CONE ["1. Past Causality Light Cone (Preconditions & Support Manifold)"]
        ROOM_FLOOR["USD Stage Floor Mesh<br/>(Normal Contact & Raycast Anchor: z_floor = -0.795m)"]:::past
        FIXTURE_SUPPORT["Shelf Fixture & Tier Anchor<br/>(Physical Support Manifold: z_shelf = 0.75m)"]:::past
    end

    subgraph SEED_EVENT ["2. The Causal Seed Event (Task Objective)"]
        TASK_EVENT["TASK EVENT: Pick(Box) & Place(Bin)<br/>• Active Manipulation Centroid: P_task<br/>• Collapses Spatial Uncertainty"]:::seed
    end

    subgraph FUTURE_CONE ["3. Future Causality Light Cone (Affordances, Reachability & Gaze)"]
        ROBOT_MANIFOLD["Robot Kinematic Reach Cone<br/>(||P_robot - P_task|| &lt;= 0.72m, facing theta)"]:::future
        CAMERA_FRUSTUM["Camera Line-of-Sight Frustum Cone<br/>(Over-the-shoulder, unoccluded line to P_task)"]:::future
    end

    subgraph OUTSIDE_CONE ["4. Spacelike Separated / Forbidden States (Pruned by SHACL)"]
        FLOATING_BOX["Floating Box in Void"]:::outside
        OCCLUDED_CAM["Camera Behind Concrete Wall"]:::outside
        FALLING_ROBOT["Robot Spawned in Mid-Air"]:::outside
    end

    ROOM_FLOOR ==>|Causal Precondition| FIXTURE_SUPPORT
    FIXTURE_SUPPORT ==>|Causal Support| TASK_EVENT
    TASK_EVENT ==>|Causal Reachability Constraint| ROBOT_MANIFOLD
    TASK_EVENT ==>|Causal Viewport Constraint| CAMERA_FRUSTUM
    ROBOT_MANIFOLD ==>|Foot Contact Grounding| ROOM_FLOOR

    OUTSIDE_CONE -.->|Rejected by SHACL Invariant Gate| SEED_EVENT
```

---

### 18.2 Mathematical Formalization of the Causality Light Cone

Inspired by relativistic causality (where an event $E_0$ at spacetime $(t_0, \vec{x}_0)$ can only interact with entities inside its light cone $c^2 \Delta t^2 \ge \Delta x^2$), the **Semantic Causality Light Cone** defines the valid manifold of scene entities:

$$\mathcal{C}(E_0) = \mathcal{C}^{-}(E_0) \cup \{E_0\} \cup \mathcal{C}^{+}(E_0)$$

Where:
1. **$E_0 = (\text{TaskObjective}, \vec{P}_{\text{task}})$ (The Causal Seed Event)**:
   The interaction centroid $\vec{P}_{\text{task}} = \frac{1}{2}(\vec{P}_{\text{pick}} + \vec{P}_{\text{place}})$ anchors the entire scene.
2. **$\mathcal{C}^{-}(E_0)$ (The Past Light Cone — Physical Preconditions)**:
   Entities that *must exist and be physically grounded* for $E_0$ to be stable:
   $$\mathcal{C}^{-}(E_0) = \left\{ \text{Fixture } F, \text{Surface } S, \text{Floor } G \;\middle|\; \vec{P}_{\text{task}} \in \text{Polygon}(S), \; z_S = z_F + h_{\text{tier}}, \; z_F = z_G + h_{\text{fixture}} \right\}$$
   *If the shelf is missing or floating, the past light cone is broken $\to$ simulation explodes.*
3. **$\mathcal{C}^{+}(E_0)$ (The Future Light Cone — Affordances & Observers)**:
   Entities that *can interact with or observe* $E_0$:
   $$\mathcal{C}^{+}(E_0) = \left\{ \text{Robot } R, \text{Camera } C \;\middle|\; \|\vec{P}_R - \vec{P}_{\text{task}}\| \le L_{\text{reach}}, \; \text{Raycast}(C \to \vec{P}_{\text{task}}) \cap \text{Obstacles} = \emptyset \right\}$$
   *Any robot or camera placed outside $\mathcal{C}^{+}(E_0)$ cannot reach or see the task.*
4. **Forbidden / Spacelike-Separated Manifold**:
   Any configuration $\vec{x} \notin \mathcal{C}(E_0)$ violates physics or task reachability and is strictly pruned by SHACL-star.

---

### 18.3 Progressive Graph Hops as Shannon Entropy Collapse

At each graph hop in the Labeled Property Graph (LPG), the agent traverses along the causality light cone, collapsing uncertainty and writing the resulting reified constraints to RDF-star:

$$\mathcal{H}(\text{SceneState}) = \mathcal{H}(E_0) + \mathcal{H}(\text{Support} \mid E_0) + \mathcal{H}(\text{Robot} \mid \text{Support}, E_0) + \mathcal{H}(\text{Camera} \mid \text{Robot}, E_0) + \dots$$

| Graph Hop Step | Prior State (No Causality) | Light Cone Constraint Applied | Result in RDF-star (Causality Created) |
| :--- | :--- | :--- | :--- |
| **Hop 0: Seed** | $\infty$ possible tasks in building | User prompt: `Pick(Box), Place(Bin)` | Defines Task Interaction Centroid $\vec{P}_{\text{task}}$. |
| **Hop 1: Support** | Shelf floating anywhere in $\pm 100\text{m}$ | Must physically support $\vec{P}_{\text{task}}$ at surface $z=0.75\text{m}$ | `<< :box :placedOnSubSurface :shelf_tier >>` (Entropy drops by 90%). |
| **Hop 2: Robot Standoff** | Robot can spawn anywhere in space | Must lie inside Kinematic Reach Cone ($\le 0.72\text{m}$) | `<< :g1_robot :standsAtAffordance :shelf >> :standoff 0.85m` (Entropy drops by 99%). |
| **Hop 3: Camera Triad** | Viewport points into black void | Must lie inside Over-the-Shoulder Frustum Cone | `<< :persp_cam :framesPerspectiveView :g1_robot >> :lookAt :box` (Unoccluded view). |
| **Hop 4: Ground Raycast** | Robot feet float or bounce | Must intersect USD Stage Floor Mesh ($z = -0.795\text{m}$) | `<< :g1_robot :groundedOn :galileo_floor >> :z -0.795m` (Zero physics penetration). |

---

### 18.4 Cyclic Causal Closure & Equilibrium

Because the graph is a **Directed Cyclic Random Graph (DCRG)**, the causal chain forms a closed loop:

$$\text{Floor} \xrightarrow{\text{grounds}} \text{Shelf} \xrightarrow{\text{supports}} \text{Box} \xrightarrow{\text{demands\_reach}} \text{Robot} \xrightarrow{\text{stands\_on}} \text{Floor}$$

A generated environment is physically valid if and only if the causal loop achieves equilibrium:

$$\oint_{\text{cycle}} \text{CausalConstraints} = \text{Valid}$$

* **SHACL-star Validation Gate**: If any link in the cycle fails (e.g. shelf height exceeds maximum arm elevation, or shelf collision hull forces the robot beyond reach distance), the causal loop fails to close, triggering automatic curriculum repair.
* **PROV-O Lineage**: Records the complete causal provenance trail (`prov:wasDerivedFrom`, `prov:wasGeneratedBy`) documenting the exact sequence of graph hops that collapsed the scene entropy.

---

### 18.5 RDF-star Representation of Causal Light Cones

```turtle
# 1. Causal Seed Event
:task_seed_001 a arena:TaskSeedEvent ;
    arena:interactionCentroid [ 0.5785, 0.165, 0.735 ] ;
    arena:pickTarget :brown_box ;
    arena:placeTarget :blue_bin .

# 2. Past Light Cone: Physical Grounding Manifold
<< :brown_box arena:pastCausalAnchor :shelf_tier_2 >>
    arena:normalContact [ 0.0, 0.0, 1.0 ] ;
    arena:surfaceHeight "0.75"^^xsd:float ;
    arena:groundFloorRef "-0.795"^^xsd:float .

# 3. Future Light Cone: Kinematic & Perception Manifold
<< :g1_robot arena:futureCausalAffordance :task_seed_001 >>
    arena:reachEllipsoidMax "0.72"^^xsd:float ;
    arena:standoffDistance "0.85"^^xsd:float ;
    arena:facingAzimuth "0.0"^^xsd:float .

<< :persp_cam arena:futureCausalFrustum :task_seed_001 >>
    arena:cameraMode "over_the_shoulder" ;
    arena:standoffDistance "1.6"^^xsd:float ;
    arena:lineOfSightClearance true .
```

---

### 18.6 Cypher Causal Light Cone Query in Neo4j

```cypher
// Query: Verify Closed Causal Loop from Seed through Support, Robot, Camera, and Floor
MATCH (seed:TaskSeedEvent)-[:TARGETS]->(box:RigidObject)
MATCH (box)-[:PLACED_ON_SUB_SURFACE]->(tier:SurfaceAnchor)<-[:HAS_SUB_SURFACE]-(shelf:Furniture)
MATCH (shelf)-[:ATTACHED_TO_PRIM]->(zone:USDPrim)
MATCH (shelf)<-[:STANDS_AT_AFFORDANCE]-(robot:Embodiment)
MATCH (robot)-[:FRAMES_PERSPECTIVE_VIEW]->(cam:PerspectiveCamera)
MATCH (robot)-[:GROUNDED_ON]->(floor:USDPrim)
WHERE robot.standoff_distance <= 0.85 
  AND cam.has_clear_line_of_sight = true
RETURN seed.id, box.id, shelf.id, robot.id, cam.id, floor.id;
```










