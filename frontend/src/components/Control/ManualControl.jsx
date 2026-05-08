import React, { useState } from 'react';
import useStore from '../../store/useStore';
import PreflightModal from './PreflightModal';

const ManualControl = () => {
  const apiBaseUrl = 'http://127.0.0.1:8000';
  const maneuver = useStore((s) => s.maneuver);
  const setManeuver = useStore((s) => s.setManeuver);
  const selectedSatelliteId = useStore((s) => s.selectedSatelliteId);
  const setSimulationActive = useStore((s) => s.setSimulationActive);
  const [showPreflight, setShowPreflight] = useState(false);

  const handleSliderChange = (axis, value) => {
    setManeuver(axis, parseFloat(value));
  };

  const handleExecute = () => {
    if (!selectedSatelliteId) return;
    setShowPreflight(true);
  };

  const handleConfirmBurn = async () => {
    try {
      const resp = await fetch(`${apiBaseUrl}/api/maneuver`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          norad_id: selectedSatelliteId,
          dvx: maneuver.dvx,
          dvy: maneuver.dvy,
          dvz: maneuver.dvz,
        }),
      });
      const data = await resp.json();
      console.log('Maneuver result:', data);
    } catch (e) {
      console.error('Maneuver failed:', e);
    }
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
    { axis: 'dvx', label: 'Delta-V X', unit: 'm/s' },
    { axis: 'dvy', label: 'Delta-V Y', unit: 'm/s' },
    { axis: 'dvz', label: 'Delta-V Z', unit: 'm/s' },
  ];

  return (
    <div className="panel control-panel">
      <div className="panel-header">
        <span className="panel-title">Manual Control</span>
      </div>

      {sliders.map(({ axis, label, unit }) => (
        <div className="slider-group" key={axis}>
          <div className="slider-label">
            <span>{label}</span>
            <span>
              {maneuver[axis]?.toFixed(1)} {unit}
            </span>
          </div>
          <input
            type="range"
            min="-50"
            max="50"
            step="0.5"
            value={maneuver[axis] || 0}
            onChange={(e) => handleSliderChange(axis, e.target.value)}
          />
        </div>
      ))}

      <button
        className="btn btn-execute"
        onClick={handleExecute}
        disabled={!selectedSatelliteId}
      >
        Execute Burn
      </button>

      <button className="btn btn-scenario" onClick={handleTriggerScenario}>
        Trigger Scenario
      </button>

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
