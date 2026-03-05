import React, { useRef, useEffect } from 'react'

export default function MoveList({ moves }) {
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [moves])

  if (!moves || moves.length === 0) {
    return (
      <div style={{
        background: '#2a2a4a',
        borderRadius: '8px',
        padding: '16px',
      }}>
        <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>📜 Moves</h3>
        <div style={{ opacity: 0.4, fontSize: '13px' }}>Waiting for moves...</div>
      </div>
    )
  }

  // Pair into rows
  const rows = []
  for (let i = 0; i < moves.length; i += 2) {
    rows.push({
      num: Math.floor(i / 2) + 1,
      white: moves[i],
      black: moves[i + 1] || null,
    })
  }

  const MoveCell = ({ move }) => {
    if (!move) return <span style={{ width: '70px', display: 'inline-block' }} />
    const isNew = moves.indexOf(move) >= moves.length - 2
    return (
      <span style={{
        width: '70px',
        display: 'inline-block',
        color: move.fallback ? '#ff6b6b' : isNew ? '#4CAF50' : '#e0e0e0',
        fontWeight: isNew ? 'bold' : 'normal',
        transition: 'color 0.5s',
      }}>
        {move.san}{move.fallback ? ' 💀' : ''}
      </span>
    )
  }

  return (
    <div style={{
      background: '#2a2a4a',
      borderRadius: '8px',
      padding: '16px',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>📜 Moves</h3>
      <div style={{
        maxHeight: '400px',
        overflowY: 'auto',
        fontFamily: 'monospace',
        fontSize: '13px',
        lineHeight: '2',
      }}>
        {rows.map((r) => (
          <div key={r.num} style={{ display: 'flex', gap: '6px' }}>
            <span style={{ width: '28px', opacity: 0.35, textAlign: 'right', flexShrink: 0 }}>{r.num}.</span>
            <MoveCell move={r.white} />
            <MoveCell move={r.black} />
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div style={{
        marginTop: '8px',
        fontSize: '11px',
        opacity: 0.4,
        borderTop: '1px solid #333',
        paddingTop: '6px',
      }}>
        {moves.length} moves • {moves.filter(m => m.fallback).length} fallbacks 💀
      </div>
    </div>
  )
}
