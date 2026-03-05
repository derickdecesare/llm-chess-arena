import React from 'react'

export default function GameHeader({ white, black, gameNum, totalGames, result, running }) {
  if (!white && !black) {
    return (
      <div style={{
        textAlign: 'center',
        padding: '12px 24px',
        background: '#2a2a4a',
        borderRadius: '8px',
        fontSize: '14px',
        opacity: 0.6,
      }}>
        Waiting for tournament to start...
      </div>
    )
  }

  return (
    <div style={{
      textAlign: 'center',
      padding: '12px 24px',
      background: '#2a2a4a',
      borderRadius: '8px',
      width: '100%',
    }}>
      {gameNum > 0 && (
        <div style={{ fontSize: '11px', opacity: 0.5, marginBottom: '4px' }}>
          Game {gameNum}{totalGames > 0 ? ` of ${totalGames}` : ''}
        </div>
      )}
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        gap: '16px',
        fontSize: '16px',
        fontWeight: 'bold',
      }}>
        <span style={{ color: '#f0f0f0' }}>⬜ {white}</span>
        <span style={{ color: '#ffd700', fontSize: '14px' }}>vs</span>
        <span style={{ color: '#b0b0b0' }}>⬛ {black}</span>
      </div>
      {result && (
        <div style={{
          marginTop: '6px',
          fontSize: '14px',
          fontWeight: 'bold',
          color: result === '1-0' ? '#4CAF50' : result === '0-1' ? '#ff6b6b' : '#ffd700',
        }}>
          {result === '1-0' ? `${white} wins!` : result === '0-1' ? `${black} wins!` : 'Draw'}
          <span style={{ fontWeight: 'normal', opacity: 0.6 }}> ({result})</span>
        </div>
      )}
    </div>
  )
}
