import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

/**
 * A render-time throw anywhere under the router blanks the whole page, which
 * for a reviewer mid-determination looks like the service went down. React
 * offers no hook equivalent, so this is the one class component in the app.
 *
 * Callers pass the route as `key` so navigating remounts the boundary, which
 * clears the error - a single bad record must not trap the reviewer on it.
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
