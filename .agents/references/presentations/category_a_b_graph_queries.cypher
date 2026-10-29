// Read-only presentation queries. Run one numbered block at a time in Neo4j Browser.
// These show Neo4j's explicit reification projection, not native RDF-star triple terms.
// Names, labels, properties and relationship directions verified on the live deployment.

// === 1_discover_droid_apple ===
MATCH (g:EnvironmentGraph)
WHERE g.name CONTAINS 'apple' AND g.name CONTAINS 'droid'
RETURN g.name AS graph_name, g.task_description AS task_description
ORDER BY graph_name;

// === 2_scene_overview ===
MATCH p=(g:EnvironmentGraph {name: 'franka_droid_apple_to_bowl_maple_table'})-[*1..2]-(n)
WHERE all(member IN nodes(p) WHERE member = g OR member.env_name = g.name)
RETURN p
LIMIT 100;

// === 3_reified_statements ===
MATCH membership=(g:EnvironmentGraph {name: 'franka_droid_apple_to_bowl_maple_table'})
                 -[:HAS_REIFIER]->(rf:ReifiedRelation)
MATCH statement=(subject)<-[:REIFIES_SUBJECT]-(rf)-[:REIFIES_OBJECT]->(object)
OPTIONAL MATCH direct_fact=(subject)-[fact]->(object)
WHERE type(fact) = rf.relation_type
RETURN membership, statement, direct_fact;

// === 4_apple_placement_closeup ===
MATCH membership=(g:EnvironmentGraph {name: 'franka_droid_apple_to_bowl_maple_table'})
                 -[:HAS_REIFIER]->(rf:ReifiedRelation {reifier_id: 'reifier_apple_table'})
MATCH statement=(apple)<-[:REIFIES_SUBJECT]-(rf)-[:REIFIES_OBJECT]->(table)
MATCH direct_fact=(apple)-[:PLACED_ON]->(table)
RETURN membership, statement, direct_fact;

// === 5_reifier_annotations ===
MATCH (g:EnvironmentGraph {name: 'franka_droid_apple_to_bowl_maple_table'})
      -[:HAS_REIFIER]->(rf:ReifiedRelation)
MATCH (rf)-[:REIFIES_SUBJECT]->(subject), (rf)-[:REIFIES_OBJECT]->(object)
RETURN rf.reifier_id AS statement_id, rf.relation_type AS predicate,
       subject.id AS subject, object.id AS object,
       rf.surface_anchor AS surface_anchor,
       rf.required_headroom AS required_headroom,
       rf.required_friction AS required_friction,
       rf.delta_x_min AS delta_x_min, rf.delta_x_max AS delta_x_max,
       rf.delta_y_min AS delta_y_min, rf.delta_y_max AS delta_y_max,
       rf.delta_z_nominal AS delta_z_nominal,
       rf.prior_entropy AS prior_entropy, rf.posterior_entropy AS posterior_entropy,
       rf.evidence_sources AS evidence_sources
ORDER BY statement_id;

// === 6_direct_placement_properties ===
MATCH (g:EnvironmentGraph {name: 'franka_droid_apple_to_bowl_maple_table'})
      -[:CONTAINS_OBJECT]->(subject)
MATCH (subject)-[placement:PLACED_ON]->(support)
WHERE support.env_name = g.name
RETURN subject.id AS subject, support.id AS support,
       placement.surface_anchor AS surface_anchor,
       placement.clearance AS clearance, placement.nominal_height AS nominal_height,
       placement.raw_params AS raw_params;

// === 7_current_run_provenance ===
MATCH p=(ev:EvaluationRun {id: 'eval_run_1788928970'})-[:USED_POLICY]->(policy:Policy)
OPTIONAL MATCH environment_link=(ev)-[:EVALUATED_GRAPH]->(g:EnvironmentGraph)
RETURN p, environment_link;

// === 8_b1_scene_overview ===
MATCH p=(g:EnvironmentGraph {name: 'franka_droid_tomato_soup_to_bin'})-[*1..2]-(n)
WHERE all(member IN nodes(p) WHERE member = g OR member.env_name = g.name)
RETURN p
LIMIT 100;

// === 9_b1_reified_statements ===
MATCH membership=(g:EnvironmentGraph {name: 'franka_droid_tomato_soup_to_bin'})
                 -[:HAS_REIFIER]->(rf:ReifiedRelation)
MATCH statement=(subject)<-[:REIFIES_SUBJECT]-(rf)-[:REIFIES_OBJECT]->(object)
OPTIONAL MATCH direct_fact=(subject)-[fact]->(object)
WHERE type(fact) = rf.relation_type
RETURN membership, statement, direct_fact;

// === 10_b1_can_statement_closeup ===
MATCH membership=(g:EnvironmentGraph {name: 'franka_droid_tomato_soup_to_bin'})
                 -[:HAS_REIFIER]->(rf:ReifiedRelation {reifier_id: 'reifier_tomato_soup_can_maple_table'})
MATCH statement=(can)<-[:REIFIES_SUBJECT]-(rf)-[:REIFIES_OBJECT]->(table)
MATCH direct_fact=(can)-[:PLACED_ON]->(table)
RETURN membership, statement, direct_fact;

// === 11_b1_statement_annotations ===
MATCH (g:EnvironmentGraph {name: 'franka_droid_tomato_soup_to_bin'})
      -[:HAS_REIFIER]->(rf:ReifiedRelation)
MATCH (rf)-[:REIFIES_SUBJECT]->(subject), (rf)-[:REIFIES_OBJECT]->(object)
RETURN rf.reifier_id AS statement_id, subject.id AS subject,
       rf.relation_type AS predicate, object.id AS object,
       rf.surface_anchor AS surface_anchor,
       rf.required_headroom AS required_headroom, rf.required_friction AS required_friction,
       rf.kinematic_manifold AS kinematic_manifold,
       rf.prior_entropy AS prior_entropy, rf.posterior_entropy AS posterior_entropy,
       rf.evidence_sources AS evidence_sources
ORDER BY statement_id;

// === 12_b1_recorded_evaluations ===
MATCH policy_use=(ev:EvaluationRun)-[:USED_POLICY]->(policy:Policy)
WHERE ev.id IN ['eval_run_1788238238', 'eval_run_1788238722', 'eval_run_1788279490',
               'eval_run_1788281565', 'eval_run_1788284877', 'eval_run_1788287246',
               'eval_run_1788289371']
OPTIONAL MATCH environment_link=(ev)-[:EVALUATED_GRAPH]->(g:EnvironmentGraph)
RETURN policy_use, environment_link;

// === 13_b4_scene_overview ===
MATCH p=(g:EnvironmentGraph {name: 'franka_droid_spam_can_to_grey_bin'})-[*1..2]-(n)
WHERE all(member IN nodes(p) WHERE member = g OR member.env_name = g.name)
RETURN p
LIMIT 100;

// === 14_b4_support_statements_closeup ===
MATCH membership=(g:EnvironmentGraph {name: 'franka_droid_spam_can_to_grey_bin'})
                 -[:CONTAINS_OBJECT]->(item)
WHERE item.id IN ['spam_can', 'grey_bin']
MATCH support_statement=(item)-[:PLACED_ON]->(table)
WHERE table.env_name = g.name
RETURN membership, support_statement;

// === 15_b4_reification_gap ===
MATCH (g:EnvironmentGraph {name: 'franka_droid_spam_can_to_grey_bin'})
OPTIONAL MATCH (rf:ReifiedRelation {env_name: g.name})
RETURN g.name AS graph_name, count(rf) AS reifier_count,
       collect(rf.reifier_id) AS statement_ids;

// === 16_b4_edge_annotations ===
MATCH (g:EnvironmentGraph {name: 'franka_droid_spam_can_to_grey_bin'})
      -[:CONTAINS_OBJECT]->(item)
MATCH (item)-[placement:PLACED_ON]->(table)
WHERE table.env_name = g.name
RETURN item.id AS subject, item.registry_name AS asset,
       type(placement) AS predicate, table.id AS object,
       placement.surface_anchor AS surface_anchor,
       placement.clearance AS clearance, placement.nominal_height AS nominal_height,
       placement.raw_params AS source_parameters
ORDER BY subject;

// === 17_b4_recorded_evaluations ===
MATCH policy_use=(ev:EvaluationRun)-[:USED_POLICY]->(policy:Policy)
WHERE ev.id IN ['eval_run_1788290861', 'eval_run_1788292259', 'eval_run_1788292607']
OPTIONAL MATCH environment_link=(ev)-[:EVALUATED_GRAPH]->(g:EnvironmentGraph)
RETURN policy_use, environment_link;
