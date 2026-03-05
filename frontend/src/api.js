const API_BASE = '/api'

export async function fetchLeaderboard() {
  const res = await fetch(`${API_BASE}/leaderboard`)
  return res.json()
}

export async function fetchStandings() {
  return fetchLeaderboard()
}

export async function fetchActiveGames() {
  const res = await fetch(`${API_BASE}/games/active`)
  return res.json()
}

export async function fetchFinishedGames() {
  const res = await fetch(`${API_BASE}/games/finished`)
  return res.json()
}

export async function fetchGames() {
  return fetchFinishedGames()
}

export async function fetchGame(gameId) {
  const res = await fetch(`${API_BASE}/games/${gameId}`)
  return res.json()
}

export async function fetchStatus() {
  const res = await fetch(`${API_BASE}/status`)
  return res.json()
}

export async function fetchQueueStatus() {
  const res = await fetch(`${API_BASE}/queue/status`)
  return res.json()
}

export async function fetchAgents() {
  const res = await fetch(`${API_BASE}/agents`)
  return res.json()
}

export async function fetchTools() {
  const res = await fetch(`${API_BASE}/tools`)
  return res.json()
}

export async function registerAgent(name, description) {
  const res = await fetch(`${API_BASE}/agents/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  })
  return res.json()
}

export async function joinQueue(token) {
  const res = await fetch(`${API_BASE}/queue/join`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  return res.json()
}

export async function leaveQueue(token) {
  const res = await fetch(`${API_BASE}/queue/leave`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  return res.json()
}

export function connectWebSocket(onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws`)
  ws.onmessage = (e) => onMessage(JSON.parse(e.data))
  ws.onclose = () => setTimeout(() => connectWebSocket(onMessage), 2000)
  return ws
}
