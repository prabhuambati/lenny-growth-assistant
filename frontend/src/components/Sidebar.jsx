export default function Sidebar({ sessions, activeId, loading, onNewChat, onSelect }) {
  return (
    <aside className="sidebar panel">
      <div className="brand-block">
        <div className="brand-mark">LG</div>
        <div>
          <div className="eyebrow">Lenny's Podcast</div>
          <h1>Growth Assistant</h1>
        </div>
      </div>
      <button className="new-chat" onClick={onNewChat} disabled={loading}>
        <span>+</span> New Chat
      </button>
      <div className="session-heading">
        <span>Conversations</span>
        <span className="count">{sessions.length}</span>
      </div>
      <div className="session-list" aria-label="Conversations">
        {sessions.length === 0 && <div className="empty-state">Your conversations will appear here.</div>}
        {sessions.map((session) => (
          <button
            className={`session-item ${session.id === activeId ? 'active' : ''}`}
            key={session.id}
            onClick={() => onSelect(session.id)}
            disabled={loading}
          >
            <span className="session-dot" />
            <span className="session-copy">
              <strong>{session.user_label || 'Untitled conversation'}</strong>
              <small>{session.model_provider || 'ollama'} · {new Date(session.created_at).toLocaleDateString()}</small>
            </span>
          </button>
        ))}
      </div>
      <div className="sidebar-footer">Grounded in Lenny's Podcast transcripts</div>
    </aside>
  )
}
