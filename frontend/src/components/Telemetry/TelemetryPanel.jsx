import React, { useEffect, useState } from 'react';
import useStore from '../../store/useStore';
import { eciToLla } from '../../utils/coords';

const computeSpeedKmh = (velocity) => {
  if (!velocity) return null;
  const vx = Number(velocity.vx ?? velocity.x ?? 0);
  const vy = Number(velocity.vy ?? velocity.y ?? 0);
  const vz = Number(velocity.vz ?? velocity.z ?? 0);
  if ([vx, vy, vz].some((value) => Number.isNaN(value))) return null;
  return Math.sqrt((vx * vx) + (vy * vy) + (vz * vz)) * 3600;
};

const computeAltitudeKm = (position) => {
  if (!position) return null;
  const x = Number(position.x ?? 0);
  const y = Number(position.y ?? 0);
  const z = Number(position.z ?? 0);
  if ([x, y, z].some((value) => Number.isNaN(value))) return null;
  return Math.sqrt((x * x) + (y * y) + (z * z)) - 6371.0;
};

const enrichSatellite = (sat) => {
  if (!sat) return sat;

  const speedKmh = sat.speed_kmh != null ? sat.speed_kmh : computeSpeedKmh(sat.velocity);
  const altitudeKm = sat.altitude_km != null ? sat.altitude_km : computeAltitudeKm(sat.position);

  return {
    ...sat,
    speed_kmh: speedKmh,
    altitude_km: altitudeKm,
  };
};

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

      setSatelliteDetail(enrichSatellite(fallbackSatellite));

      try {
        const resp = await fetch(`${apiBaseUrl}/api/satellites/${selectedSatelliteId}`);
        if (!resp.ok) return;

        const data = await resp.json();
        if (!cancelled) {
          setSatelliteDetail(enrichSatellite({
            ...fallbackSatellite,
            ...data,
          }));
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

  const epoch = sat.epoch_utc ? new Date(sat.epoch_utc) : new Date();
  const lla = eciToLla(sat.position, epoch);
  const speedText = sat.speed_kmh != null ? Number(sat.speed_kmh).toLocaleString() : '---';
  const heightText = sat.altitude_km != null ? Math.round(Number(sat.altitude_km)).toLocaleString() : '---';
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
