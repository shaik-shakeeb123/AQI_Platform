import React from 'react';
import PageWrapper from './PageWrapper';

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error("ErrorBoundary caught an error:", error, errorInfo);
    }

    render() {
        if (this.state.hasError) {
            return (
                <PageWrapper>
                    <div className="card" style={{ textAlign: "center", padding: "50px 20px" }}>
                        <h2 style={{ color: "var(--danger)" }}>⚠ Something went wrong.</h2>
                        <p style={{ margin: "20px 0" }}>An unexpected error occurred in this section.</p>
                        <button 
                            className="login-btn"
                            onClick={() => window.location.href = '/'}
                        >
                            Return to Dashboard
                        </button>
                    </div>
                </PageWrapper>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
