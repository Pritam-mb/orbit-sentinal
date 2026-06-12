import React from 'react';
import useStore from '../../store/useStore';

const AlertPanel = () => {
  const alerts = useStore((s) => s.alerts);
  const cascadePlan = useStore((s) => s.cascadePlan);
  const hotspots = useStore((s) => s.hotspots);

  const totalDeltaV = cascadePlan?.total_delta_v_ms != null
    ? Number(cascadePlan.total_delta_v_ms).toFixed(3)
    : '0.000';

  return (
    <div className="panel alert-panel">
      <div className="panel-header">
        <span className="panel-title">Conjunction Alerts</span>
        <span className="mono" style={{ fontSize: 11 }}>
          {alerts.length}
        </span>
      </div>

      {cascadePlan && (
        <div className="monitor-card">
          <div className="monitor-title">Cascade Plan</div>
          <div className="monitor-row">
            <span>Graph Nodes</span>
            <span className="mono">{cascadePlan.graph?.node_count ?? 0}</span>
          </div>
          <div className="monitor-row">
            <span>Graph Edges</span>
            <span className="mono">{cascadePlan.graph?.edge_count ?? 0}</span>
          </div>
          <div className="monitor-row">
            <span>Max Cascade Depth</span>
            <span className="mono">{cascadePlan.cascade_depth ?? 0}</span>
          </div>
          <div className="monitor-row">
            <span>Total Delta-V</span>
            <span className="mono">{totalDeltaV} m/s</span>
          </div>
          <div className="monitor-row">
            <span>Agencies</span>
            <span className="mono">{(cascadePlan.agencies_involved || []).join(', ') || '—'}</span>
          </div>
        </div>
      )}

      {alerts.length === 0 ? (
        <div className="no-data">NO ACTIVE ALERTS</div>
      ) : (
        alerts.map((alert, i) => {
          const topCascade = cascadePlan?.cascade_plan?.find(
            (maneuver) => maneuver.satellite_id === alert.sat1?.id || maneuver.satellite_id === alert.sat2?.id,
          );

          return (
            <div className="alert-item" key={`${alert.sat1?.id || 'a'}-${alert.sat2?.id || 'b'}-${i}`}>
              <div className="alert-names">
                <div>{alert.sat1?.name || 'SAT-1'}</div>
                <div style={{ color: 'var(--text-dim)' }}>
                  × {alert.sat2?.name || 'SAT-2'}
                </div>
                {topCascade && (
                  <div style={{ color: 'var(--alert-green)', fontSize: 10, marginTop: 4 }}>
                    Cascade depth {topCascade.cascade_depth} | {topCascade.maneuver.delta_v_ms} m/s
                  </div>
                )}
              </div>
              <div className="alert-distance">
                <div className={`severity-${alert.severity}`}>
                  {Number(alert.miss_distance_km || 0).toFixed(1)} km
                </div>
                <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>
                  {Number(alert.relative_speed_kmh || 0).toFixed(0)} km/h
                </div>
                {alert.cpi_score != null && (
                  <div style={{ color: 'var(--text-bright)', fontSize: 10 }}>
                    CPI {Number(alert.cpi_score).toFixed(1)}
                  </div>
                )}
              </div>
            </div>
          );
        })
      )}

      {cascadePlan?.cascade_plan?.length > 0 && (
        <div className="monitor-card" style={{ marginTop: 12 }}>
          <div className="monitor-title">Maneuver Chain</div>
          {cascadePlan.cascade_plan.slice(0, 8).map((maneuver) => (
            <div className="monitor-row" key={`${maneuver.satellite_id}-${maneuver.cascade_depth}`}>
              <span>{maneuver.satellite_name}</span>
              <span className="mono">
                D{maneuver.cascade_depth} | {maneuver.maneuver.delta_v_ms} m/s
              </span>
            </div>
          ))}
        </div>
      )}

      {hotspots.length > 0 && (
        <div className="monitor-card" style={{ marginTop: 12 }}>
          <div className="monitor-title">Red Hotspots</div>
          {hotspots.slice(0, 5).map((hotspot, index) => (
            <div className="monitor-row" key={`${hotspot.sat1?.id}-${hotspot.sat2?.id}-${index}`}>
              <span>
                {hotspot.sat1?.name || 'SAT-1'} × {hotspot.sat2?.name || 'SAT-2'}
              </span>
              <span className="mono">
                {Number(hotspot.hotspot_score || 0).toFixed(2)} | T{Number(hotspot.tca_minutes || 0).toFixed(0)}m
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default AlertPanel;
