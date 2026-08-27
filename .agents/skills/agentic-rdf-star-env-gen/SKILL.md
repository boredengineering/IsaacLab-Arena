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
