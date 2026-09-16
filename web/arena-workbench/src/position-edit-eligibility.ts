import { yamlLanguage } from '@codemirror/lang-yaml';
import type { Validation } from './editor-contracts';
import { proposeRootPositionEdit } from './authored-yaml-edit';

type Eligibility = { ok: true; role: 'background'; position: number[] } | { ok: false; reason: string };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
type Node = ReturnType<typeof yamlLanguage.parser.parse>['topNode'];
const children = (node: Node) => { const result: Node[] = []; for (let n = node.firstChild; n; n = n.nextSibling) if (n.name !== 'Comment') result.push(n); return result; };
const scalar = (n: Node | undefined, text: string) => n ? text.slice(n.from, n.to).replace(/^(['"])(.*)\1$/, '$2') : undefined;
function members(n: Node | undefined, text: string): Map<string, Node> {
  return new Map(n?.getChildren('Pair').map(pair => [scalar(pair.getChild('Key')?.firstChild ?? undefined, text) ?? '', children(pair)[2]]) ?? []);
}
function numbers(n: Node | undefined, text: string): number[] {
  if (!n || !['BlockSequence', 'FlowSequence'].includes(n.name)) return [];
  return n.getChildren('Item').map(item => {
    const leaf = children(item)[0]; const s = leaf && text.slice(leaf.from, leaf.to);
    return s && leaf.name === 'Literal' && /^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(s) ? Number(s) : NaN;
  });
}
/**
 * Descriptor v1: ONLY background/table, explicit full root pose, no additional
 * constructor params, no incident relations/reifiers/reference children.
 * Static source characterization, not runtime/GPU validation:
 * assets/background_library.py Table -> LibraryBackground pops initial_pose;
 * environment_spec/arena_env_graph_conversion_utils.py:161-169 parses Pose;
 * assets/background.py -> Object._add_initial_pose_to_cfg writes init_state.pos.
 * scene/scene.py get_objects_with_relations and relation_solver_interface.py
 * operate on relation-bearing assets; exclude ALL incident constraints here.
 * object_min_z is global and does NOT move with this background (background.py).
 * No registry discovery/constructor execution or generalized support inference.
 */
export function positionEditEligibility(draft: string, validation: Validation | null, id: string): Eligibility {
  const deny = (reason: string): Eligibility => ({ ok: false, reason });
  if (!validation || validation.valid !== true || !Array.isArray(validation.errors) || validation.errors.length || !Array.isArray(validation.assets) || !Array.isArray(validation.relations) || !Array.isArray(validation.reified_relations)) return deny('Current successful schema validation required.');
  if (typeof validation.canonical_hash !== 'string' || !/^[a-f0-9]{64}$/.test(validation.canonical_hash) || !validation.assets.every(record)) return deny('Malformed validation projection.');
  const matches = validation.assets.filter(asset => asset?.id === id);
  if (matches.length !== 1) return deny('Unique validated asset identity required.');
  const asset = matches[0];
  if (asset.role !== 'background' || asset.registry_name !== 'table') return deny('Supported descriptor v1: background / table only; other registries, embodiments, objects and references are read-only.');
  if (!record(asset.properties) || asset.properties.id !== id || asset.properties.registry_name !== asset.registry_name || asset.parent_id != null || asset.prim_path != null) return deny('Inconsistent asset projection.');
  if (validation.relations.some(r => !record(r) || r.subject === id || r.reference === id) || validation.reified_relations.some(r => !record(r) || r.source_id === id || r.target_id === id) || validation.assets.some(a => a.parent_id === id)) return deny('Relation-constrained or reference-parent placement is unsupported.');
  const params = asset.properties.params;
  const pose = record(params) ? params.initial_pose : null;
  if (!record(params) || Object.keys(params).some(k => k !== 'initial_pose') || !record(pose) || Object.keys(pose).some(k => !['position_xyz', 'rotation_xyzw'].includes(k))) return deny('Additional/defaulted constructor parameters and scale are unsupported.');
  const position = pose.position_xyz;
  if (!Array.isArray(position) || position.length !== 3 || !position.every(v => typeof v === 'number' && Number.isFinite(v))) return deny('Explicit finite XYZ required.');
  // The existing bounded proposer proves syntax, unique IDs and numeric root CST
  // provenance. Its alternate value is never applied or sent to the API.
  for (const axis of [0, 1, 2] as const) {
    const proof = proposeRootPositionEdit({draft, role: 'background', nodeId: id, axis, value: position[axis] === 0 ? 1 : 0});
    if (!proof.ok) return deny(`Root CST mapping unavailable: ${proof.reason}.`);
    if (proof.before !== position[axis]) return deny('Root position differs from the current projection.');
  }
  const top = yamlLanguage.parser.parse(draft).topNode;
  const root = top.getChild('Document');
  const rootFields = members(root ? children(root)[0] : undefined, draft);
  const external = rootFields.get('external_yaml');
  if (external && (!['Literal', 'QuotedLiteral'].includes(external.name) || !scalar(external, draft)?.trim())) return deny('Only scalar external_yaml composition is supported; never create overrides.');
  const bg = rootFields.get('background');
  const fields = members(bg, draft);
  if (scalar(fields.get('registry_name'), draft) !== 'table' || [...fields.keys()].some(k => !['id', 'registry_name', 'params'].includes(k))) return deny('Root registry/constructor provenance is unsupported.');
  const rawParams = members(fields.get('params'), draft);
  const rawPose = members(rawParams.get('initial_pose'), draft);
  if ([...rawParams.keys()].some(k => k !== 'initial_pose') || [...rawPose.keys()].some(k => !['position_xyz', 'rotation_xyzw'].includes(k))) return deny('Additional root constructor parameters are unsupported.');
  const rotation = numbers(rawPose.get('rotation_xyzw'), draft);
  const projectedRotation = pose.rotation_xyzw;
  // Deliberately narrower than a tolerance policy: only an explicitly authored
  // identity quaternion is admitted. Quaternion edits/normalization are not offered.
  if (rotation.length !== 4 || !rotation.every((v, i) => v === (i === 3 ? 1 : 0)) || !Array.isArray(projectedRotation) || projectedRotation.length !== 4 || rotation.some((v, i) => v !== projectedRotation[i])) return deny('Descriptor v1 requires explicit identity XYZW [0, 0, 0, 1]; rotation editing is unsupported.');
  return { ok: true, role: 'background', position: [...position] };
}
