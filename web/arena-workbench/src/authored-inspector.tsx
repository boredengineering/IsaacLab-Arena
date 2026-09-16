import { useRef, useState } from 'react';
import { ReviewedPositionEdit, type PositionEditBinding } from './reviewed-position-edit';
import type { Validation } from './editor-contracts';
import { PropertyTree } from './graph-explorer/property-tree';

export interface AuthoredInspectorProps {
  validation: Validation | null;
  /** Caller-owned current session/source/text identity; null validation withholds stale data. */
  bindingKey: string;
  onFocusSpecification: () => void;
  editing?: PositionEditBinding;
}

const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 512 && value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);
const collection = (value: unknown): value is Record<string, unknown>[] => Array.isArray(value) && value.length <= 500 && Array.from(value).every(record);

/** Check only the projection consumed here; never infer assets from graph labels or spec text. */
function usable(value: unknown): value is Validation {
  if (!record(value) || value.valid !== true || !collection(value.assets) || !collection(value.relations) || !collection(value.reified_relations) || !collection(value.tasks)) return false;
  const assets = value.assets;
  const ids = new Set<string>();
  for (const asset of assets) {
    if (!identifier(asset.id) || ids.has(asset.id) || typeof asset.role !== 'string' || !['embodiment', 'background', 'object', 'object_reference'].includes(asset.role) || !record(asset.properties) || asset.properties.id !== asset.id) return false;
    ids.add(asset.id);
    for (const key of ['registry_name', 'parent_id', 'prim_path']) {
      if ((asset[key] ?? null) !== (asset.properties[key] ?? null) || (asset[key] != null && !identifier(asset[key]))) return false;
    }
    if (asset.role !== 'object_reference' && !identifier(asset.registry_name)) return false;
    if (asset.role === 'object_reference' && !identifier(asset.parent_id)) return false;
  }
  if (!assets.every(asset => asset.parent_id == null || assets.some(parent => parent.id === asset.parent_id && (parent.role === 'background' || parent.role === 'object')))) return false;
  const endpoint = (id: unknown) => identifier(id) && ids.has(id);
  if (!value.relations.every(relation => identifier(relation.kind) && endpoint(relation.subject) && (relation.reference == null || endpoint(relation.reference)) && record(relation.params))) return false;
  const reifiers = new Set<string>();
  for (const relation of value.reified_relations) {
    if (!identifier(relation.reifier_id) || ids.has(relation.reifier_id) || reifiers.has(relation.reifier_id) || !identifier(relation.relation_type) || !endpoint(relation.source_id) || !endpoint(relation.target_id)) return false;
    reifiers.add(relation.reifier_id);
  }
  return value.tasks.every(task => identifier(task.kind) && record(task.params));
}
const UNAVAILABLE = '[Unavailable: invalid value or display limit]';

/** Bounded detached display copy; never stringify arbitrary values or walk cycles/accessors. */
function displayValue(value: unknown): unknown {
  let budget = 2000;
  const ancestors = new Set<object>();
  function visit(item: unknown, depth: number): unknown {
    if (--budget < 0 || depth > 16) return UNAVAILABLE;
    if (item === null || typeof item === 'boolean' || finite(item)) return item;
    if (typeof item === 'string') return item.length <= 4096 ? item : UNAVAILABLE;
    if (!Array.isArray(item) && !record(item)) return UNAVAILABLE;
    if (ancestors.has(item)) return UNAVAILABLE;
    const keys = Object.keys(item);
    if (keys.length > 500 || keys.some(key => key.length > 512) || (Array.isArray(item) && item.length !== keys.length)) return UNAVAILABLE;
    ancestors.add(item);
    const copy: Record<string, unknown> | unknown[] = Array.isArray(item) ? [] : Object.create(null);
    for (const key of keys) {
      const descriptor = Object.getOwnPropertyDescriptor(item, key);
      const child = descriptor && 'value' in descriptor ? visit(descriptor.value, depth + 1) : UNAVAILABLE;
      Object.defineProperty(copy, key, { value: child, enumerable: true, configurable: true, writable: true });
    }
    ancestors.delete(item);
    return copy;
  }
  return visit(value, 0);
}

function mentions(value: unknown, id: string): boolean {
  if (value === UNAVAILABLE) return false;
  if (value === id) return true;
  return value !== null && typeof value === 'object' && Object.values(value).some(child => mentions(child, id));
}
function vector(value: unknown, length: number) {
  return Array.isArray(value) && value.length === length && Array.from(value).every(finite) && (length !== 4 || value.some(component => component !== 0)) ? value.join(', ') : 'Unavailable';
}

export function AuthoredInspector(props: AuthoredInspectorProps) {
  return <BoundInspector key={props.bindingKey} {...props} />;
}

function BoundInspector({ validation, onFocusSpecification, editing }: AuthoredInspectorProps) {
  const valid = usable(validation);
  const [selection, setSelection] = useState({ validation, id: '' });
  const selectionEpoch = useRef(0);
  const renderedSelectionEpoch = selectionEpoch.current;
  // Render-time retirement withholds old details before commit, including A→B→A.
  if (selection.validation !== validation || (!valid && selection.id)) setSelection({ validation, id: '' });
  const selectedId = valid && selection.validation === validation ? selection.id : '';
  const asset = valid ? validation.assets.find(item => item.id === selectedId) : undefined;
  const properties = displayValue(asset?.properties);
  const params = record(properties) && record(properties.params) ? properties.params : {};
  const pose = record(params.initial_pose) ? params.initial_pose : {};
  const relations = asset && valid ? validation.relations.filter(item => item.subject === asset.id || item.reference === asset.id) : [];
  const reifiers = asset && valid ? validation.reified_relations.filter(item => item.source_id === asset.id || item.target_id === asset.id) : [];
  const checkedTasks = displayValue(valid ? validation.tasks : []);
  const tasks = asset && Array.isArray(checkedTasks) ? checkedTasks.filter(item => record(item) && mentions(item.params, asset.id)) : [];
  return <section className="authored-inspector" aria-label="Authored inspector" data-read-only={editing ? 'false' : 'true'}>
    <h3>Authored inspector</h3>
    <p className="authored-inspector-status" role="status">{valid ? 'Schema-valid · not runtime-validated' : 'Authored data unavailable. Validate the current specification; malformed, ambiguous or oversized projections are withheld.'}</p>
    <p className="authored-inspector-readonly">{editing ? 'Selected supported root XYZ coordinates can be proposed, validated and explicitly applied after source-diff review. Other properties remain read-only; schema validity is not runtime validity.' : 'Read-only. Structured editing is unsupported: no verified source-field mapping; edit and validate the raw specification instead.'}</p>
    <button type="button" onClick={onFocusSpecification}>Focus raw specification</button>
    {valid && <label>Authored asset<select aria-label="Authored asset" value={selectedId} onChange={event => { selectionEpoch.current++; setSelection({ validation, id: event.target.value }); }}>
      <option value="">Select an asset by ID</option>
      {validation.assets.map(item => <option key={item.id} value={item.id}>{item.id} · {item.role}</option>)}
    </select></label>}
    {asset && <section className="authored-inspector-selection" aria-label="Selected authored asset">
      {editing && <ReviewedPositionEdit binding={{...editing,
        optionsKey: `${editing.optionsKey}:selection:${renderedSelectionEpoch}`,
        isCurrent: () => selectionEpoch.current === renderedSelectionEpoch && editing.isCurrent(),
      }} validation={validation} selectedId={asset.id} />}
      <dl className="authored-inspector-fields">
        <dt>Asset ID</dt><dd>{asset.id}</dd>
        <dt>Role</dt><dd>{asset.role}</dd>
        <dt>Registry</dt><dd>{asset.registry_name ?? 'Not authored'}</dd>
        <dt>Reference parent ID</dt><dd>{asset.parent_id ?? 'Not authored'}</dd>
        <dt>Prim path</dt><dd>{asset.prim_path ?? 'Not authored'}</dd>
        <dt>Initial position · XYZ (m) · environment frame</dt><dd>{vector(pose.position_xyz, 3)}</dd>
        <dt>Initial rotation · quaternion XYZW</dt><dd>{vector(pose.rotation_xyzw, 4)}</dd>
        <dt>Authored scale</dt><dd>{finite(params.scale) ? String(params.scale) : vector(params.scale, 3)}</dd>
      </dl>
      <p>Authored constructor values only, not a resolved world or runtime pose. Registry defaults and effective scale are unknown; missing values are not zero or identity.</p>
      {asset.parent_id && <p>Projected containment relationship. Parent-relative transforms and USD prim transforms are not resolved here; Arena composes the referenced prim pose with the parent pose when present. Prim path not checked against USD.</p>}
      {relations.length > 0 && <p className="authored-inspector-warning">Relation-constrained placement may override or ignore initial_pose. No placement, collision, physics or pixel-to-meter inference is performed.</p>}
      <section className="authored-inspector-properties" aria-label="Raw authored properties">
        <h4>Raw authored properties</h4><PropertyTree key={asset.id} value={properties} />
      </section>
      <section className="authored-inspector-context" aria-label="Relevant authored relations">
        <h4>Relevant authored relations</h4><PropertyTree key={asset.id} value={displayValue(relations)} />
      </section>
      <section className="authored-inspector-context" aria-label="Relevant authored reifiers">
        <h4>Relevant authored reifiers</h4><PropertyTree key={asset.id} value={displayValue(reifiers)} />
      </section>
      <section className="authored-inspector-context" aria-label="Task parameters mentioning this ID">
        <h4>Task parameters mentioning this ID</h4>
        <p>Exact string match in parameters; task parameter semantics are not inferred.</p>
        <PropertyTree key={asset.id} value={tasks} />
      </section>
      <p className="authored-inspector-limits">Display bounds: 500 entries per collection, 512 characters per identifier/key, 16 nested levels, a 2,000-value inspection budget per tree (unavailable placeholders may exceed this count) and 4,096 characters per value. Invalid or excess values are unavailable; task matches can be incomplete. Inspect the raw specification for full content.</p>
    </section>}
  </section>;
}
