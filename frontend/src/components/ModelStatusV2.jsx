import React, { useEffect, useState, useRef } from 'react';
import { apiGet } from '../utils/api';

const POLL_MS = 30_000;

const TOP_FEATURES = ['miss_dist', 'rel_vel', 'altitude', 'tle_age'];

export default function ModelStatusV2() {
  const [metrics, setMetrics] = useState(null);
  const [cascadeStatus, setCascadeStatus] = useState(null);
  const [sampleHistory, setSampleHistory] = useState([]);
  const mountedRef = useRef(true);

  const fetchAll = async () => {
    if (!mountedRef.current) return;
    try {
      const [m, c] = await Promise.all([
        apiGet('/api/model-metrics').catch(() => null),
        apiGet('/api/cascade/status').catch(() => null),
      ]);
      if (!mountedRef.current) return;
      if (m) setMetrics(m);
      if (c) setCascadeStatus(c);
      setSampleHistory((prev) => {
        const count = m?.xgboost?.training_samples ?? m?.training_samples ?? 0;
        const ts = new Date().toISOString().substring(11, 19);
        return [...prev, { ts, count }].slice(-10);
      });
    } catch (_) {}
  };

  useEffect(() => {
    mountedRef.current = true;
    fetchAll();
    const id = setInterval(fetchAll, POLL_MS);
    return () => { mountedRef.current = false; clearInterval(id); };
  }, []);

  const xgb = metrics?.xgboost ?? {};
  const lstm = metrics?.lstm ?? {};
  const gnn = metrics?.gnn ?? {};
  const rlhf = metrics?.rlhf ?? {};
  const meta = metrics?.meta_propagator ?? {};

  const usingTrained = xgb.using_trained ?? false;
  const trainSamples = xgb.training_samples ?? 0;
  const precision = xgb.precision ?? null;
  const recall = xgb.recall ?? null;
  const f1 = xgb.f1 ?? null;
  const predictions = xgb.predictions_today ?? 0;
  const highRisk = xgb.high_risk_count ?? 0;

  const lstmTrained = lstm.trained ?? false;
  const lstmSeqs = lstm.training_sequences ?? 0;
  const lstmSats = lstm.satellites ?? 0;
  const lstmErr = lstm.mean_error_km ?? null;
  const bufferFill = lstm.buffer_fill ?? 0;
  const BUFFER_THRESHOLD = 500;

  const gnnType = gnn.model_type ?? 'DETERMINISTIC';
  const torchGeo = gnn.torch_geometric ?? null;
  const cascadePred = cascadeStatus?.cascade_predictions ?? gnn.cascade_predictions ?? 0;
  const meanDepth = cascadeStatus?.mean_cascade_depth ?? gnn.mean_cascade_depth ?? 0;

  const rlhfDecisions = rlhf.decisions_collected ?? 0;
  const approvalRate = rlhf.approval_rate ?? null;
  const rlhfRounds = rlhf.rounds_completed ?? 0;
  const rlhfRoundRates = rlhf.round_rates ?? [];

  const metaSats = meta.satellites_with_corrections ?? 0;
  const metaImprovement = meta.mean_improvement_pct ?? 0;
  const metaCorrections = meta.total_corrections ?? 0;

  const conjSamples = metrics?.conjunction_samples ?? trainSamples;
  const readyToRetrain = conjSamples >= BUFFER_THRESHOLD;

  // Sparkline for sample history (simple inline SVG)
  const maxCount = Math.max(...sampleHistory.map((s) => s.count), 1);
  const sparkW = 260;
  const sparkH = 28;

  const sparkPoints = sampleHistory
    .map((s, i) => {
      const x = sampleHistory.length < 2
        ? sparkW / 2
        : (i / (sampleHistory.length - 1)) * sparkW;
      const y = sparkH - (s.count / maxCount) * (sparkH - 4) - 2;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className="model-status-v2">
      {/* Section 1: XGBoost */}
      <div className="msv2-section">
        <div className="msv2-section-title">XGBoost Risk Classifier</div>
        <div className={`msv2-model-badge ${usingTrained ? 'trained' : 'heuristic'}`}>
          {usingTrained ? '● TRAINED' : '◌ HEURISTIC'}
        </div>
        <div className="msv2-row"><span>Training samples</span><span>{trainSamples.toLocaleString()}</span></div>
        {usingTrained && precision != null && (
          <div className="msv2-row">
            <span>Precision / Recall / F1</span>
            <span>{precision.toFixed(2)} / {recall.toFixed(2)} / {f1.toFixed(2)}</span>
          </div>
        )}
        <div className="msv2-row"><span>Predictions today</span><span>{predictions}</span></div>
        <div className="msv2-row"><span>High-risk detections</span><span>{highRisk}</span></div>

        {/* Feature importance bars */}
        <div className="msv2-feature-bars">
          {TOP_FEATURES.map((feat, i) => {
            const imp = xgb.feature_importance?.[feat] ?? (0.35 - i * 0.06);
            return (
              <div className="msv2-feature-bar-row" key={feat}>
                <span className="msv2-feature-name">{feat}</span>
                <div className="msv2-bar-container">
                  <div className="msv2-bar-fill" style={{ width: `${Math.min(imp * 100, 100)}%` }} />
                </div>
                <span className="msv2-feature-val">{(imp * 100).toFixed(0)}%</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Section 2: LSTM */}
      <div className="msv2-section">
        <div className="msv2-section-title">LSTM Trajectory Predictor</div>
        <div className={`msv2-model-badge ${lstmTrained ? 'trained' : 'heuristic'}`}>
          {lstmTrained ? '● TRAINED' : '◌ LINEAR EXTRAPOLATION'}
        </div>
        <div className="msv2-row">
          <span>Training sequences</span>
          <span>{lstmSeqs} from {lstmSats} satellites</span>
        </div>
        {lstmErr != null && (
          <div className="msv2-row"><span>Mean prediction error</span><span>{lstmErr.toFixed(2)} km</span></div>
        )}
        <div className="msv2-row">
          <span>Buffer fill</span>
          <span>{bufferFill} / {BUFFER_THRESHOLD}</span>
        </div>
        <div className="msv2-bar-container">
          <div className="msv2-bar-fill" style={{ width: `${Math.min((bufferFill / BUFFER_THRESHOLD) * 100, 100)}%` }} />
        </div>
      </div>

      {/* Section 3: GNN */}
      <div className="msv2-section">
        <div className="msv2-section-title">GNN Cascade Model</div>
        <div className={`msv2-model-badge ${gnnType === 'GAT' ? 'trained' : 'heuristic'}`}>
          {gnnType === 'GAT' ? '● GAT' : '◌ DETERMINISTIC'}
        </div>
        <div className="msv2-row">
          <span>torch-geometric</span>
          <span className={torchGeo ? '' : ''} style={{ color: torchGeo ? 'var(--alert-green)' : 'var(--text-dim)' }}>
            {torchGeo ? `INSTALLED ${torchGeo}` : 'NOT INSTALLED'}
          </span>
        </div>
        <div className="msv2-row"><span>Cascade predictions</span><span>{cascadePred}</span></div>
        <div className="msv2-row"><span>Mean cascade depth</span><span>{Number(meanDepth).toFixed(1)}</span></div>
      </div>

      {/* Section 4: Meta-Propagator + RLHF */}
      <div className="msv2-section">
        <div className="msv2-section-title">Meta-Propagator + RLHF</div>

        <div className="msv2-row"><span>Sats with corrections</span><span>{metaSats}</span></div>
        <div className="msv2-row"><span>Mean improvement vs SGP4</span><span>{metaImprovement.toFixed(1)}%</span></div>
        <div className="msv2-row"><span>Total corrections</span><span>{metaCorrections}</span></div>

        <div style={{ height: 6 }} />

        <div className="msv2-row"><span>RLHF decisions</span><span>{rlhfDecisions}</span></div>
        <div className="msv2-row">
          <span>Approval rate</span>
          <span>
            {approvalRate != null ? `${(approvalRate * 100).toFixed(0)}%` : '—'}
          </span>
        </div>
        <div className="msv2-row"><span>RLHF rounds</span><span>{rlhfRounds}</span></div>

        {/* Approval rate sparkline dots */}
        {rlhfRoundRates.length > 0 && (
          <div className="msv2-rlhf-dots">
            {rlhfRoundRates.slice(-10).map((r, i) => (
              <div
                key={i}
                className="msv2-rlhf-dot"
                style={{ height: `${Math.max(2, r * 28)}px` }}
                title={`Round ${i + 1}: ${(r * 100).toFixed(0)}%`}
              />
            ))}
          </div>
        )}
      </div>

      {/* Bottom: data accumulation */}
      <div className="msv2-section">
        <div className="msv2-section-title">Training Data Accumulation</div>
        <div className="msv2-row"><span>Conjunction samples</span><span>{conjSamples.toLocaleString()}</span></div>
        <div className="msv2-row">
          <span>Ready to retrain</span>
          <span style={{ color: readyToRetrain ? 'var(--alert-green)' : 'var(--text-dim)' }}>
            {readyToRetrain ? 'YES' : `NO (${conjSamples}/${BUFFER_THRESHOLD})`}
          </span>
        </div>

        {/* Sample count sparkline */}
        {sampleHistory.length > 1 && (
          <svg className="msv2-sparkline" width={sparkW} height={sparkH} viewBox={`0 0 ${sparkW} ${sparkH}`}>
            <polyline
              points={sparkPoints}
              fill="none"
              stroke="var(--alert-green)"
              strokeWidth={1.5}
              opacity={0.7}
            />
          </svg>
        )}
      </div>
    </div>
  );
}
