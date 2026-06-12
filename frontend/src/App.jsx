import React, { useEffect, useRef } from 'react';
import CesiumGlobe from './components/Globe/CesiumGlobe';
import TelemetryPanel from './components/Telemetry/TelemetryPanel';
import ConjunctionMonitor from './components/ConjunctionMonitor';
import AlertPanel from './components/Alert/AlertPanel';
import SimulationDrawer from './components/SimulationDrawer';
import MetricsDrawer from './components/MetricsDrawer';
import UplinkDownlinkPanel from './components/Control/UplinkDownlinkPanel';
import SimulationTimeControl from './components/Control/SimulationTimeControl';
import AgencyFilter from './components/Globe/AgencyFilter';
import useStore from './store/useStore';
import useTestMode from './hooks/useTestMode';
import './App.css';

const apiBaseUrl = '';
const wsBaseUrl = (window.location.origin || '').replace(/^http/, 'ws');
const alertPollMs = 30000;
const heartbeatPollMs = 20000;

function App() {
  const setSatellites = useStore((s) => s.setSatellites);
  const setSnapshotTimestamp = useStore((s) => s.setSnapshotTimestamp);
  const setAlerts = useStore((s) => s.setAlerts);
  const setCascadePlan = useStore((s) => s.setCascadePlan);
  const setHotspots = useStore((s) => s.setHotspots);
  const setDebrisClouds = useStore((s) => s.setDebrisClouds);
  const setModelMetrics = useStore((s) => s.setModelMetrics);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const wsConnected = useStore((s) => s.wsConnected);
  const satellites = useStore((s) => s.satellites);
  const testActive = useTestMode((s) => s.testActive);
  const wsRef = useRef(null);
  const alertFetchInFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer = null;
    let alertPollTimer = null;
    let heartbeatTimer = null;

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
      if (cancelled || alertFetchInFlight.current) return;

      alertFetchInFlight.current = true;
      try {
        const alertResponse = await fetch(`${apiBaseUrl}/api/alerts`);
        if (cancelled || !alertResponse.ok) return;

        const alertData = await alertResponse.json();
        if (!cancelled) {
          setAlerts(alertData.alerts || []);
          setCascadePlan(alertData.cascade_plan || null);
          setHotspots(alertData.hotspots || []);
          setDebrisClouds(alertData.debris_clouds || []);
        }
      } catch (error) {
        console.error('Initial alert bootstrap failed:', error);
      } finally {
        alertFetchInFlight.current = false;
      }
    };

    const bootstrapModelMetrics = async () => {
      if (cancelled) return;

      try {
        const response = await fetch(`${apiBaseUrl}/api/model-metrics`);
        if (cancelled || !response.ok) return;

        const metricsData = await response.json();
        if (!cancelled) {
          setModelMetrics(metricsData);
        }
      } catch (error) {
        console.error('Model metrics bootstrap failed:', error);
      }
    };

    const connect = () => {
      if (cancelled) return;

      const ws = new WebSocket(`${wsBaseUrl}/ws/satellites`);

      ws.onopen = () => {
        console.log('WebSocket connected');
        setWsConnected(true);
        heartbeatTimer = setInterval(() => {
          try {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send('ping');
            }
          } catch (error) {
            console.warn('WebSocket heartbeat failed:', error);
          }
        }, heartbeatPollMs);
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
            if (Object.prototype.hasOwnProperty.call(data, 'debris_clouds')) {
              setDebrisClouds(data.debris_clouds || []);
            }
          }
        } catch (e) {
          console.error('WS parse error:', e);
        }
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        setWsConnected(false);
        if (heartbeatTimer) {
          clearInterval(heartbeatTimer);
          heartbeatTimer = null;
        }
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
    bootstrapModelMetrics();
    connect();

    alertPollTimer = setInterval(() => {
      bootstrapAlerts();
    }, alertPollMs);

    return () => {
      cancelled = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      if (alertPollTimer) {
        clearInterval(alertPollTimer);
      }
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [setSatellites, setSnapshotTimestamp, setAlerts, setCascadePlan, setHotspots, setDebrisClouds, setModelMetrics, setWsConnected]);

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
          <button 
            type="button" 
            className={`header-test ${testActive ? 'active' : ''}`}
            onClick={() => useTestMode.getState().setTestActive(!testActive)}
          >
            TEST MODE: {testActive ? 'ON' : 'OFF'}
          </button>
        </div>
      </header>

      <main className="bento-grid">
        <div className="globe-panel">
          <CesiumGlobe />
          <TelemetryPanel />
        </div>

        <div className="sidebar">
          <div className="sidebar-top">
            <AgencyFilter />
            <SimulationTimeControl />
            <AlertPanel />
            <UplinkDownlinkPanel />
          </div>
        </div>
      </main>

      <MetricsDrawer />
      <SimulationDrawer />
    </div>
  );
}

export default App;
