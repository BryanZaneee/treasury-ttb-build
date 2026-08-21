import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

/**
 * A render-time throw blanks the page, which mid-determination reads as an
 * outage. React has no hook equivalent, so this is the app's one class component.
 * Callers pass the route as `key`, so navigating clears the error.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled render error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="card card-pad" style={{ marginTop: 16 }}>
        <div className="card-title">This page could not be displayed</div>
        <p className="card-note">
          Nothing was lost — no determination is recorded by opening a page. Go back to the
          inbox, or reload to try again.
        </p>
        <p className="card-note mono" style={{ fontSize: 11.5 }}>
          {this.state.error.message}
        </p>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
