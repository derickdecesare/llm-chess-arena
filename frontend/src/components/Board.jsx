import React from 'react'
import { Chessboard } from 'react-chessboard'

export default function Board({ fen, white, black, lastMove }) {
  // Highlight the last move's squares
  const customSquareStyles = {}
  if (lastMove) {
    customSquareStyles[lastMove.from] = { background: 'rgba(255, 255, 0, 0.3)' }
    customSquareStyles[lastMove.to] = { background: 'rgba(255, 255, 0, 0.4)' }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <Chessboard
        position={fen || 'start'}
        boardWidth={420}
        arePiecesDraggable={false}
        animationDuration={300}
        customSquareStyles={customSquareStyles}
        customDarkSquareStyle={{ backgroundColor: '#779952' }}
        customLightSquareStyle={{ backgroundColor: '#edeed1' }}
      />
    </div>
  )
}
