import { useEffect, useRef, useState } from 'react'

function Citations({ citations = [] }) {
  if (!citations.length) return null
  return (
    <div className="citations">
      <span className="citation-label">Sources</span>
      <div className="citation-list">
        {citations.map((citation, index) => (
          <a key={citation.chunk_id || `${citation.source_url}-${index}`} href={citation.source_url || '#'} target="_blank" rel="noreferrer">
            <span className="source-number">{index + 1}</span>
            {citation.episode_title || citation.episode_id || 'Transcript source'}
          </a>
        ))}
      </div>
    </div>
  )
}

export default function ChatPane({ messages, loading, error, onSend }) {
  const [draft, setDraft] = useState('')
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const submit = async () => {
    const content = draft.trim()
    if (!content || loading) return
    setDraft('')
    await onSend(content)
  }

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <main className="chat-pane panel">
      <header className="chat-header">
        <div>
          <div className="eyebrow">Grounded conversation</div>
          <h2>Ask about product and growth</h2>
        </div>
        <div className="chat-status"><span className="status-dot online" /> Live context</div>
      </header>
      <div className="message-list">
        {messages.length === 0 && (
          <div className="welcome-state">
            <div className="welcome-kicker">Start with a sharp question</div>
            <h3>Turn transcript wisdom into your next move.</h3>
            <p>Ask about pricing, product strategy, growth loops, positioning, or team building.</p>
          </div>
        )}
        {messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <div className="message-meta">{message.role === 'user' ? 'You' : 'Lenny Growth Assistant'}</div>
            <div className="message-content">{message.content}</div>
            {message.role === 'assistant' && <Citations citations={message.citations} />}
          </article>
        ))}
        {loading && <div className="typing"><span /><span /><span /> Searching transcripts and thinking</div>}
        {error && <div className="inline-error">{error}</div>}
        <div ref={endRef} />
      </div>
      <div className="composer-wrap">
        <div className="composer">
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} placeholder="Ask a product or growth question..." rows="2" disabled={loading} />
          <button className="send-button" onClick={submit} disabled={loading || !draft.trim()}>Send <span>↗</span></button>
        </div>
        <div className="composer-hint">Enter to send · Shift + Enter for a new line</div>
      </div>
    </main>
  )
}
