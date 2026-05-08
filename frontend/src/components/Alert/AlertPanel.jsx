import React from 'react';
import useStore from '../../store/useStore';

const AlertPanel = () => {
  const alerts = useStore((s) => s.alerts);

  return (
    <div className="panel alert-panel">
      <div className="panel-header">
        <span className="panel-title">Conjunction Alerts</span>
        <span className="mono" style={{ fontSize: 11 }}>
          {alerts.length}
        </span>
      </div>
      {alerts.length === 0 ? (
        <div className="no-data">NO ACTIVE ALERTS</div>
      ) : (
        alerts.map((alert, i) => (
          <div className="alert-item" key={i}>
            <div className="alert-names">
              <div>{alert.sat1?.name || 'SAT-1'}</div>
              <div style={{ color: 'var(--text-dim)' }}>
                × {alert.sat2?.name || 'SAT-2'}
              </div>
            </div>
            <div className="alert-distance">
              <div className={`severity-${alert.severity}`}>
                {alert.miss_distance_km?.toFixed(1)} km
              </div>
              <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>
                {alert.relative_speed_kmh?.toFixed(0)} km/h
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
};

export default AlertPanel;
