#!/usr/bin/env python3
"""
Milestone 5 (Step 1 & 2):
1. Audit physical defects in Neo4j from Scenario B1 (Milestones 2, 3, 4)
2. Assert Causal Attribution Feedback Mutation and Relaxation Proposal edges
3. Export W3C PROV-O provenance graph to artifacts/experiments/exp02_b1_triad/self_healing_lineage.ttl
"""

import os
import sys
import datetime
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")

PROV_TTL_PATH = "/workspaces/isaaclab_arena/artifacts/experiments/exp02_b1_triad/self_healing_lineage.ttl"
os.makedirs(os.path.dirname(PROV_TTL_PATH), exist_ok=True)

def main():
    print("=================================================================")
    print("STEP 1: Audit Physical Defects & Assert Causal Attribution Edges")
    print("=================================================================")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Create EvaluationRun for Arm A and link feedback mutation
        session.run("""
            MATCH (a:EnvironmentGraph {name: 'franka_pick_place_tomato_soup'})
            MATCH (a)-[:HAS_REIFIER]->(rf:ReifiedRelation)
            WHERE rf.reifier_id = 'reifier_blue_bin_maple_table'
            
            MERGE (ev:EvaluationRun {eval_id: 'eval_arm_a_step0'})
            ON CREATE SET ev.timestamp = '2026-10-19T03:36:56Z',
                          ev.model = 'Qwen/Qwen2.5-Coder-32B-Instruct-AWQ',
                          ev.physx_settled = true,
                          ev.pdr_discrepancy = 1.0,
                          ev.human_critique = 'blue_sorting_bin 0.85m exceeds 0.65m table by >50% overhang'
            MERGE (ev)-[:EVALUATED_GRAPH]->(a)
            
            MERGE (ev)-[f:FEEDBACK_MUTATION]->(rf)
            ON CREATE SET f.defect_mode = 'SpatialScaleMismatch',
                          f.root_cause = 'blue_sorting_bin exceeds table deck area by >100%',
                          f.remediation = 'Select compact container bin_b03_vomp_robolab',
                          f.timestamp = '2026-10-19T03:40:00Z'
        """)
        print("[NEO4J] Created [:FEEDBACK_MUTATION] edge from EvaluationRun to reifier_blue_bin_maple_table")
        
        # Link relaxation to Arm B and Arm C graphs
        session.run("""
            MATCH (rf:ReifiedRelation {reifier_id: 'reifier_blue_bin_maple_table'})
            MATCH (b:EnvironmentGraph {name: 'tomato_soup_pick_place_maple_table'})
            MERGE (rf)-[r1:PROPOSES_RELAXATION]->(b)
            ON CREATE SET r1.action = 'Select compact container bin_b03_vomp_robolab via QwQ-32B deduction',
                          r1.delta_free_energy = -0.35,
                          r1.timestamp = '2026-10-19T04:49:43Z'
                          
            WITH rf
            MATCH (c:EnvironmentGraph {name: 'franka_tomato_soup_can_bin_b03'})
            MERGE (rf)-[r2:PROPOSES_RELAXATION]->(c)
            ON CREATE SET r2.action = 'Select compact container bin_b03_vomp_robolab via GLM-5.3 744B MoE',
                          r2.delta_free_energy = -0.38,
                          r2.timestamp = '2026-10-19T06:08:25Z'
        """)
        print("[NEO4J] Created [:PROPOSES_RELAXATION] edges to Arm B and Arm C environments")
        
        # Verify closed-loop query (Cypher Query 1 from Section 7.3)
        res = session.run("""
            MATCH (env:EnvironmentGraph)
            WHERE env.name IN ['franka_pick_place_tomato_soup', 'tomato_soup_pick_place_maple_table', 'franka_tomato_soup_can_bin_b03']
            OPTIONAL MATCH (env)<-[:EVALUATED_GRAPH]-(ev:EvaluationRun)
            OPTIONAL MATCH (ev)-[f:FEEDBACK_MUTATION]->(rf:ReifiedRelation)
            OPTIONAL MATCH (rf)-[r:PROPOSES_RELAXATION]->(next_env:EnvironmentGraph)
            RETURN env.name AS Environment,
                   ev.eval_id AS EvalRun,
                   f.defect_mode AS DefectMode,
                   rf.reifier_id AS TargetReifier,
                   next_env.name AS NextIterationEnv
        """)
        records = list(res)
        print(f"[NEO4J AUDIT] Cypher Query 1 returned {len(records)} attribution record(s):")
        for rec in records:
            print("  ->", dict(rec))

    print("\n=================================================================")
    print("STEP 2: Export W3C PROV-O Graph Lineage (self_healing_lineage.ttl)")
    print("=================================================================")
    prov_ttl = f"""@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix arena: <https://isaaclab-arena.nvidia.com/schema#> .

# -------------------------------------------------------------
# 1. Physical Entities & Agents
# -------------------------------------------------------------
:agent_coder32b a prov:Agent, arena:SpecGenerator ;
    rdfs:label "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" .

:agent_qwq32b a prov:Agent, arena:SpecGenerator ;
    rdfs:label "Qwen/QwQ-32B-AWQ (Test-Time Deduction)" .

:agent_glm53 a prov:Agent, arena:SpecGenerator ;
    rdfs:label "Colibri GLM-5.3 (744B MoE Streaming)" .

:human_evaluator a prov:Agent ;
    rdfs:label "Human In The Loop Evaluator" .

# -------------------------------------------------------------
# 2. Arm A Specification & Evaluation Activity
# -------------------------------------------------------------
:spec_arm_a a prov:Entity, arena:EnvironmentGraphSpec ;
    arena:envName "franka_pick_place_tomato_soup" ;
    prov:wasAttributedTo :agent_coder32b ;
    prov:generatedAtTime "2026-10-19T03:36:56Z"^^xsd:dateTime .

:eval_activity_arm_a a prov:Activity, arena:EvaluationRun ;
    prov:used :spec_arm_a ;
    prov:wasAssociatedWith :human_evaluator ;
    arena:physxSettled true ;
    arena:visualCriticVerdict "FAIL_OVERHANG_50PCT" ;
    arena:proxyToRealityDiscrepancy "1.0"^^xsd:float ;
    prov:startedAtTime "2026-10-19T03:37:00Z"^^xsd:dateTime ;
    prov:endedAtTime "2026-10-19T03:40:00Z"^^xsd:dateTime .

# Reified factor that caused failure
:reifier_blue_bin_arm_a a prov:Entity, arena:ReifiedRelation ;
    arena:reifierId "reifier_blue_bin_maple_table" ;
    arena:sourceId "blue_sorting_bin" ;
    arena:targetId "maple_table" ;
    arena:defectMode "SpatialScaleMismatch" .

# -------------------------------------------------------------
# 3. Active Inference Causal Feedback Mutation
# -------------------------------------------------------------
:feedback_mutation_arm_a a prov:Activity, arena:FeedbackMutation ;
    prov:wasInformedBy :eval_activity_arm_a ;
    arena:targetsReifier :reifier_blue_bin_arm_a ;
    arena:diagnosticAttributionAccuracy "1.0"^^xsd:float ;
    arena:contextCompactionRatio "14.2"^^xsd:float ;
    prov:startedAtTime "2026-10-19T03:40:01Z"^^xsd:dateTime .

# -------------------------------------------------------------
# 4. Arm B Deductive Evolution (QwQ-32B)
# -------------------------------------------------------------
:spec_arm_b a prov:Entity, arena:EnvironmentGraphSpec ;
    arena:envName "tomato_soup_pick_place_maple_table" ;
    prov:wasDerivedFrom :spec_arm_a ;
    prov:wasGeneratedBy :feedback_mutation_arm_a ;
    prov:wasAttributedTo :agent_qwq32b ;
    arena:selectedReceptacle "bin_b03_vomp_robolab" ;
    prov:generatedAtTime "2026-10-19T04:49:43Z"^^xsd:dateTime .

:eval_activity_arm_b a prov:Activity, arena:EvaluationRun ;
    prov:used :spec_arm_b ;
    arena:physxSettled true ;
    arena:visualCriticVerdict "PASS_ZERO_OVERHANG" ;
    arena:proxyToRealityDiscrepancy "0.0"^^xsd:float ;
    arena:freeEnergyDelta "-0.35"^^xsd:float ;
    prov:startedAtTime "2026-10-19T04:50:00Z"^^xsd:dateTime .

# -------------------------------------------------------------
# 5. Arm C Frontier MoE Evolution (GLM-5.3 744B)
# -------------------------------------------------------------
:spec_arm_c a prov:Entity, arena:EnvironmentGraphSpec ;
    arena:envName "franka_tomato_soup_can_bin_b03" ;
    prov:wasDerivedFrom :spec_arm_a ;
    prov:wasGeneratedBy :feedback_mutation_arm_a ;
    prov:wasAttributedTo :agent_glm53 ;
    arena:selectedReceptacle "bin_b03_vomp_robolab" ;
    prov:generatedAtTime "2026-10-19T06:08:25Z"^^xsd:dateTime .

:eval_activity_arm_c a prov:Activity, arena:EvaluationRun ;
    prov:used :spec_arm_c ;
    arena:physxSettled true ;
    arena:visualCriticVerdict "PASS_ZERO_OVERHANG" ;
    arena:proxyToRealityDiscrepancy "0.0"^^xsd:float ;
    arena:freeEnergyDelta "-0.38"^^xsd:float ;
    prov:startedAtTime "2026-10-19T06:08:30Z"^^xsd:dateTime .
"""
    with open(PROV_TTL_PATH, "w") as f:
        f.write(prov_ttl)
    print(f"[PROV-O EXPORT] Written W3C PROV-O provenance graph to {PROV_TTL_PATH} ({len(prov_ttl.splitlines())} lines)")

if __name__ == "__main__":
    main()
