import React from 'react'

const cellStyle = {
  padding: '5px 6px',
  textAlign: 'center',
  borderBottom: '1px solid #333',
  fontSize: '12px',
  whiteSpace: 'nowrap',
}
const headerStyle = {
  ...cellStyle,
  fontWeight: 'bold',
  borderBottom: '2px solid #555',
  color: '#ffd700',
  fontSize: '11px',
}

export default function Leaderboard({ standings }) {
  if (!standings || standings.length === 0) {
    return (
      <div style={{
        background: '#2a2a4a',
        borderRadius: '8px',
        padding: '16px',
      }}>
        <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>Leaderboard</h3>
        <div style={{ opacity: 0.4, fontSize: '13px' }}>No agents yet &mdash; register to play!</div>
      </div>
    )
  }

  return (
    <div style={{
      background: '#2a2a4a',
      borderRadius: '8px',
      padding: '12px',
      overflow: 'hidden',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>Leaderboard</h3>
      <table style={{ borderCollapse: 'collapse', width: '100%', tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: '22px' }} />
          <col />
          <col style={{ width: '36px' }} />
          <col style={{ width: '24px' }} />
          <col style={{ width: '24px' }} />
          <col style={{ width: '24px' }} />
          <col style={{ width: '24px' }} />
        </colgroup>
        <thead>
          <tr>
            <th style={headerStyle}>#</th>
            <th style={{ ...headerStyle, textAlign: 'left' }}>Agent</th>
            <th style={headerStyle}>ELO</th>
            <th style={headerStyle}>W</th>
            <th style={headerStyle}>D</th>
            <th style={headerStyle}>L</th>
            <th style={headerStyle} title="Random fallback moves">F</th>
          </tr>
        </thead>
        <tbody>
          {standings.map((s) => (
            <tr key={s.name || s.agent_id}>
              <td style={cellStyle}>{s.rank}</td>
              <td style={{
                ...cellStyle,
                textAlign: 'left',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                <div title={s.description || s.name}>{s.name}</div>
              </td>
              <td style={{ ...cellStyle, fontWeight: 'bold', color: '#ffd700' }}>{s.elo || 1200}</td>
              <td style={cellStyle}>{s.wins}</td>
              <td style={cellStyle}>{s.draws}</td>
              <td style={cellStyle}>{s.losses}</td>
              <td style={{ ...cellStyle, color: (s.fallbacks || 0) > 0 ? '#ff6b6b' : 'inherit' }}>
                {s.fallbacks || 0}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: '10px', opacity: 0.4, marginTop: '6px' }}>
        F = timeout/fallback moves
      </div>
    </div>
  )
}
