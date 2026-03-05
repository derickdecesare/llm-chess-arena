import React from 'react'

export default function QueueStatus({ status }) {
  if (!status) return null

  return (
    <div style={{
      background: '#2a2a4a',
      borderRadius: '8px',
      padding: '12px 16px',
      fontSize: '13px',
    }}>
      <h3 style={{ margin: '0 0 6px', fontSize: '14px', color: '#ffd700' }}>
        Matchmaking Queue
      </h3>
      <div style={{ opacity: 0.7 }}>
        {status.queue_size === 0 ? (
          <span>Queue empty &mdash; agents can join via API</span>
        ) : (
          <div>
            <div>{status.queue_size} agent{status.queue_size !== 1 ? 's' : ''} waiting</div>
            {status.waiting_agents && status.waiting_agents.length > 0 && (
              <div style={{ marginTop: '4px', fontSize: '11px', opacity: 0.6 }}>
                {status.waiting_agents.join(', ')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
