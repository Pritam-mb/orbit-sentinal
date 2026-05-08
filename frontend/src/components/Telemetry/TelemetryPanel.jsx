import React, { useEffect, useState } from 'react';
import useStore from '../../store/useStore';
import { eciToLla } from '../../utils/coords';

const TelemetryPanel = () => {
  const selectedSatelliteId = useStore((s) => s.selectedSatelliteId);
  const satellites = useStore((s) => s.satellites);
  const setSelectedOrbit = useStore((s) => s.setSelectedOrbit);
  const [satelliteDetail, setSatelliteDetail] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let detailTimer = null;
    let orbitTimer = null;

    const apiBaseUrl = 'http://127.0.0.1:8000';

    const loadSelectedSatellite = async () => {
      if (!selectedSatelliteId) {
        setSatelliteDetail(null);
        setSelectedOrbit([]);
        return;
      }

      const fallbackSatellite =
        satellites.find((satellite) => satellite.norad_id === selectedSatelliteId) ||
        null;

      setSatelliteDetail(fallbackSatellite);

      try {
        const resp = await fetch(`${apiBaseUrl}/api/satellites/${selectedSatelliteId}`);
        if (!resp.ok) return;

        const data = await resp.json();
        if (!cancelled) {
          setSatelliteDetail(data);
        }
      } catch (error) {
        console.error('Selected satellite detail fetch failed:', error);
      }
    };

    const loadOrbit = async () => {
      if (!selectedSatelliteId) {
        setSelectedOrbit([]);
        return;
      }

      try {
        const resp = await fetch(
          `${apiBaseUrl}/api/satellites/${selectedSatelliteId}/orbit?span_minutes=180&step_seconds=10`
        );
        if (!resp.ok) return;

        const data = await resp.json();
        if (!cancelled) {
          setSelectedOrbit(data.orbit || []);
        }
      } catch (error) {
        console.error('Selected orbit fetch failed:', error);
      }
    };

    if (!selectedSatelliteId) {
      loadSelectedSatellite();
      return () => {
        cancelled = true;
      };
    }

    loadSelectedSatellite();
    loadOrbit();

    detailTimer = setInterval(loadSelectedSatellite, 1000);
    orbitTimer = setInterval(loadOrbit, 30000);

    return () => {
      cancelled = true;
      if (detailTimer) {
        clearInterval(detailTimer);
      }
      if (orbitTimer) {
        clearInterval(orbitTimer);
      }
    };
  }, [selectedSatelliteId, satellites, setSelectedOrbit]);

  const sat = satelliteDetail;

  if (!sat) {
    return (
      <div className="telemetry-overlay satellite-card">
        <div className="no-data">NO SATELLITE SELECTED</div>
      </div>
    );
  }

  const now = new Date();
  const lla = eciToLla(sat.position, now);
  const speedText = sat.speed_kmh != null ? sat.speed_kmh.toLocaleString() : '---';
  const heightText = sat.altitude_km != null ? Math.round(sat.altitude_km).toLocaleString() : '---';
  const latitudeText = lla.lat != null ? lla.lat.toFixed(2) : '---';
  const longitudeText = lla.lon != null ? lla.lon.toFixed(2) : '---';

  return (
    <div className="telemetry-overlay satellite-card">
      <div className="satellite-card__header">
        <div className="satellite-card__title">{sat.name}</div>
        <div className="satellite-card__id">#{sat.norad_id}</div>
      </div>
      <div className="satellite-card__divider" />
      <div className="satellite-card__rows">
        <div className="satellite-card__row">
          <span>Speed:</span>
          <strong>{speedText} km/h</strong>
        </div>
        <div className="satellite-card__row">
          <span>Height:</span>
          <strong>{heightText} km</strong>
        </div>
        <div className="satellite-card__row">
          <span>Latitude:</span>
          <strong>{latitudeText}°</strong>
        </div>
        <div className="satellite-card__row">
          <span>Longitude:</span>
          <strong>{longitudeText}°</strong>
        </div>
      </div>
    </div>
  );
};

export default TelemetryPanel;
