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
        <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>🏆 Standings</h3>
        <div style={{ opacity: 0.4, fontSize: '13px' }}>No standings yet</div>
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
      <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>🏆 Standings</h3>
      <table style={{ borderCollapse: 'collapse', width: '100%', tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: '22px' }} />
          <col />
          <col style={{ width: '26px' }} />
          <col style={{ width: '26px' }} />
          <col style={{ width: '26px' }} />
          <col style={{ width: '32px' }} />
          <col style={{ width: '28px' }} />
        </colgroup>
        <thead>
          <tr>
            <th style={headerStyle}>#</th>
            <th style={{ ...headerStyle, textAlign: 'left' }}>Player</th>
            <th style={headerStyle}>W</th>
            <th style={headerStyle}>D</th>
            <th style={headerStyle}>L</th>
            <th style={headerStyle}>Pts</th>
            <th style={headerStyle}>💀</th>
          </tr>
        </thead>
        <tbody>
          {standings.map((s) => (
            <tr key={s.name}>
              <td style={cellStyle}>{s.rank}</td>
              <td style={{
                ...cellStyle,
                textAlign: 'left',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                <div>{s.name}</div>
                {s.model && (
                  <div style={{ fontSize: '9px', opacity: 0.4, marginTop: '1px' }}>
                    {s.model}{s.thinking ? ' 🧠' : ''}
                  </div>
                )}
              </td>
              <td style={cellStyle}>{s.wins}</td>
              <td style={cellStyle}>{s.draws}</td>
              <td style={cellStyle}>{s.losses}</td>
              <td style={{ ...cellStyle, fontWeight: 'bold', color: '#ffd700' }}>{s.points}</td>
              <td style={cellStyle}>{s.fallbacks}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: '10px', opacity: 0.4, marginTop: '6px' }}>💀 = random fallback moves</div>
    </div>
  )
}
