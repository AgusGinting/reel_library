import { Component } from "react";

// Menahan error render di satu panel supaya seluruh halaman tidak ikut kosong.
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="panel-error">
        <p className="notice error">Terjadi kesalahan: {String(this.state.error.message || this.state.error)}</p>
        <button className="btn" onClick={() => this.setState({ error: null })}>Coba lagi</button>
        {this.props.onClose && (
          <button className="btn" onClick={this.props.onClose}>Tutup</button>
        )}
      </div>
    );
  }
}
