import { Component, type ComponentType } from 'react';
import type { WorkbenchChromeProps } from './workbench-chrome';

export type WorkbenchChromeLoader = () => Promise<{ WorkbenchChrome: ComponentType<WorkbenchChromeProps> }>;

export interface OptionalWorkbenchChromeProps extends WorkbenchChromeProps {
  enabled: boolean;
  /** Once per activation, only after the loaded chrome reports its committed mount. */
  onReady: () => void;
  /** Once on import/render failure, including a failure after readiness. */
  onFailure: () => void;
  /** Pinned for one activation; replacing this callback does not restart loading. */
  loader?: WorkbenchChromeLoader;
}

const loadWorkbenchChrome: WorkbenchChromeLoader = () => import('./workbench-chrome');

interface AttemptState {
  Chrome: ComponentType<WorkbenchChromeProps> | null;
  failed: boolean;
}

class ChromeAttempt extends Component<OptionalWorkbenchChromeProps, AttemptState> {
  state: AttemptState = { Chrome: null, failed: false };

  static getDerivedStateFromError(): Partial<AttemptState> {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onFailure();
  }

  private mounted = false;
  private ready = false;
  private epoch = 0;
  private request?: ReturnType<WorkbenchChromeLoader>;

  private handleReady = () => {
    if (!this.mounted || this.state.failed || this.ready) return;
    this.ready = true;
    this.props.onReady();
  };

  componentWillUnmount() {
    this.mounted = false;
  }

  componentDidMount() {
    this.mounted = true;
    const epoch = ++this.epoch;
    if (!this.request) {
      try {
        this.request = (this.props.loader ?? loadWorkbenchChrome)();
      } catch (error) {
        this.request = Promise.reject(error);
      }
    }
    this.request.then(
      module => { if (this.mounted && this.epoch === epoch) this.setState({ Chrome: module.WorkbenchChrome }); },
      () => { if (this.mounted && this.epoch === epoch) this.props.onFailure(); },
    );
  }

  render() {
    const { Chrome, failed } = this.state;
    if (failed) return null;
    const { navigation, sessionControls, themeControl } = this.props;
    return Chrome ? <Chrome navigation={navigation} sessionControls={sessionControls} themeControl={themeControl} onReady={this.handleReady} /> : null;
  }
}

/**
 * Optional presentation sibling, never a workspace/provider wrapper.
 * The parent owns fallback and layout: start/reset readiness to false on disable,
 * set it true onReady, and false onFailure. Pending/failed/disabled render nothing.
 * Disable unmounts this attempt and retires its callbacks; re-enable starts fresh.
 * Callback replacements receive future signals, not a replay of prior readiness.
 * Like other React boundaries, this catches descendant render/lifecycle errors,
 * not event-handler exceptions or arbitrary asynchronous errors inside slots.
 */
export function OptionalWorkbenchChrome(props: OptionalWorkbenchChromeProps) {
  return props.enabled ? <ChromeAttempt {...props} /> : null;
}
