import React from 'react'

export default function ActiveGames({ games, onSelect, selectedId }) {
  return (
    <div style={{
      background: '#2a2a4a',
      borderRadius: '8px',
      padding: '16px',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#4CAF50' }}>
        <span style={{ marginRight: '6px' }}>&#9679;</span> Live Games
      </h3>
      {(!games || games.length === 0) ? (
        <div style={{ opacity: 0.4, fontSize: '13px' }}>No active games</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {games.map((g) => (
            <button
              key={g.game_id}
              onClick={() => onSelect(g)}
              style={{
                background: g.game_id === selectedId ? '#3a3a6a' : '#1a1a2e',
                border: g.game_id === selectedId ? '1px solid #4CAF50' : '1px solid #333',
                borderRadius: '4px',
                color: '#e0e0e0',
                padding: '8px 10px',
                cursor: 'pointer',
                textAlign: 'left',
                fontSize: '12px',
              }}
            >
              <div style={{ fontWeight: 'bold' }}>
                {g.white?.name || 'White'} vs {g.black?.name || 'Black'}
              </div>
              <div style={{ opacity: 0.6, marginTop: '2px' }}>
                {g.move_count} moves &bull; {g.turn} to move
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
