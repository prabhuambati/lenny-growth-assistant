import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function isolatedHtml(content) {
  const policy = "default-src 'none'; script-src 'unsafe-inline'; connect-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; frame-src 'none'; base-uri 'none'; form-action 'none'"
  return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${policy}"></head><body>${content}</body></html>`
}

export default function ArtifactViewer({ artifacts, selectedArtifact, onSelect }) {
  return (
    <aside className="artifact-pane panel">
      <div className="artifact-header">
        <div>
          <div className="eyebrow">Workspace</div>
          <h2>Artifact Viewer</h2>
        </div>
        <span className="stage-badge">Stage 1</span>
      </div>
      {artifacts.length > 0 && (
        <div className="artifact-list" aria-label="Generated artifacts">
          {artifacts.map((artifact) => (
            <button className={`artifact-item ${artifact.id === selectedArtifact?.id ? 'active' : ''}`} key={artifact.id} onClick={() => onSelect(artifact)}>
              <strong>{artifact.title || 'Untitled artifact'}</strong>
              <small>{artifact.type} · {new Date(artifact.created_at).toLocaleDateString()}</small>
            </button>
          ))}
        </div>
      )}
      {!selectedArtifact ? (
        <div className="artifact-empty">
          <div className="artifact-icon">□</div>
          <h3>No artifact selected</h3>
          <p>Generated essays and artifacts will appear here when you create one from a conversation.</p>
        </div>
      ) : selectedArtifact.type === 'html' ? (
        <div className="artifact-content html-artifact">
          <p className="artifact-security">HTML is isolated in a sandbox. Inline scripts may animate this preview, but cannot access the host app, cookies, storage, or network requests.</p>
          <iframe title={selectedArtifact.title || 'HTML artifact'} sandbox="allow-scripts" srcDoc={isolatedHtml(selectedArtifact.content)} />
        </div>
      ) : (
        <div className="artifact-content markdown-artifact">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedArtifact.content}</ReactMarkdown>
        </div>
      )}
    </aside>
  )
}
