const API_BASE = '/api'

export async function fetchAgents() {
  const res = await fetch(`${API_BASE}/agents`)
  return res.json()
}

export async function fetchStandings() {
  const res = await fetch(`${API_BASE}/standings`)
  return res.json()
}

export async function fetchGames() {
  const res = await fetch(`${API_BASE}/games`)
  return res.json()
}

export async function fetchGamePgn(gameNum) {
  const res = await fetch(`${API_BASE}/games/${gameNum}/pgn`)
  return res.json()
}

export async function fetchStatus() {
  const res = await fetch(`${API_BASE}/status`)
  return res.json()
}

export async function startTournament() {
  const res = await fetch(`${API_BASE}/tournament/start`, { method: 'POST' })
  return res.json()
}

export async function resetTournament() {
  const res = await fetch(`${API_BASE}/tournament/reset`, { method: 'POST' })
  return res.json()
}

export async function pauseTournament() {
  const res = await fetch(`${API_BASE}/tournament/pause`, { method: 'POST' })
  return res.json()
}

export function connectWebSocket(onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws`)
  ws.onmessage = (e) => onMessage(JSON.parse(e.data))
  ws.onclose = () => setTimeout(() => connectWebSocket(onMessage), 2000)
  return ws
}
