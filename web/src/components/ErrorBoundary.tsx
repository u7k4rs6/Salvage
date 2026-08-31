import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * A render error in one panel should cost that panel, not the console.
 *
 * This exists because it already happened: the evidence packet carries sibling segments as an
 * object and the page expected an array, and the resulting exception blanked every page rather
 * than the one panel. An ops console that goes white when one field has an unexpected shape is
 * worse than one that says which panel broke.
 */
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ name: string; children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[salvage] ${this.props.name} failed to render`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          className="border border-[color:var(--crit)] bg-[color:var(--crit-bg)] px-4 py-3 text-sm text-[color:var(--crit)]"
        >
          <div className="font-medium">{this.props.name} could not be rendered</div>
          <div className="num mt-1 break-words text-[13px]">{this.state.error.message}</div>
          <p className="mt-1 text-[13px]">
            The rest of the page is unaffected. The full stack is in the browser console.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
