import { Component, type ErrorInfo, type ReactNode } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, Notice } from './ui';

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State { return { error }; }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('AgentSwarm UI error', error, info.componentStack);
  }

  reset = () => {
    this.setState({ error: null });
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return <main className="boot" role="alert"><div className="panel panel-content" style={{ maxWidth: 560 }}><span className="eyebrow lime-text">AGENTSWARM / RECOVERY</span><h1>Something interrupted this workspace.</h1><Notice>The research data was not changed. Reload the page to restore the workspace.</Notice><Button variant="primary" onClick={this.reset}><RefreshCw size={15} />Reload workspace</Button></div></main>;
  }
}
