import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { WorkflowPanels } from './workflow-panels';
import { exampleFamilies } from './library-data';
import type { PreviewContext } from './types';

afterEach(cleanup);
const context: PreviewContext = { familyId: 'example-family', versionId: 'example-v1', familyName: 'Example scene', versionLabel: 'v1', robot: 'G1', hand: 'left', dirty: false };
const change = (name: string, value: string) => fireEvent.change(screen.getByLabelText(name), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const rebind = () => {
  fireEvent.click(screen.getByLabelText('Keep form options for the selected saved version; review all target-specific consent again'));
  click('Rebind form to selected version');
};

describe('preview downstream workflows', () => {
  it('never carries proposal acceptance across source rebinding or restores it on return', () => {
    const a = { ...context, familyId: 'example-c1-g1-tabletop', versionId: 'example-c1-g1-tabletop-v1' };
    const view = render(<WorkflowPanels section="improve" context={a} />);
    change('Improvement example state', 'candidate');
    const acceptance = () => screen.getByLabelText('Accept example proposal locally (no editor change)');
    fireEvent.click(acceptance());
    expect(acceptance()).toBeChecked();
    view.rerender(<WorkflowPanels section="improve" context={{ ...a, versionId: 'example-c1-g1-tabletop-v2' }} />);
    rebind();
    expect(acceptance()).not.toBeChecked();
    expect(acceptance()).toBeDisabled();
    expect(screen.queryByText(/Example acceptance reviewed/)).toBeNull();
    view.rerender(<WorkflowPanels section="improve" context={a} />);
    rebind();
    expect(acceptance()).not.toBeChecked();
    expect(acceptance()).toBeEnabled();
  });
  it('requires fresh assistance consent after an offset edit even if the old value returns', () => {
    render(<WorkflowPanels section="improve" context={context} />);
    change('Improvement workflow', 'assistance');
    change('Assistance mode', 'offset');
    fireEvent.click(screen.getByLabelText('Consent to privileged-state example review'));
    expect(screen.getByLabelText('Consent to privileged-state example review')).toBeChecked();
    change('Maximum offset (mm)', '6');
    change('Maximum offset (mm)', '5');
    expect(screen.getByLabelText('Consent to privileged-state example review')).not.toBeChecked();
    click('Preview request');
    expect(screen.getByRole('alert')).toHaveTextContent('privileged');
  });
  it('does not label dirty experiment children as exact saved revisions', () => {
    render(<WorkflowPanels section="experiments" context={{ ...context, dirty: true }} />);
    expect(screen.getByRole('table', { name: 'Effective child configurations' }).textContent).not.toContain('example-v1');
    click('Preview request');
    expect(screen.queryByTestId('frozen-request')).toBeNull();
    expect(screen.getByRole('alert').textContent).toContain('saved example');
  });
  it('keeps independent mounted forms and options through ordinary hidden navigation', () => {
    function Forms({ selected, active }: { selected: PreviewContext; active: string }) {
      return <><section hidden={active !== 'build'}><WorkflowPanels section="build" context={selected} /></section><section hidden={active !== 'experiments'}><WorkflowPanels section="experiments" context={selected} /></section></>;
    }
    const view = render(<Forms selected={context} active="build" />);
    change('Build purpose', 'build');
    change('Step limit', '456');
    view.rerender(<Forms selected={{ ...context, versionId: 'example-v2' }} active="experiments" />);
    click('Preview request');
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).context.versionId).toBe('example-v1');
    view.rerender(<Forms selected={context} active="build" />);
    expect((screen.getByLabelText('Step limit') as HTMLInputElement).value).toBe('456');
  });
  it('keeps the clean bound revision when the current draft becomes dirty without capturing that draft', () => {
    const view = render(<WorkflowPanels section="build" context={context} />);
    view.rerender(<WorkflowPanels section="build" context={{ ...context, dirty: true }} />);
    expect(screen.getByLabelText('Current workflow selection').textContent).toContain('Dirty draft — not captured');
    click('Preview request');
    const request = JSON.parse(screen.getByTestId('frozen-request').textContent!);
    expect(request.context).toEqual(context);
    expect(request.sourceStatus).toContain('draft not captured');
  });
  it('requires a fresh native ownership review after explicit source rebind', () => {
    const view = render(<WorkflowPanels section="build" context={context} />);
    change('Build purpose', 'nativeKit');
    fireEvent.click(screen.getByLabelText('Review native session ownership and close responsibility'));
    view.rerender(<WorkflowPanels section="build" context={{ ...context, versionId: 'example-v2' }} />);
    rebind();
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('ownership');
  });
  it.each([
    ['example-c1-g1-tabletop', 'example-c1-failed-run', 'example-c1-gr00t', 'example-c1-policy-config-v1'],
    ['example-a2-droid', 'example-a2-failed-run', 'example-a2-openpi', 'example-a2-policy-config-v1'],
  ])('binds labelled repair evidence to the actual Library version and policy/config (%s)', (familyId, evidence, policy, config) => {
    const family = exampleFamilies.find(item => item.id === familyId)!;
    const version = family.versions[0];
    const source = { ...context, familyId, versionId: version.versionId, robot: family.robot, hand: family.hand };
    const view = render(<WorkflowPanels section="improve" context={source} />);
    change('Failed evidence', evidence);
    change('Repair policy identity', policy);
    change('Repair policy configuration', config);
    change('Repair feedback', 'Example contact repair');
    click('Preview request');
    const frozen = screen.getByTestId('frozen-request').textContent;
    const binding = JSON.parse(JSON.parse(frozen!).options.evidenceBinding);
    expect(binding).toMatchObject({ exampleOnly: true, familyId, versionId: `${familyId}-v1`, policyIdentity: policy, policyConfigIdentity: config, sceneConfigIdentity: version.source });
    expect(screen.getByLabelText('Repair evidence binding').textContent).toContain('not runtime evidence');
    view.rerender(<WorkflowPanels section="improve" context={{ ...source, familyId: 'example-c1-g1-tabletop', versionId: 'example-c1-g1-tabletop-v2' }} />);
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    rebind();
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    click('Back to form');
    expect(screen.getByLabelText('Repair evidence status').textContent).toContain('family/version mismatch');
    expect((screen.getByRole('button', { name: 'Preview request' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Only the listed v1 fixtures have illustrative failed evidence/)).toBeTruthy();
  });
  it('blocks repair for wrong scene, policy, config and missing evidence identities', () => {
    render(<WorkflowPanels section="improve" context={{ ...context, familyId: 'example-c1-g1-tabletop', versionId: 'example-c1-g1-tabletop-v1' }} />);
    change('Repair feedback', 'Example repair');
    for (const [label, wrong, correct, reason] of [
      ['Failed evidence', 'example-a2-failed-run', 'example-c1-failed-run', 'family/version mismatch'],
      ['Repair policy identity', 'example-a2-openpi', 'example-c1-gr00t', 'policy/config mismatch'],
      ['Repair policy configuration', 'example-a2-policy-config-v1', 'example-c1-policy-config-v1', 'policy/config mismatch'],
      ['Repair policy identity', 'missing', 'example-c1-gr00t', 'policy/config mismatch'],
      ['Repair policy configuration', 'missing', 'example-c1-policy-config-v1', 'policy/config mismatch'],
      ['Failed evidence', 'missing', 'example-c1-failed-run', 'No failed evidence'],
    ]) {
      change(label, wrong);
      expect(screen.getByLabelText('Repair evidence status').textContent).toContain(reason);
      expect((screen.getByRole('button', { name: 'Preview request' }) as HTMLButtonElement).disabled).toBe(true);
      click('Preview request');
      expect(screen.queryByTestId('frozen-request')).toBeNull();
      change(label, correct);
    }
    click('Preview request');
    expect(screen.getByTestId('frozen-request')).toBeTruthy();
  });
  it.each([null, 'example-v1'])('blocks exact-revision work for unresolved drafts (%s) but not new generation or settings', versionId => {
    const unresolved = { ...context, versionId, dirty: true };
    const view = render(<WorkflowPanels section="build" context={unresolved} />);
    expect(screen.getByLabelText('Bound workflow source').textContent).toContain('Unresolved');
    click('Preview request');
    expect(screen.queryByTestId('frozen-request')).toBeNull();
    expect(screen.getByRole('alert').textContent).toContain('saved example');
    expect((screen.getByRole('button', { name: 'Rebind form to selected version' }) as HTMLButtonElement).disabled).toBe(true);
    change('Build purpose', 'generate-build');
    change('Generation prompt', 'New example concept');
    click('Preview request');
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).sourceStatus).toBe('unresolved — draft not captured');
    view.unmount();
    render(<WorkflowPanels section="settings" context={unresolved} />);
    click('Preview request');
    expect(screen.getByTestId('frozen-request')).toBeTruthy();
  });
  it('keeps publication preparation frozen but invalidates its write consent on rebind', () => {
    const view = render(<WorkflowPanels section="graph" context={context} />);
    change('Graph view', 'publication');
    change('Publication example state', 'prepared');
    change('Publication operation', 'publish');
    fireEvent.click(screen.getByLabelText('Consent to publish the frozen example target'));
    click('Preview request');
    const frozen = screen.getByTestId('frozen-request').textContent;
    view.rerender(<WorkflowPanels section="graph" context={{ ...context, versionId: 'example-v2' }} />);
    rebind();
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    expect((screen.getByLabelText('Consent to publish the frozen example target') as HTMLInputElement).checked).toBe(false);
    click('Back to form');
    fireEvent.click(screen.getByLabelText('Consent to publish the frozen example target'));
    click('Preview request');
    expect(screen.getByRole('alert')).toHaveTextContent('previous bound source');
    expect(screen.queryByTestId('frozen-request')).toBeNull();
    change('Publication example state', 'empty');
    change('Publication example state', 'prepared');
    fireEvent.click(screen.getByLabelText('Consent to publish the frozen example target'));
    click('Preview request');
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).context.versionId).toBe('example-v2');
  });
  it('pins the form before first review and requires explicit option retention to rebind', () => {
    const view = render(<WorkflowPanels section="build" context={context} />);
    change('Build purpose', 'build');
    change('Step limit', '321');
    view.rerender(<WorkflowPanels section="build" context={{ ...context, versionId: 'example-v2' }} />);
    expect(screen.getByLabelText('Bound workflow source').textContent).toContain('example-v1');
    expect(screen.getByLabelText('Current workflow selection').textContent).toContain('example-v2');
    click('Preview request');
    const frozen = screen.getByTestId('frozen-request').textContent;
    expect(JSON.parse(frozen!).context.versionId).toBe('example-v1');
    expect((screen.getByRole('button', { name: 'Rebind form to selected version' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText('Keep form options for the selected saved version; review all target-specific consent again'));
    click('Rebind form to selected version');
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    click('Preview request');
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    click('Back to form');
    expect((screen.getByLabelText('Step limit') as HTMLInputElement).value).toBe('321');
    click('Preview request');
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).context.versionId).toBe('example-v2');
  });
  it('retains local edits when switching build purposes and rejects oversized prompt input', () => {
    render(<WorkflowPanels section="build" context={context} />);
    change('Build purpose', 'generate-build');
    change('Generation prompt', 'Example generation notes');
    change('Build purpose', 'snapshot');
    change('Build purpose', 'generate-build');
    expect((screen.getByLabelText('Generation prompt') as HTMLTextAreaElement).value).toBe('Example generation notes');
    change('Generation prompt', 'x'.repeat(4001));
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('4000');
  });
  it('reviews native close only for an owned session and does not equate cleanup with closure', () => {
    render(<WorkflowPanels section="build" context={context} />);
    change('Build purpose', 'nativeKit');
    fireEvent.click(screen.getByLabelText('Review native session ownership and close responsibility'));
    change('Native session operation', 'close');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('owned');
    change('Native session example', 'owned');
    click('Preview request');
    expect(screen.getByTestId('frozen-request').textContent).toContain('nativeKit close');
    click('Back to form');
    change('Native session example', 'cleanup-pending');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('cleanup');
  });
  it('requires privileged-state consent even for observation-only assistance', () => {
    render(<WorkflowPanels section="improve" context={context} />);
    change('Improvement workflow', 'assistance');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('privileged');
  });
  it('retains assistance consent for the pinned source and invalidates it on explicit rebind', () => {
    const view = render(<WorkflowPanels section="improve" context={context} />);
    change('Improvement workflow', 'assistance');
    change('Assistance mode', 'offset');
    fireEvent.click(screen.getByLabelText('Consent to privileged-state example review'));
    view.rerender(<WorkflowPanels section="improve" context={{ ...context, versionId: 'example-v2' }} />);
    click('Preview request');
    const frozen = screen.getByTestId('frozen-request').textContent;
    expect(JSON.parse(frozen!).context.versionId).toBe('example-v1');
    rebind();
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    click('Back to form');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('privileged');
    expect((screen.getByLabelText('Consent to privileged-state example review') as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByLabelText('Consent to privileged-state example review'));
    click('Preview request');
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).context.versionId).toBe('example-v2');
    click('Back to form');
    view.rerender(<WorkflowPanels section="improve" context={context} />);
    rebind();
    view.rerender(<WorkflowPanels section="improve" context={{ ...context, versionId: 'example-v2' }} />);
    rebind();
    expect((screen.getByLabelText('Consent to privileged-state example review') as HTMLInputElement).checked).toBe(false);
  });
  it('offers only nonsecret settings and distinguishes configuration from authentication and inference', () => {
    const { container } = render(<WorkflowPanels section="settings" context={context} />);
    expect(container.querySelector('input[type="password"], input[type="text"], textarea')).toBeNull();
    expect(screen.getByText(/Authentication: not verified/)).toBeTruthy();
    expect(screen.getByText(/Inference: not tested/)).toBeTruthy();
    change('Provider', 'example-openai');
    change('Temperature', '3');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('Temperature');
    change('Temperature', '0.4');
    click('Preview request');
    expect(screen.getByTestId('frozen-request').textContent).toContain('example-openai');
    expect(screen.getByTestId('frozen-request').textContent).toContain('0.4');
    change('Readiness example', 'session-expired');
    expect(screen.getByText(/Session expired: reconnect/)).toBeTruthy();
  });
  it('requires prepared publication consent and blocks publish while outcome is unknown', () => {
    const view = render(<WorkflowPanels section="graph" context={context} />);
    expect(screen.getByText(/Persisted example graph is not the authored draft graph/)).toBeTruthy();
    change('Graph view', 'publication');
    change('Publication operation', 'publish');
    expect((screen.getByRole('button', { name: 'Preview request' }) as HTMLButtonElement).disabled).toBe(true);
    change('Publication example state', 'prepared');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('consent');
    fireEvent.click(screen.getByLabelText('Consent to publish the frozen example target'));
    click('Preview request');
    const frozen = screen.getByTestId('frozen-request').textContent;
    view.rerender(<WorkflowPanels section="graph" context={{ ...context, versionId: 'example-v2' }} />);
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    click('Back to form');
    change('Publication example state', 'unknown');
    expect((screen.getByRole('button', { name: 'Preview request' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/No blind retry/)).toBeTruthy();
    change('Publication operation', 'observe');
    click('Preview request');
    expect(screen.getByTestId('frozen-request').textContent).toContain('observe');
  });
  it.each([false, true])('clears a colliding run comparison without retargeting a frozen review (review open: %s)', reviewOpen => {
    render(<WorkflowPanels section="runs" context={context} />);
    change('Comparison example run', 'example-active');
    expect(screen.getByText(/example-queued versus example-active:/)).toBeTruthy();
    let frozen: string | null = null;
    if (reviewOpen) {
      click('Preview request');
      frozen = screen.getByTestId('frozen-request').textContent;
      expect(JSON.parse(frozen!).options).toMatchObject({ selectedRun: 'example-queued', compare: 'example-active' });
    }
    change('Selected example run', 'example-active');
    expect(screen.getByLabelText('Comparison example run')).toHaveValue('none');
    expect(screen.getByText('Select a second example to inspect attribution.')).toBeTruthy();
    expect(screen.queryByText(/example-active versus example-active:/)).toBeNull();
    if (reviewOpen) {
      expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
      click('Preview request');
      expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
      click('Back to form');
    }
    click('Preview request');
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).options).toMatchObject({ selectedRun: 'example-active', compare: 'none' });
  });
  it('retains a valid comparison when the primary run changes without colliding', () => {
    render(<WorkflowPanels section="runs" context={context} />);
    change('Comparison example run', 'example-active');
    change('Selected example run', 'example-zero-episodes');
    expect(screen.getByLabelText('Comparison example run')).toHaveValue('example-active');
    expect(screen.getByText(/example-zero-episodes versus example-active:/)).toBeTruthy();
    click('Preview request');
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).options).toMatchObject({ selectedRun: 'example-zero-episodes', compare: 'example-active' });
  });
  it('rejects self-comparison at request review even if the select options are bypassed', () => {
    render(<WorkflowPanels section="runs" context={context} />);
    change('Comparison example run', 'example-active');
    click('Preview request');
    const frozen = screen.getByTestId('frozen-request').textContent;
    // Inject an otherwise excluded option to exercise the review boundary independently.
    const comparison = screen.getByLabelText('Comparison example run');
    const option = document.createElement('option');
    option.value = 'example-queued';
    option.textContent = 'example-queued';
    comparison.appendChild(option);
    change('Comparison example run', 'example-queued');
    click('Preview request');
    expect(screen.getByRole('alert')).toHaveTextContent('Comparison run must differ from the selected run.');
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    click('Back to form');
    click('Preview request');
    expect(screen.queryByTestId('frozen-request')).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent('Comparison run must differ from the selected run.');
    change('Comparison example run', 'none');
    click('Preview request');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(JSON.parse(screen.getByTestId('frozen-request').textContent!).options).toMatchObject({ selectedRun: 'example-queued', compare: 'none' });
  });
  it('keeps research metrics and reports separate from operational job controls', () => {
    render(<WorkflowPanels section="runs" context={context} />);
    change('Selected example run', 'example-zero-episodes');
    expect(screen.getByText('Completed episodes: 0')).toBeTruthy();
    expect(screen.getByText('Success rate: unavailable (null)')).toBeTruthy();
    expect(screen.queryByText('0%')).toBeNull();
    change('Selected example run', 'example-cleanup-pending');
    expect(screen.getByText(/Cancellation requested; cleanup still pending/)).toBeTruthy();
    expect(screen.queryByLabelText('Run review operation')).toBeNull();
    expect(screen.queryByLabelText('Queue example state')).toBeNull();
    expect(screen.getByText(/Job cancellation, authorization and integration diagnostics belong in Jobs & diagnostics/)).toBeTruthy();
    change('Selected example run', 'example-unknown');
    expect(screen.getByText(/Unknown outcome/)).toBeTruthy();
    click('Preview request');
    expect(screen.getByTestId('frozen-request').textContent).toContain('example-unknown');
  });
  it('validates experiment import and cumulative budgets with effective ordered children', () => {
    render(<WorkflowPanels section="experiments" context={context} />);
    change('Experiment input', '{}');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('type');
    change('Experiment input', '{"type":"experiment","name":"example-study"}');
    change('Variation seeds', '1,2,3');
    change('Episodes per child', '4');
    change('Total episode budget', '10');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('cumulative');
    change('Total episode budget', '12');
    change('Failure policy', 'continue');
    click('Preview request');
    expect(screen.getByTestId('frozen-request').textContent).toContain('continue');
    expect(screen.getByRole('table', { name: 'Effective child configurations' }).textContent).toContain('example-child-3');
    change('Variation seeds', '1,1');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('unique');
  });
  it('gates privileged assistance by consent and the G1 left-hand contract', () => {
    const view = render(<WorkflowPanels section="improve" context={context} />);
    change('Improvement workflow', 'assistance');
    change('Assistance mode', 'combined');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('privileged');
    fireEvent.click(screen.getByLabelText('Consent to privileged-state example review'));
    click('Preview request');
    expect(screen.getByTestId('frozen-request').textContent).toContain('combined');
    click('Back to form');
    view.rerender(<WorkflowPanels section="improve" context={{ ...context, robot: 'DROID', familyId: 'example-a2-droid', versionId: 'example-a2-droid-v1' }} />);
    rebind();
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('G1 left');
    change('Improvement workflow', 'dcrg');
    expect(screen.getByLabelText('Resume point')).toBeTruthy();
    change('Improvement workflow', 'repair');
    expect(screen.getByLabelText('Failed evidence')).toBeTruthy();
    expect(screen.getByText(/Reevaluation requires separate authorization/)).toBeTruthy();
  });
  it('separates build purposes and never verifies missing policy identity', () => {
    render(<WorkflowPanels section="build" context={context} />);
    expect(screen.getByLabelText('Snapshot scope')).toBeTruthy();
    change('Build purpose', 'evaluate');
    expect(screen.getByText(/Policy identity: missing — not verified/)).toBeTruthy();
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('checkpoint');
    change('Checkpoint or server identity', 'example-checkpoint');
    change('Episode limit', '0');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('Episode');
    change('Build purpose', 'generate-build');
    expect(screen.getByLabelText('Generation prompt')).toBeTruthy();
    change('Build purpose', 'nativeKit');
    expect(screen.getByText(/Native Kit is not browser 3D/)).toBeTruthy();
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('ownership');
  });
  it('bounds build forms and freezes the exact context and options at review', () => {
    const view = render(<WorkflowPanels section="build" context={context} />);
    change('Build purpose', 'build');
    change('Step limit', '0');
    click('Preview request');
    expect(screen.getByRole('alert').textContent).toContain('Step limit');
    change('Step limit', '120');
    click('Preview request');
    const frozen = screen.getByTestId('frozen-request').textContent;
    expect(frozen).toContain('example-v1');
    expect(frozen).toContain('120');
    view.rerender(<WorkflowPanels section="build" context={{ ...context, versionId: 'example-v2', dirty: true }} />);
    change('Step limit', '200');
    expect(screen.getByTestId('frozen-request').textContent).toBe(frozen);
    click('Back to form');
    expect((screen.getByLabelText('Step limit') as HTMLInputElement).value).toBe('200');
  });
});
