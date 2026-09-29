const API_BASE = import.meta.env.VITE_API_URL || '/api'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = body?.error?.message || body?.detail?.message || body?.detail || `Request failed (${response.status})`
    const error = new Error(message)
    error.code = body?.error?.code || body?.detail?.code
    error.status = response.status
    throw error
  }
  return body
}

export const api = {
  health: () => request('/health'),
  getModel: () => request('/config/model'),
  setModel: (provider) => request('/config/model', { method: 'PUT', body: JSON.stringify({ provider }) }),
  listSessions: (after) => request(`/sessions${after ? `?after=${encodeURIComponent(after)}` : ''}`),
  createSession: (user_label = 'New conversation') => request('/sessions', { method: 'POST', body: JSON.stringify({ user_label }) }),
  getSession: (id) => request(`/sessions/${id}`),
  getMessages: (id) => request(`/sessions/${id}/messages`),
  getArtifacts: (id) => request(`/sessions/${id}/artifacts`),
  sendMessage: (id, content) => request(`/sessions/${id}/messages`, { method: 'POST', body: JSON.stringify({ content }) }),
  createArtifact: (id, type, topic) => request(`/sessions/${id}/artifacts`, { method: 'POST', body: JSON.stringify({ type, topic }) }),
  getArtifact: (id) => request(`/artifacts/${id}`),
}
