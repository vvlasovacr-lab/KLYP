import React from 'react';

export const BrollCard = ({event}) => event.enabled ? (
  <div style={{position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#111', color: '#fff', fontSize: 48}}>
    {event.text || 'B-roll placeholder'}
  </div>
) : null;
