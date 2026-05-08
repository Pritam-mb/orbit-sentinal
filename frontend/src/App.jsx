import React, { useEffect, useRef } from 'react';
import CesiumGlobe from './components/Globe/CesiumGlobe';
import TelemetryPanel from './components/Telemetry/TelemetryPanel';
import ConjunctionMonitor from './components/ConjunctionMonitor';
import ManualControl from './components/Control/ManualControl';
import TestModePanel from './components/TestModePanel';
import useStore from './store/useStore';
import useTestMode from './hooks/useTestMode';
import './App.css';

function App() {
  const apiBaseUrl = 'http://127.0.0.1:8000';
  const wsBaseUrl = 'ws://127.0.0.1:8000';
  const setSatellites = useStore((s) => s.setSatellites);
  const setSnapshotTimestamp = useStore((s) => s.setSnapshotTimestamp);
  const setAlerts = useStore((s) => s.setAlerts);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const wsConnected = useStore((s) => s.wsConnected);
  const satellites = useStore((s) => s.satellites);
  const testActive = useTestMode((s) => s.testActive);
  const wsRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer = null;

    const bootstrapSatellites = async () => {
      try {
        const satelliteResponse = await fetch(`${apiBaseUrl}/api/satellites`);
        if (cancelled || !satelliteResponse.ok) return;

        const satelliteData = await satelliteResponse.json();
        setSnapshotTimestamp(satelliteData.timestamp || null);
        setSatellites(satelliteData.satellites || []);
      } catch (error) {
        console.error('Initial satellite bootstrap failed:', error);
      }
    };

    const bootstrapAlerts = async () => {
      try {
        const alertResponse = await fetch(`${apiBaseUrl}/api/alerts`);
        if (cancelled || !alertResponse.ok) return;

        const alertData = await alertResponse.json();
        if (!cancelled) {
          setAlerts(alertData.alerts || []);
        }
      } catch (error) {
        console.error('Initial alert bootstrap failed:', error);
      }
    };

    const connect = () => {
      if (cancelled) return;

      const ws = new WebSocket(`${wsBaseUrl}/ws/satellites`);

      ws.onopen = () => {
        console.log('WebSocket connected');
        setWsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'update') {
            setSnapshotTimestamp(data.timestamp || null);
            setSatellites(data.satellites || []);
            if (Object.prototype.hasOwnProperty.call(data, 'alerts')) {
              setAlerts(data.alerts || []);
            }
          }
        } catch (e) {
          console.error('WS parse error:', e);
        }
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        setWsConnected(false);
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    };

    bootstrapSatellites();
    bootstrapAlerts();
    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [setSatellites, setSnapshotTimestamp, setAlerts, setWsConnected]);

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>ORBITAL SENTINEL</h1>
        <div className="header-status">
          <span
            className="status-dot"
            style={{
              background: wsConnected
                ? 'var(--alert-green)'
                : 'var(--alert-red)',
            }}
          />
          <span>{wsConnected ? 'TRACKING' : 'OFFLINE'}</span>
        </div>
        <div className="header-right">
          <div className="header-meta">
            {satellites.length} OBJECTS TRACKED
          </div>
          <div className={`header-test ${testActive ? 'active' : ''}`}>
            TEST MODE: {testActive ? 'ON' : 'OFF'}
          </div>
        </div>
      </header>

      <main className="bento-grid">
        <div className="globe-panel">
          <CesiumGlobe />
          <TelemetryPanel />
        </div>

        <div className="sidebar">
          <TestModePanel />
          <ConjunctionMonitor />
          <ManualControl />
        </div>
      </main>
    </div>
  );
}

export default App;
