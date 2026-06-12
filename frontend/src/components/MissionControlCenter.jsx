import React, { useState } from 'react';
import ThreatCard from './ThreatCard';
import useStore from '../store/useStore';
import { apiPost, apiDelete } from '../utils/api';
import { markEdgeResolved } from '../utils/cascadeGraph';

const TABS = ['ALL', 'CRITICAL', 'WARNING', 'WATCH'];

export default function MissionControlCenter({ alerts = [] }) {
  const [activeTab, setActiveTab] = useState('ALL');
  const selectedAlertId = useStore((s) => s.selectedAlertId);
  const wsConnected = useStore((s) => s.wsConnected);
  const modelMetrics = useStore((s) => s.modelMetrics);
  const setCascadeGraph = useStore((s) => s.setCascadeGraph);
  const cascadeGraph = useStore((s) => s.cascadeGraph);

  const filteredAlerts = alerts
    .filter((a) => {
      if (activeTab === 'ALL') return true;
      const cpi = Number(a.cpi_score ?? 0);
      if (activeTab === 'CRITICAL') return cpi >= 8 || a.severity?.toUpperCase() === 'CRITICAL';
      if (activeTab === 'WARNING') return (cpi >= 5 && cpi < 8) || a.severity?.toUpperCase() === 'WARNING';
      if (activeTab === 'WATCH') return cpi < 5 && a.severity?.toUpperCase() !== 'CRITICAL' && a.severity?.toUpperCase() !== 'WARNING';
      return true;
    })
    .sort((a, b) => Number(b.cpi_score ?? 0) - Number(a.cpi_score ?? 0));

  // System status indicators
  const pipeline = wsConnected;
  const mlTrained = modelMetrics?.xgboost?.using_trained ?? false;
  const physicsOk = true; // Foster analytics always available

  const handleDecision = (decision, alert) => {
    if (decision === 'APPROVE' || decision === 'MODIFY') {
      setCascadeGraph(markEdgeResolved(cascadeGraph, alert.id));
    }
  };

  const handleLoadCascadeDemo = async () => {
    try { await apiPost('/api/simulate', { scenario: 'cascade_demo' }); } catch (_) {}
  };

  const handleSimulateCollision = async () => {
    try { await apiPost('/api/debris/simulate', {}); } catch (_) {}
  };

  const handleClearDebris = async () => {
    try { await apiDelete('/api/debris/active'); } catch (_) {}
  };

  const handleResetTime = async () => {
    try { await apiPost('/api/simulation/reset', {}); } catch (_) {}
  };

  return (
    <div className="mcc-column">
      {/* Section 1: System status */}
      <div className="mcc-section">
        <div className="mcc-section-header">
          <span className="mcc-section-title">System Status</span>
        </div>
        <div className="sys-status-row">
          <div className="sys-indicator">
            <div className={`sys-indicator-dot ${wsConnected ? 'green' : 'red'}`} />
            <div className="sys-indicator-label">BACKEND</div>
          </div>
          <div className="sys-indicator">
            <div className={`sys-indicator-dot ${pipeline ? 'green' : 'red'}`} />
            <div className="sys-indicator-label">PIPELINE</div>
          </div>
          <div className="sys-indicator">
            <div className={`sys-indicator-dot ${mlTrained ? 'green' : 'amber'}`} />
            <div className="sys-indicator-label">ML</div>
          </div>
          <div className="sys-indicator">
            <div className={`sys-indicator-dot ${physicsOk ? 'green' : 'red'}`} />
            <div className="sys-indicator-label">PHYSICS</div>
          </div>
        </div>
      </div>

      {/* Section 2: Threat Queue */}
      <div className="threat-queue">
        <div className="mcc-section-header">
          <span className="mcc-section-title">
            Threat Queue
          </span>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: alerts.length > 0 ? 'var(--alert-red)' : 'var(--text-dim)' }}>
            {alerts.length} ACTIVE
          </span>
        </div>

        {/* Filter tabs */}
        <div className="threat-filter-tabs">
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              className={`threat-tab ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Cards */}
        <div className="threat-cards-list">
          {filteredAlerts.length === 0 ? (
            <div className="threat-empty">
              {activeTab === 'ALL'
                ? 'No active conjunction alerts'
                : `No ${activeTab} alerts`}
            </div>
          ) : (
            filteredAlerts.map((alert) => (
              <ThreatCard
                key={alert.id ?? `${alert.sat1?.id}-${alert.sat2?.id}`}
                alert={alert}
                isSelected={selectedAlertId === alert.id}
                onDecision={handleDecision}
              />
            ))
          )}
        </div>
      </div>

      {/* Section 3: Quick Actions */}
      <div className="quick-actions">
        <button type="button" className="qa-btn" onClick={handleLoadCascadeDemo}>
          ▶ Load Cascade Demo
        </button>
        <button type="button" className="qa-btn" onClick={handleSimulateCollision}>
          ● Simulate Collision
        </button>
        <button type="button" className="qa-btn" onClick={handleClearDebris}>
          ✕ Clear Debris
        </button>
        <button type="button" className="qa-btn" onClick={handleResetTime}>
          ↺ Reset Time
        </button>
      </div>
    </div>
  );
}
