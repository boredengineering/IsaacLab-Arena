"""Build a historical preview index using JSON and AST only; never import Arena."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / '.agents/references/plans/dashboard_cli_workflow_parity/workflow-parity-ledger.json'
OUTPUT = ROOT / 'web/arena-workbench/src/preview/coverage-data.json'


def build():
    ledger = json.loads(LEDGER.read_text())
    entries = ledger['entries']
    ids = [entry['id'] for entry in entries]
    assert len(ids) == len(set(ids)) == 394
    caps = sorted({cap for entry in entries for cap in entry['capability_ids']})
    assert caps == [f'C{number:02}' for number in range(1, 22)]
    inventory_ids = []
    for inventory in ledger['source_inventories']:
        enumerated = inventory['enumerated_source_ids']
        assert len(enumerated) == len(set(enumerated)) == inventory['ledger_count']
        inventory_ids.extend(enumerated)
    assert len(inventory_ids) == len(set(inventory_ids)) == 394
    assert set(inventory_ids) == set(ids)
    # Preserve every original entry field, including historical source references.
    source_path = 'isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py'
    text = (ROOT / source_path).read_text()
    tree = ast.parse(text)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'add_agentic_env_gen_runner_cli_args')
    deltas = []
    known = {option for entry in entries if entry.get('surface') == 'generation' for option in entry.get('option_strings', [])}
    for loop in ast.walk(function):
        if not isinstance(loop, ast.For) or not isinstance(loop.target, ast.Name):
            continue
        try:
            names = ast.literal_eval(loop.iter)
        except (ValueError, TypeError):
            continue
        for call in ast.walk(loop):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != 'add_argument' or not call.args:
                continue
            arg = call.args[0]
            if not isinstance(arg, ast.JoinedStr):
                continue
            assert len(arg.values) == 2 and isinstance(arg.values[0], ast.Constant)
            assert isinstance(arg.values[1], ast.FormattedValue) and isinstance(arg.values[1].value, ast.Name)
            assert arg.values[1].value.id == loop.target.id
            for name in names:
                option = arg.values[0].value + name
                if option in known or not option.startswith('--managed_'):
                    continue
                deltas.append({'option': option, 'canonical_ledger_id': None, 'origin': 'source_delta_requires_reconciliation', 'source': {'path': source_path, 'start_line': call.lineno, 'end_line': call.end_lineno}, 'default': {'kind': 'literal', 'value': None, 'source_expression': 'None'}, 'parser_kwargs': {kw.arg: ast.unparse(kw.value) for kw in call.keywords}, 'profile': 'not_assigned_pending_reconciliation', 'precedence': 'Not established by AST declaration; consumer audit required.', 'capability_ids': [], 'disposition': 'unresolved audit', 'screen_groups': ['settings', 'library', 'graph'], 'explanation': 'Managed CLI source addition, not a canonical historical entry. Transport, operation and publication identity are operator/private bindings; no raw browser field or runtime-support claim.'})
    assert len(deltas) == len({item['option'] for item in deltas})
    result = {'revision': 'historical-ledger-schema-1', 'ledger_sha256': hashlib.sha256(LEDGER.read_bytes()).hexdigest(), 'historical_counts': ledger['counts'], 'capability_ids': caps, 'source_manifest': ledger['source_manifest'], 'source_inventories': ledger['source_inventories'], 'profile_semantics': ledger['profile_semantics'], 'coverage_limitations': ledger['coverage_limitations'], 'remaining_audit_gaps': ledger['remaining_audit_gaps'], 'entries': entries, 'source_delta': deltas, 'delta_source_sha256': hashlib.sha256(text.encode()).hexdigest(), 'delta_method': 'Static AST expansion of literal managed-option loop only; no parser execution, imports, live catalogues or whole-current-parser census.'}
    OUTPUT.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'historical_entries': len(entries), 'unique_ids': len(set(ids)), 'capabilities': len(caps), 'source_delta_flags': len(deltas), 'audit_gaps': len(result['remaining_audit_gaps'])}))


if __name__ == '__main__':
    build()
