import { useEffect, useState } from 'react'
import { api } from './lib/api'
import Sidebar from './components/Sidebar'
import ChatPane from './components/ChatPane'
import ArtifactViewer from './components/ArtifactViewer'

const SESSION_KEY = 'lenny-growth-selected-session'

export default function App() {
  const [sessions, setSessions] = useState([])
  const [activeId, setActiveId] = useState(() => localStorage.getItem(SESSION_KEY))
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [chatLoading, setChatLoading] = useState(false)
  const [error, setError] = useState('')
  const [health, setHealth] = useState(null)
  const [model, setModel] = useState(null)
  const [providerMessage, setProviderMessage] = useState('')
  const [artifacts, setArtifacts] = useState([])
  const [selectedArtifact, setSelectedArtifact] = useState(null)

  const refreshRuntime = async () => {
    try {
      const [healthResponse, modelResponse] = await Promise.all([api.health(), api.getModel()])
      setHealth(healthResponse.data)
      setModel(modelResponse.data)
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  const loadSession = async (id) => {
    setLoading(true)
    setError('')
    try {
      const history = await api.getMessages(id)
      const sessionArtifacts = await api.getArtifacts(id)
      setMessages(history)
      setArtifacts(sessionArtifacts)
      setSelectedArtifact(sessionArtifacts[0] || null)
      setActiveId(id)
      localStorage.setItem(SESSION_KEY, id)
    } catch (requestError) {
      if (requestError.code === 'SESSION_NOT_FOUND') {
        localStorage.removeItem(SESSION_KEY)
        setActiveId(null)
        await createChat()
      } else {
        setError(requestError.message)
      }
    } finally {
      setLoading(false)
    }
  }

  const createChat = async () => {
    setLoading(true)
    setError('')
    try {
      const session = await api.createSession('New conversation')
      setSessions((current) => [session, ...current])
      setMessages([])
      setArtifacts([])
      setSelectedArtifact(null)
      setActiveId(session.id)
      localStorage.setItem(SESSION_KEY, session.id)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const boot = async () => {
      setLoading(true)
      await refreshRuntime()
      try {
        const sessionPage = await api.listSessions()
        const availableSessions = sessionPage.items || []
        setSessions(availableSessions)
        const storedSession = activeId && availableSessions.some((session) => session.id === activeId)
          ? activeId
          : availableSessions[0]?.id
        if (storedSession) {
          await loadSession(storedSession)
        } else {
          await createChat()
        }
      } catch (requestError) {
        setError(requestError.message)
      } finally {
        setLoading(false)
      }
    }
    boot()
  }, [])

  const sendMessage = async (content) => {
    if (!activeId) return
    setChatLoading(true)
    setError('')
    const optimistic = { id: `pending-${Date.now()}`, role: 'user', content, citations: [] }
    setMessages((current) => [...current, optimistic])
    try {
      const assistant = await api.sendMessage(activeId, content)
      const sessionArtifacts = await api.getArtifacts(activeId)
      setMessages((current) => [...current.filter((message) => message.id !== optimistic.id), optimistic, assistant])
      setArtifacts(sessionArtifacts)
      setSelectedArtifact(sessionArtifacts[0] || null)
    } catch (requestError) {
      setMessages((current) => current.filter((message) => message.id !== optimistic.id))
      setError(requestError.message)
    } finally {
      setChatLoading(false)
    }
  }

  const changeProvider = async (provider) => {
    setProviderMessage('Switching provider...')
    try {
      const response = await api.setModel(provider)
      setModel(response.data)
      setProviderMessage(`${provider} is ready.`)
    } catch (requestError) {
      setProviderMessage(requestError.message)
    }
  }

  const providerName = model?.active_provider || 'ollama'
  const providerModel = providerName === 'ollama' ? 'llama3.1:8b' : providerName === 'anthropic' ? 'Claude' : providerName === 'gemini' ? 'gemini-2.5-flash' : 'OpenAI'

  return (
    <div className="app-shell">
      <Sidebar sessions={sessions} activeId={activeId} loading={loading} onNewChat={createChat} onSelect={loadSession} />
      <ChatPane messages={messages} loading={chatLoading || loading} error={error} onSend={sendMessage} />
      <ArtifactViewer artifacts={artifacts} selectedArtifact={selectedArtifact} onSelect={setSelectedArtifact} />
      <div className="runtime-bar">
        <div className="runtime-item"><span className={`status-dot ${health?.database ? 'online' : 'offline'}`} /> Database {health?.database ? 'healthy' : 'unavailable'}</div>
        <div className="runtime-item"><span className={`status-dot ${health?.ollama ? 'online' : 'offline'}`} /> Ollama {health?.ollama ? 'available' : 'unavailable'}</div>
        <label className="provider-control">Provider
          <select value={providerName} onChange={(event) => changeProvider(event.target.value)}>
            <option value="ollama">Ollama</option>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="gemini">Google Gemini</option>
          </select>
        </label>
        <span className="model-label">Model: {providerModel}</span>
        {providerMessage && <span className="provider-message">{providerMessage}</span>}
      </div>
    </div>
  )
}
