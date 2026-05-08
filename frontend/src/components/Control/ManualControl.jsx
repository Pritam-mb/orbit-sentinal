import React, { useState } from 'react';
import useStore from '../../store/useStore';
import PreflightModal from './PreflightModal';

const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

const ManualControl = () => {
  const maneuver = useStore((s) => s.maneuver);
  const setManeuver = useStore((s) => s.setManeuver);
  const resetManeuver = useStore((s) => s.resetManeuver);
  const selectedSatelliteId = useStore((s) => s.selectedSatelliteId);
  const selectedSatellite = useStore((s) => {
    if (!s.selectedSatelliteId) return null;
    return s.satellites.find((sat) => sat.norad_id === s.selectedSatelliteId) || null;
  });
  const setSimulationActive = useStore((s) => s.setSimulationActive);
  const [showPreflight, setShowPreflight] = useState(false);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSliderChange = (axis, value) => {
    setManeuver(axis, parseFloat(value));
  };

  const handleExecute = () => {
    if (!selectedSatelliteId) return;
    setShowPreflight(true);
  };

  const handleConfirmBurn = async () => {
    if (!selectedSatelliteId) return;

    setLoading(true);
    setResult(null);

    try {
      const resp = await fetch(`${apiBaseUrl}/api/maneuver`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          norad_id: selectedSatelliteId,
          dvx: maneuver.dvx,
          dvy: maneuver.dvy,
          dvz: maneuver.dvz,
          frame: 'RSW',
        }),
      });
      const data = await resp.json();
      setResult(data);
    } catch (e) {
      setResult({ status: 'ERROR', error: e.message });
    }

    setLoading(false);
    setShowPreflight(false);
  };

  const handleTriggerScenario = async () => {
    try {
      const resp = await fetch(`${apiBaseUrl}/api/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'approaching' }),
      });
      const data = await resp.json();
      console.log('Scenario loaded:', data);
      setSimulationActive(true);
    } catch (e) {
      console.error('Scenario trigger failed:', e);
    }
  };

  const sliders = [
    { axis: 'dvx', label: 'Radial (R)', hint: 'pushes orbit up or down' },
    { axis: 'dvy', label: 'Along-track (S)', hint: 'speeds up or slows down' },
    { axis: 'dvz', label: 'Cross-track (W)', hint: 'tilts the orbital plane' },
  ];

  return (
    <div className="panel control-panel">
      <div className="panel-header">
        <span className="panel-title">Manual Control</span>
      </div>

      {!selectedSatelliteId ? (
        <div className="no-data">SELECT A SATELLITE TO COMMAND</div>
      ) : (
        <div style={{ marginBottom: 12, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-dim)' }}>
          Commanding: <span style={{ color: 'var(--text-bright)' }}>{selectedSatellite?.name || `#${selectedSatelliteId}`}</span>
        </div>
      )}

      {sliders.map(({ axis, label, hint }) => (
        <div className="slider-group" key={axis}>
          <div className="slider-label">
            <span>
              {label} <span style={{ color: 'var(--text-dim)', textTransform: 'none', letterSpacing: 0 }}>({hint})</span>
            </span>
            <span>
              {maneuver[axis]?.toFixed(1)} m/s
            </span>
          </div>
          <input
            type="range"
            min="-5"
            max="5"
            step="0.05"
            value={maneuver[axis] || 0}
            onChange={(e) => handleSliderChange(axis, e.target.value)}
          />
        </div>
      ))}

      <div className="threshold-note mono">
        Total delta-V: {Math.sqrt((maneuver.dvx ** 2) + (maneuver.dvy ** 2) + (maneuver.dvz ** 2)).toFixed(3)} m/s
      </div>

      <div className="btn-row" style={{ marginTop: 12 }}>
        <button className="btn" type="button" onClick={resetManeuver}>
          Reset
        </button>
        <button
          className="btn btn-execute"
          type="button"
          onClick={handleExecute}
          disabled={!selectedSatelliteId || loading}
        >
          {loading ? 'Applying...' : 'Run Preflight + Burn'}
        </button>
      </div>

      <button className="btn btn-scenario" type="button" onClick={handleTriggerScenario}>
        Trigger Scenario
      </button>

      {result && (
        <div
          className={`status-banner mono ${result.error || result.status === 'ERROR' ? 'error' : ''}`}
          style={{ marginTop: 12, textAlign: 'left' }}
        >
          {result.error || result.status === 'ERROR' ? (
            <div>Rejected: {result.error || result.message || 'Unable to apply maneuver'}</div>
          ) : (
            <div>
              <div>Burn applied successfully</div>
              <div>Frame: {result.frame_used || 'RSW'}</div>
              <div>New perigee: {result.new_perigee_km} km</div>
              <div>New apogee: {result.new_apogee_km} km</div>
              <div>New period: {result.new_period_min} min</div>
              <div>Delta-V used: {Number(result.delta_v_ms || 0).toFixed(3)} m/s</div>
            </div>
          )}
        </div>
      )}

      {showPreflight && (
        <PreflightModal
          noradId={selectedSatelliteId}
          maneuver={maneuver}
          onConfirm={handleConfirmBurn}
          onCancel={() => setShowPreflight(false)}
        />
      )}
    </div>
  );
};

export default ManualControl;
