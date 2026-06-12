import React, { useState } from 'react';
import { useTCACountdown } from '../utils/tcaCountdown';
import BPlaneDiagram from './BPlaneDiagram';
import { apiPost } from '../utils/api';
import useStore from '../store/useStore';

function cpiClass(cpi) {
  if (cpi >= 8) return 'critical';
  if (cpi >= 5) return 'warning';
  return 'watch';
}

function severityLabel(alert) {
  const cpi = Number(alert.cpi_score ?? 0);
  if (alert.severity) return alert.severity.toUpperCase();
  if (cpi >= 8) return 'CRITICAL';
  if (cpi >= 5) return 'WARNING';
  return 'WATCH';
}

function cpiBarColor(cpi) {
  if (cpi >= 8) return 'var(--alert-red)';
  if (cpi >= 5) return 'var(--alert-yellow)';
  return '#4a90d9';
}

function formatPc(pc) {
  if (!pc || pc === 0) return '—';
  const n = Number(pc);
  if (!Number.isFinite(n)) return '—';
  return n.toExponential(1);
}

export default function ThreatCard({ alert, isSelected, onDecision }) {
  const [expanded, setExpanded] = useState(false);
  const [showDvEditor, setShowDvEditor] = useState(false);
  const [customDv, setCustomDv] = useState(0.1);
  const addDecisionLogEntry = useStore((s) => s.addDecisionLogEntry);
  const setSelectedAlertId = useStore((s) => s.setSelectedAlertId);

  const cpi = Number(alert.cpi_score ?? 0);
  const severity = severityLabel(alert);
  const tcaHours = Number(alert.tca_hours ?? (Number(alert.tca_minutes ?? 720) / 60));
  const { formatted, urgent, critical } = useTCACountdown(tcaHours);

  const sat1 = alert.sat1 ?? {};
  const sat2 = alert.sat2 ?? {};
  const missKm = Number(alert.miss_distance_km ?? 0);
  const relVelKmh = Number(alert.relative_speed_kmh ?? alert.relative_speed_kh ?? 0);
  const relVelKms = (relVelKmh / 3600).toFixed(2);
  const cascadeCount = alert.cascade_depth ?? 0;
  const btKm = Number(alert.bt_km ?? alert.b_plane_bt_km ?? 0);
  const bnKm = Number(alert.bn_km ?? alert.b_plane_bn_km ?? 0);
  const cov = alert.covariance_ellipse ?? {};
  const semiMajorM = Number(cov.a ?? 3000);
  const semiMinorM = Number(cov.b ?? 1000);
  const angleRad = Number(cov.angle ?? 0);
  const hbrKm = 0.010;

  const recManeuver = alert.recommended_maneuver ?? {};
  const newMissKm = Number(recManeuver.new_miss_distance_km ?? missKm * 3);
  const newPc = recManeuver.new_pc_collision ?? null;
  const deltaV = Number(recManeuver.delta_v_ms ?? 0.1);
  const fuelCost = Number(recManeuver.fuel_cost_pct ?? 0.5);

  const handleDecision = async (decision, dv) => {
    const payload = {
      alert_id: alert.id,
      sat1_id: sat1.id,
      sat2_id: sat2.id,
      decision,
      delta_v_ms: dv ?? deltaV,
    };
    try {
      await apiPost('/api/feedback/maneuver', payload);
    } catch (_) { /* silent */ }
    addDecisionLogEntry({
      time: new Date().toISOString(),
      decision,
      alert_id: alert.id,
      sat: sat1.name ?? 'unknown',
    });
    onDecision?.(decision, alert);
    setShowDvEditor(false);
  };

  const handleCardClick = () => {
    setExpanded((v) => !v);
    setSelectedAlertId(isSelected ? null : alert.id);
  };

  return (
    <div
      className={`threat-card severity-${severity} ${isSelected ? 'selected' : ''}`}
      id={`threat-card-${alert.id ?? 'unknown'}`}
    >
      {/* Collapsed header — always visible */}
      <div className="threat-card-header" onClick={handleCardClick}>
        <span className={`severity-badge ${severity}`}>{severity}</span>
        <span className={`cpi-score ${cpiClass(cpi)}`}>CPI {cpi.toFixed(1)}</span>
      </div>

      {/* Satellite pair row */}
      <div className="threat-sat-row">
        <span className="agency-badge">{sat1.agency ?? '—'}</span>
        <span className="threat-sat-name">{sat1.name ?? `#${sat1.id}`}</span>
        <span className="threat-arrow">→</span>
        <span className="agency-badge">{sat2.agency ?? '—'}</span>
        <span className="threat-sat-name">{sat2.name ?? `#${sat2.id}`}</span>
      </div>

      {/* Metrics row */}
      <div className="threat-metrics-row">
        <span className="threat-metric">Miss: <strong>{missKm.toFixed(1)}km</strong></span>
        <span className="threat-metric">Pc: <strong>{formatPc(alert.p_collision)}</strong></span>
        <span className="threat-metric">TCA: <strong>{tcaHours.toFixed(1)}h</strong></span>
        <span className="threat-metric">Casc: <strong>{cascadeCount}</strong></span>
      </div>

      {/* CPI progress bar */}
      <div className="threat-cpi-bar">
        <div
          className="threat-cpi-fill"
          style={{ width: `${Math.min(cpi / 10, 1) * 100}%`, background: cpiBarColor(cpi) }}
        />
      </div>

      {/* TCA countdown */}
      <div className="threat-tca-countdown">
        <span className="tca-label">TCA</span>
        <span className={`tca-time ${critical ? 'critical' : urgent ? 'urgent' : ''}`}>
          {formatted}
        </span>
      </div>

      {/* Expanded section */}
      {expanded && (
        <div className="threat-card-expanded">
          {/* B-plane diagram */}
          <div>
            <div className="threat-section-label">B-Plane Geometry</div>
            <BPlaneDiagram
              btKm={btKm}
              bnKm={bnKm}
              semiMajorM={semiMajorM}
              semiMinorM={semiMinorM}
              angleRad={angleRad}
              hbrKm={hbrKm}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
              <span style={{ fontSize: 8, color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>
                σ_a={semiMajorM.toFixed(0)}m σ_b={semiMinorM.toFixed(0)}m
              </span>
            </div>
          </div>

          {/* Encounter details */}
          <div>
            <div className="threat-section-label">Encounter Details</div>
            <div className="threat-detail-grid">
              <div className="threat-detail-row"><span>Miss distance</span><span>{missKm.toFixed(3)} km</span></div>
              <div className="threat-detail-row"><span>Relative velocity</span><span>{relVelKms} km/s</span></div>
              <div className="threat-detail-row"><span>Combined HBR</span><span>{hbrKm.toFixed(3)} km</span></div>
              <div className="threat-detail-row"><span>B-plane Bt</span><span>{btKm.toFixed(3)} km</span></div>
              <div className="threat-detail-row"><span>B-plane Bn</span><span>{bnKm.toFixed(3)} km</span></div>
              <div className="threat-detail-row"><span>Method</span><span>Foster 1992</span></div>
            </div>
          </div>

          {/* Recommended maneuver */}
          <div>
            <div className="threat-section-label">Recommended Maneuver</div>
            <div className="threat-detail-grid">
              <div className="threat-detail-row">
                <span>Satellite</span><span>{sat1.name ?? `#${sat1.id}`}</span>
              </div>
              <div className="threat-detail-row">
                <span>Delta-V</span><span>{deltaV.toFixed(2)} m/s prograde</span>
              </div>
              <div className="threat-detail-row">
                <span>Fuel cost</span><span>{fuelCost.toFixed(1)}%</span>
              </div>
              <div className="threat-detail-row">
                <span>New miss</span><span style={{ color: 'var(--alert-green)' }}>{newMissKm.toFixed(2)} km</span>
              </div>
              {newPc != null && (
                <div className="threat-detail-row">
                  <span>New Pc</span><span style={{ color: 'var(--alert-green)' }}>{formatPc(newPc)}</span>
                </div>
              )}
            </div>
          </div>

          {/* Cascade section */}
          {cascadeCount > 0 && (
            <div>
              <div className="threat-section-label">Cascade Impact</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 9, color: 'var(--text-dim)' }}>
                Maneuver affects {cascadeCount} other satellite{cascadeCount !== 1 ? 's' : ''}
              </div>
            </div>
          )}

          {/* Inline dV editor */}
          {showDvEditor && (
            <div className="dv-editor">
              <label>Custom Delta-V (m/s)</label>
              <input
                type="range"
                min={0.01}
                max={2.0}
                step={0.01}
                value={customDv}
                onChange={(e) => setCustomDv(Number(e.target.value))}
              />
              <div className="dv-editor-value">{customDv.toFixed(2)} m/s</div>
              <button
                type="button"
                className="td-btn modify"
                onClick={() => handleDecision('MODIFY', customDv)}
              >
                Execute Modified Maneuver
              </button>
            </div>
          )}

          {/* Decision buttons */}
          <div className="threat-decision-btns">
            <button
              type="button"
              className="td-btn approve"
              onClick={() => handleDecision('APPROVE')}
            >
              Approve
            </button>
            <button
              type="button"
              className="td-btn modify"
              onClick={() => setShowDvEditor((v) => !v)}
            >
              Modify
            </button>
            <button
              type="button"
              className="td-btn reject"
              onClick={() => handleDecision('REJECT')}
            >
              Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
