import React, { useState } from 'react'
import { registerAgent } from '../api'

export default function RegisterAgent({ onRegistered }) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleRegister = async () => {
    if (!name.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await registerAgent(name.trim(), desc.trim())
      if (res.error || res.detail) {
        setError(res.error || res.detail)
      } else {
        setResult(res)
        setName('')
        setDesc('')
        if (onRegistered) onRegistered()
      }
    } catch (e) {
      setError(e.message)
    }
    setLoading(false)
  }

  return (
    <div style={{
      background: '#2a2a4a',
      borderRadius: '8px',
      padding: '16px',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#4CAF50' }}>
        Register Your Agent
      </h3>

      {result ? (
        <div style={{ fontSize: '12px' }}>
          <div style={{ color: '#4CAF50', marginBottom: '8px', fontWeight: 'bold' }}>
            Agent registered!
          </div>
          <div style={{ marginBottom: '4px' }}>
            <strong>ID:</strong> {result.agent_id}
          </div>
          <div style={{
            marginBottom: '8px',
            padding: '8px',
            background: '#1a1a2e',
            borderRadius: '4px',
            wordBreak: 'break-all',
            fontFamily: 'monospace',
            fontSize: '11px',
          }}>
            <strong>Token:</strong> {result.token}
          </div>
          <div style={{ color: '#ff9800', fontSize: '11px', marginBottom: '8px' }}>
            Save this token! It won&apos;t be shown again.
          </div>
          <button
            onClick={() => setResult(null)}
            style={{
              padding: '4px 12px',
              background: '#3a3a5a',
              color: '#e0e0e0',
              border: '1px solid #555',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '11px',
            }}
          >
            Register Another
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Agent name"
            maxLength={30}
            style={{
              padding: '6px 8px',
              background: '#1a1a2e',
              border: '1px solid #444',
              borderRadius: '4px',
              color: '#e0e0e0',
              fontSize: '13px',
            }}
          />
          <input
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="Description (optional)"
            maxLength={100}
            style={{
              padding: '6px 8px',
              background: '#1a1a2e',
              border: '1px solid #444',
              borderRadius: '4px',
              color: '#e0e0e0',
              fontSize: '13px',
            }}
          />
          <button
            onClick={handleRegister}
            disabled={loading || !name.trim()}
            style={{
              padding: '8px',
              background: '#4CAF50',
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 'bold',
              opacity: loading || !name.trim() ? 0.5 : 1,
            }}
          >
            {loading ? 'Registering...' : 'Register'}
          </button>
          {error && (
            <div style={{ color: '#ff6b6b', fontSize: '12px' }}>{error}</div>
          )}
        </div>
      )}
    </div>
  )
}
