---
name: agentic-rdf-star-env-gen
description: Semantic Web and Labeled Property Graph (LPG) pipeline for IsaacLab-Arena. Use when asked to generate, validate, lower, or audit robot environment scene graphs using RDF-star, JSON-LD, SHACL constraints, Cypher, and W3C PROV-O.
---

# Agentic RDF-star, LPG & PROV-O Environment Generation Skill

This skill guides the creation, semantic validation, LPG querying, and lowering of robot simulation scenes in **IsaacLab-Arena** using **RDF-star ($\text{RDF}^*$)**, **W3C SHACL**, **Labeled Property Graphs (Cypher)**, and **W3C PROV-O**.

## 1. Quick Start: Validate & Lower an RDF Scene Graph

```python
import rdflib
from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph
from isaaclab_arena.agentic_environment_generation.rdf_lowering import lower_rdf_graph_to_spec

# 1. Parse Turtle-star scene
g = rdflib.Graph()
g.parse("path/to/scene.ttl", format="turtle")

# 2. Validate against SHACL constraints (checks terrain, reachability, WBC threads)
conforms, report = validate_rdf_environment_graph(g)
if not conforms:
    print(f"SHACL Validation Violations:\n{report}")
else:
    # 3. Lower to executable Pydantic ArenaEnvGraphSpec
    spec = lower_rdf_graph_to_spec(g)
    print(f"Successfully compiled spec: {spec.env_name}")
```

---

## 2. Core Ontologies & Schemas in the Repo

- **JSON-LD Context**: `isaaclab_arena/agentic_environment_generation/ontology/arena_context.jsonld`
- **Turtle-star Schema**: `isaaclab_arena/agentic_environment_generation/ontology/arena_schema.ttl`
- **SHACL Shapes**: `isaaclab_arena/agentic_environment_generation/ontology/arena_constraints.shacl.ttl`
- **Lowering Compiler**: `isaaclab_arena/agentic_environment_generation/rdf_lowering.py`
- **SHACL Validator**: `isaaclab_arena/agentic_environment_generation/rdf_validation.py`

---

## 3. Labeled Property Graph (Cypher) Integration

When interacting with a local or remote Neo4j database:

```cypher
// Query scene entities and reified relationship properties
MATCH (obj:RigidObject)-[rel:PLACED_ON]->(fixture:Fixture)
RETURN obj.id AS object_id,
       fixture.id AS fixture_id,
       rel.surface_anchor AS anchor,
       rel.nominal_height AS height,
       rel.bound_x AS bounds_x;
```

---

## 4. PROV-O Execution Telemetry Recording

After executing a simulation rollout with `policy_runner.py`:
```turtle
:eval_run_01 a arena:EvaluationRun, prov:Entity ;
    prov:wasGeneratedBy :activity_gr00t_eval ;
    arena:evaluatedGraph :scene_g1_001 ;
    arena:taskSuccess "true"^^xsd:boolean ;
    arena:meanZeroMQLatencyMs "18.2"^^xsd:float .
```

---

## 5. DCRG Recurrent Active Inference & Self-Healing Loopback

A static Directed Acyclic Graph (D-DAG) terminates at evaluation sinks (`EvaluationRun`, out-degree = 0). To enable closed-loop active inference, the system transitions to a **Directed Cyclic Stochastic Graph (DCRG)** by injecting recurrent loopback edges:

```cypher
// 1. Backpropagate empirical evaluation likelihood into reified relation factor
MATCH (ev:EvaluationRun {id: $eval_id}), (rf:ReifiedRelation {reifier_id: $reifier_id})
MERGE (ev)-[f:FEEDBACK_MUTATION]->(rf)
SET f.cartesian_dx = $dx,
    f.cartesian_dy = $dy,
    f.cartesian_dz = $dz,
    f.contact_force = $contact_force,
    f.iteration = $iteration,
    f.timestamp = datetime();

// 2. Reified relation proposes continuous relaxation for the next iteration
MATCH (rf:ReifiedRelation {reifier_id: $reifier_id}), (next_e:EnvironmentGraph {name: $next_env})
MERGE (rf)-[m:PROPOSES_RELAXATION]->(next_e)
SET m.delta_pose = $delta_pose,
    m.confidence = $confidence;
```

---

## 6. Stochastic Factor Graph Relaxation vs. The Deterministic Schema Trap

A rigid deterministic schema traps the agent in a finite discrete vocabulary, preventing it from discovering continuous physical contact basins (such as equatorial caging vs. fingertip pinching).

Use stochastic continuous relaxation:
```python
from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
    relax_spec_spatial_factor_graph,
)
from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
    PolicyProfile,
    DistributionShift,
)

# Perturb continuous poses guided by reach trace likelihoods rather than discrete grid slots
relaxed_spec = relax_spec_spatial_factor_graph(
    spec=current_spec,
    measured_reach_delta={"dx": -0.0006, "dy": 0.0122, "dz": -0.025},
    temperature=0.15,
)
```

---

## 7. Guardrails & Physical Invariant Rules

1. **Digital Twin Fidelity**:
   Never resolve grasp failures by inflating physics friction parameters (`static_friction`, `dynamic_friction`). In SPARQL queries, this is formally blocked by:
   ```sparql
   FILTER NOT EXISTS { ?remediation arena:invalidatedBy arena:sim_to_real_gap . }
   ```
2. **Coordinate Centroid Grounding**:
   Always audit pelvis-relative offsets $(\Delta X, \Delta Y, \Delta Z)$ against demonstration corpus `TrainingInvariant`s before running rollouts.
3. **Equatorial Caging Over Crown Pinching**:
   Ensure the approach trajectory brings the hand to the sphere equator ($dZ \approx 0\text{ m}$ relative to object center) rather than pinching tapering crowns.
