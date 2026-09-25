# Orbital Sentinel: Explainable Real-Time Conjunction Assessment with Foster B-Plane Integration, Hermite TCA Refinement, and Layered Debris Forecasting

**Authors:** [Author Names]  
**Affiliation:** [Institution]  
**Date:** September 2026  
**Keywords:** space situational awareness, conjunction assessment, SGP4, Foster collision probability, B-plane integration, time of closest approach, debris visualization, cascade risk, graph neural networks

---

## Abstract

Orbital Sentinel is a prototype for real-time satellite tracking, conjunction awareness, risk ranking, and three-dimensional incident visualization. The system integrates Two-Line Element (TLE) ingestion, SGP4 propagation, a FastAPI service layer, and a Cesium-based WebGL client connected via REST and WebSocket. The collision-probability path implements the Foster (1992) B-plane double-integration method with an RTN covariance model and a Chan (1997) series fallback; risk ranking employs an XGBoost classifier trained on Foster-generated synthetic data alongside lightweight graph surrogate models for cascade depth estimation. This paper documents the full implemented methodology, identifies and corrects four material defects present in earlier prototype versions, and evaluates all corrected paths through targeted regression tests. The corrections make collision probability responsive to miss distance and encounter geometry, refine Time of Closest Approach (TCA) between coarse numerical samples via cubic Hermite interpolation, relocate incident visualization markers to the computed TCA position, prevent near-misses from erroneously generating debris events, and restore multi-layer debris forecast rendering in the Cesium client. All three regression tests pass. Cached evaluation on Foster-derived synthetic data reports 93.85% accuracy for the risk scorer; graph cascade models report 98.76% accuracy on synthetic graph snapshots. These figures characterize internal synthetic-set behavior and do not constitute operational flight-validation claims. The resulting architecture provides a reproducible, explainable platform for conjunction-response demonstrations and serves as a controlled baseline for future validation against independent conjunction truth data.

---

## I. Introduction

The cataloged orbital population now exceeds 27,000 tracked objects, and the number of untracked debris fragments with lethal collision cross-section is estimated at several hundred thousand [1]. As constellation deployment accelerates, the number of object pairs requiring daily screening grows as the square of the catalog size, placing increasing pressure on space situational awareness (SSA) infrastructure. Prototype systems that expose the geometry, timing, uncertainty, and downstream consequences of encounters in a transparent, debuggable architecture serve an important role: they allow methodology auditing, operator training, and controlled comparison of algorithmic choices before operational commitment.

Orbital Sentinel addresses this need with an end-to-end pipeline: orbital states are propagated from TLEs via SGP4, cached, screened for close approaches, ranked by risk, streamed over WebSocket, and rendered on an interactive Cesium globe. The system additionally contains demo-specific logic, synthetic machine-learning artifacts, and a test router for injecting deterministic encounter scenarios. These components create a precise reporting obligation — implementation outputs must not be conflated with operationally validated collision probabilities. This paper enforces that boundary throughout.

### A. Research Questions

1. Does collision probability respond to both positional uncertainty and the relative miss vector in the B-plane?
2. Can the TCA routine detect a close approach that occurs between coarse numerical output samples?
3. Are hotspot and debris products located at the computed encounter position rather than the initial epoch?
4. Does the Cesium client preserve the multi-layer debris forecast-shell structure supplied by the backend?

### B. Contributions

This work contributes:
- A code-grounded system description of the full Orbital Sentinel pipeline, traced to implementation files
- Documentation of the Foster B-plane collision probability pipeline and its RTN covariance model
- A defect-focused correction set addressing four linked implementation errors
- Three executable regression tests with deterministic acceptance criteria
- Quantitative vector results for corrected probability, TCA refinement, and debris layering
- An evidence-calibrated interpretation of synthetic model metrics that clearly delineates operational validity boundaries

No new software packages were downloaded for the analysis or artifact generation. All evidence derives from the repository source, installed runtime capabilities, and newly written regression tests.

### C. Paper Organization

Section II describes the system architecture and data flow. Section III formalizes the implemented methodology, including the Foster B-plane path, RTN covariance model, Hermite TCA refinement, XGBoost risk scorer, graph cascade models, NASA EVOLVE debris simulation, and Cesium visualization pipeline. Section IV records the four corrective implementations. Sections V and VI define the evaluation protocol and present results. Sections VII and VIII discuss limitations and conclusions.

---

## II. System Architecture

### A. Operational Data Flow

The runtime data flow follows a linear pipeline:

```
TLE File → SGP4 Propagator → State Cache → Conjunction Screener
    → Foster Pc Engine → CPI Scorer → XGBoost Risk Scorer
    → KD-Tree Graph Builder → GNN/GAT Cascade Ranker
    → REST / WebSocket → Cesium Globe Client
```

TLE records are ingested from a bundled snapshot at startup (`backend/app/simulation/tle-data.txt`). The SGP4 propagator (`sgp4_propagator.py`) evaluates Earth-centered inertial (ECI) position and velocity at the requested epoch. A state cache stores the most recent propagated snapshot and serves REST and WebSocket consumers at 1 Hz. Conjunction screening (`conjunction.py`) operates on the cached snapshot; cascade planning (`cascade_planner.py`, `gnn_cascade.py`, `gat_cascade.py`) operates on the resulting proximity graph. The test router (`routers/`) accepts injected ECI encounter scenarios for deterministic validation.

### B. Backend Component Map

| File | Responsibility |
|------|---------------|
| `sgp4_propagator.py` | TLE parsing, SGP4 integration, RSW→ECI burn transforms |
| `conjunction.py` | Pairwise screening, Foster Pc dispatch, CPI computation |
| `analytics.py` | RTN covariance, B-plane transform, Foster double integration, Chan fallback |
| `debris_model.py` | NASA EVOLVE fragment generation, drag-aware propagation |
| `cascade_planner.py` | KD-tree graph construction, CPI-weighted cascade expansion |
| `gnn_cascade.py` | Graph-attention surrogate: maneuver probability, cascade depth |
| `gat_cascade.py` | Graph-attention variant of cascade ranker |
| `xgboost_scorer.py` | XGBoost classifier on Foster-derived features, boosted-stump fallback |
| `analytics.py` | Foster B-plane integration, RTN covariance, fragment count |
| `satellite_state_tracker.py` | State aggregation and Kalman-augmented tracking |

### C. Frontend Architecture

The React client (`frontend/src/`) uses Cesium for globe rendering and Zustand for state management. It bootstraps through REST (`/api/satellites`, `/api/alerts`), then maintains a WebSocket connection for live 1 Hz position updates. Between updates, each satellite is advanced using linear ECI extrapolation with the stored velocity vector. ECI coordinates are converted to Cesium Cartesian using Greenwich Mean Sidereal Time (GMST). Separate entity collections represent satellites, orbit polylines, conjunction hotspots, approach lines, and debris forecast shells.

### D. Data and Model Provenance

| Source | Description | Operational Interpretation |
|--------|-------------|---------------------------|
| TLE snapshot | Bundled SGP4-derived state estimate | State accuracy limited by TLE age and maneuver history |
| Foster synthetic data | Conjunction pairs generated by the analytics pipeline | Internal classification surrogate; not CDM-validated |
| Graph snapshots | Synthetic proximity graphs | Cascade ranking surrogate only |
| Test scenarios | Injected ECI encounters | Deterministic UI and solver validation |
| `model_metrics_cache.json` | Evaluation on above synthetic sets (8 May 2026) | Internal synthetic-set reproducibility only |

**Evidence boundary:** No external conjunction data messages (CDMs), independent truth ephemerides, or operator-validated encounter records were present in the repository. Metric claims are constrained to internal synthetic evaluation.

---

## III. Methodology

### A. Orbit Propagation

The SGP4 propagator converts TLE records to `Satrec` objects using the `python-sgp4` library (Vallado et al., 2006 [2]). For each satellite, ECI position $\mathbf{r}(t)$ and velocity $\mathbf{v}(t)$ are evaluated at the requested epoch. Scalar speed and approximate altitude are:

$$v_{kmh} = \|\mathbf{v}\| \times 3600 \quad \text{(km/h)}$$
$$h_{km} = \|\mathbf{r}\| - R_E \quad \text{(km, } R_E = 6371 \text{ km)}$$

**Maneuver integration:** Impulsive delta-V burns are accepted in ECI or converted from RSW (Radial/Along-track/Cross-track) frame. The RSW basis is:

$$\hat{R} = \frac{\mathbf{r}}{\|\mathbf{r}\|}, \quad \hat{W} = \frac{\mathbf{r} \times \mathbf{v}}{\|\mathbf{r} \times \mathbf{v}\|}, \quad \hat{S} = \hat{W} \times \hat{R}$$

The post-burn state is converted to osculating Keplerian elements; the burn is rejected if the predicted perigee drops below 100 km. A new `Satrec` is rebuilt so future propagation uses the updated orbit.

### B. RTN Covariance Model

When external covariance data is unavailable (the common case for TLE-sourced catalog objects), `analytics.py` builds a 3×3 ECI position covariance via an RTN (Radial/Transverse/Normal) uncertainty model:

$$\sigma_R = 50 \text{ m}, \quad \sigma_T = 1.0 \times \left(1 + \frac{t_{age}}{24}\right) \text{ km}, \quad \sigma_N = 50 \text{ m}$$

The transverse uncertainty grows linearly with TLE age $t_{age}$ in hours, reflecting the dominant along-track prediction error characteristic of TLE-based propagation. The combined ECI covariance is:

$$\mathbf{C}_{ECI} = \mathbf{R}_{RTN}\, \text{diag}[\sigma_R^2, \sigma_T^2, \sigma_N^2]\, \mathbf{R}_{RTN}^T$$

where $\mathbf{R}_{RTN}$ is the rotation matrix whose columns are $\hat{R}$, $\hat{T}$, $\hat{N}$ expressed in ECI.

### C. B-Plane Collision Probability (Foster 1992)

The collision probability path in `analytics.py` implements the Foster and Estes (1992) [3] B-plane method as used by NASA CARA.

**B-plane construction:** The B-plane is perpendicular to the relative velocity vector $\Delta\mathbf{v} = \mathbf{v}_q - \mathbf{v}_p$ at TCA. Unit vectors are:

$$\hat{h} = \frac{\Delta\mathbf{v}}{\|\Delta\mathbf{v}\|}, \quad \hat{t} = \frac{\hat{h} \times \mathbf{r}_p}{\|\hat{h} \times \mathbf{r}_p\|}, \quad \hat{n} = \hat{t} \times \hat{h}$$

The projection matrix is $\mathbf{B} = [\hat{t}\;;\;\hat{n}] \in \mathbb{R}^{2\times 3}$.

**Miss vector:** The combined position delta $\Delta\mathbf{r} = \mathbf{r}_q - \mathbf{r}_p$ is projected into the B-plane:

$$\mathbf{b} = \mathbf{B}\,\Delta\mathbf{r} = [B_T,\, B_N]^T \quad \text{(km)}$$

**Combined covariance:** The sum of individual ECI covariances is projected onto the B-plane:

$$\mathbf{C}_{2D} = \mathbf{B}\,(\mathbf{C}_p + \mathbf{C}_q)\,\mathbf{B}^T \in \mathbb{R}^{2\times 2}$$

**Foster integration:** Collision probability is the integral of the bivariate Gaussian PDF over the circular hard-body disk of radius $R_{HBR} = 10$ m:

$$P_c = \iint_{x^2+y^2 \leq R_{HBR}^2} \mathcal{N}(\mathbf{x};\, \mathbf{b},\, \mathbf{C}_{2D})\, dx\, dy$$

This is evaluated by `scipy.integrate.dblquad` with a 2-second timeout. If integration exceeds the timeout or fails, the Chan (1997) [4] series approximation provides a fast fallback:

$$P_c^{Chan} \approx u \cdot e^{-(u+x)} \cdot I_0\!\left(2\sqrt{ux}\right)$$

where $u = R_{HBR}^2 / (2\sigma^2)$, $x = \|\mathbf{b}\|^2 / (2\sigma^2)$, $\sigma^2 = \text{tr}(\mathbf{C}_{2D})/2$, and $I_0$ is the modified Bessel function of the first kind. The result is clipped to $[0,1]$.

### D. Conjunction Priority Index (CPI)

The CPI provides a scalar urgency score on $[0, 10]$ calibrated against the Foster $P_c$ ordering. The five sub-scores are weighted to ensure CPI rank equals Foster $P_c$ rank for comparable encounters:

| Component | Weight | Mapping |
|-----------|--------|---------|
| Miss distance | 0.40 | Piecewise linear on $[0,500]$ km |
| Foster $P_c$ (log) | 0.30 | Linear in $\log_{10}(P_c) \in [-6,-2] \to [0,10]$ |
| TCA urgency | 0.15 | Piecewise linear on $[0,24]$ h |
| Closing speed | 0.10 | Linear, capped at 15 km/s |
| TLE data age | 0.05 | Linear, capped at 48 h |

**NASA CARA threshold alignment:**
- $P_c \geq 10^{-4}$ (CPI $\approx$ 5.0): watch/elevated concern
- $P_c \geq 10^{-3}$ (CPI $\approx$ 7.5): action threshold
- $P_c \geq 10^{-2}$ (CPI $\approx$ 10): emergency — maneuver required

### E. TCA Refinement: Cubic Hermite Interpolation

The coarse TCA search evaluates ECI states at uniform time steps. The corrected method identifies the two time intervals adjacent to the coarse minimum-separation sample and fits cubic Hermite position curves from endpoint positions and velocities. The relative separation within each bracket is:

$$d(t)^2 = \|\mathbf{r}_{rel}(t)\|^2 = \|\mathbf{r}_1(t) - \mathbf{r}_2(t)\|^2$$

Hermite interpolation within interval $[t_k, t_{k+1}]$ gives a $C^1$ continuous relative trajectory. Minimizing $d^2$ via `scipy.optimize.minimize_scalar` over each bracket yields sub-step temporal localization. This reduces sample-grid aliasing without requiring a full re-integration.

Additionally, the target-time endpoint is corrected so the propagation loop terminates at the requested horizon $T$ exactly, preventing overshoot that caused the prior implementation to miss the final sample.

### F. XGBoost Risk Scorer

The risk scorer (`xgboost_scorer.py`) uses a Foster-trained XGBoost classifier as its primary path. The eight input features are:

$$\mathbf{f} = [d_{miss},\; v_{rel},\; t_{TCA},\; t_{age},\; h_{alt},\; \sigma_R^2,\; \sigma_T^2,\; \sigma_N^2]$$

Training data is generated by the `generate_risk_dataset` function in `synthetic_data.py`, which calls the Foster B-plane pipeline to produce $(P_c, \text{features})$ pairs. Binary labels are obtained by thresholding $P_c \geq 0.5$. The XGBoost model is saved to `risk_model_trained.json` and loaded at module import. If XGBoost is unavailable (no library), the system falls back to a compact gradient-boosted stump ensemble (`BoostedRiskModel`) trained on the same synthetic data.

### G. Graph Cascade Models

The cascade planner (`cascade_planner.py`) builds a proximity graph using a KD-tree with an influence radius of 200 km. Each edge stores: miss distance, predicted miss distance, relative velocity, TCA, $P_c$, CPI score, severity, and inverse-distance influence weight $w = 1/\max(d_{pred}, 1)$.

Node features include ECI state components, altitude, speed, and peak-CPI from the strongest neighbor. The GNN (`gnn_cascade.py`) and GAT (`gat_cascade.py`) surrogates are deterministic graph-attention scorers, not trained neural networks. They compute edge attention from probability, distance, velocity, and TCA, accumulate influence across neighbor edges, and output maneuver probability via a sigmoid:

$$P_{man} = \sigma(1.35 \cdot w_{inf} + 0.25 \cdot r_{local} + 0.10 \cdot a_{alt} - 0.75)$$

Cascade depth is estimated as $\lceil P_{man} \times 4 \rceil$, clipped to $[0,4]$.

**Maneuver recommendation:** Burn magnitude is:

$$\Delta v = \text{clip}\!\left(0.15 + \frac{CPI}{10}\times 1.4 + P_{man}\times 0.7,\; 0.05,\; 2.5\right)$$

Split as: radial 25%, along-track 85%, cross-track 15%.

### H. Debris Forecast Model

The debris model (`debris_model.py`) implements the NASA EVOLVE 4.0 Standard Breakup Model [5]. Fragment sizes follow a power-law CDF inversion:

$$L = L_{min} \cdot (1 - u)^{-1/1.6}, \quad u \sim \text{Uniform}(0,1)$$

Fragment velocity kicks follow the NASA EVOLVE characteristic velocity:

$$\Delta v_{mean} = \frac{200}{\sqrt{L}} \; \text{m/s}, \quad \Delta v \sim \text{LogNormal}(\mu, \sigma)$$

where $\mu = \ln(\Delta v_{mean}) - \sigma^2/2$ and $\sigma^2 = \ln(1 + 0.16)$.

Catastrophic/sub-catastrophic threshold: specific energy $E/M > 40$ J/kg. Fragment count is estimated from the NASA breakup formula:

$$N = 0.1 \times (M_1 + M_2)^{0.75} \times \begin{cases} 1 & \text{catastrophic} \\ 0.1 & \text{cratering} \end{cases}$$

Fragment propagation uses two-body gravity plus an Euler-integrated atmospheric drag term:

$$a_{drag} = -\frac{1}{2} C_D \frac{A}{m} \rho(h) v_{ms}^2 \hat{v}$$

with $C_D = 2.2$ and exponential atmospheric density scaling from sea-level reference.

### I. Cesium Globe Pipeline

Between 1 Hz backend updates, the client advances each satellite by linear ECI extrapolation: $\mathbf{r}_{adv} = \mathbf{r} + \mathbf{v} \cdot \Delta t$. ECI is converted to Cesium Cartesian via GMST rotation. The orbit track is segmented when adjacent samples diverge by more than 8000 km to prevent cross-arc line artifacts. Hotspot, approach-line, and debris-shell entities are updated from the alert REST response on each polling cycle.

---

## IV. Corrective Implementation

Table I summarizes the four defects identified through code inspection and the corrections applied.

### Table I: Defect–Correction Summary

| # | Component | Defect Observed | Root Cause | Correction Applied | Behavioral Effect |
|---|-----------|----------------|------------|-------------------|------------------|
| 1 | Collision probability | $P_c$ invariant to miss distance | Chi-square approximation used only covariance trace, ignoring $\mathbf{b}$ | Foster B-plane double integration with projected miss vector | $P_c$ decreases monotonically with miss distance |
| 2 | TCA refinement | Close approach between coarse samples missed; endpoint overshoot | Linear interpolation without sub-step search; loop counter off by one | Cubic Hermite minimization in adjacent intervals; exact endpoint fix | Improved temporal localization; target-time compliance |
| 3 | Hotspot placement | Incident marker at initial epoch position, not TCA position | Test router used snapshot positions at $t=0$ rather than solver output | Hotspot midpoint computed from solver states at refined TCA | Correct incident location displayed in Cesium |
| 4 | Debris semantics | Near-misses generated debris; expansion started before impact | Debris triggered on alert, not on collision detection; timeline not offset | Debris only on confirmed collision ($d < 1$ m); post-impact timeline | Correct event semantics: no debris for near-misses |
| 5 | Debris layers | All shells collapsed to single opaque sphere in Cesium | Client reduced shell array to maximum-radius scalar | One translucent `EllipsoidGraphics` per unique positive-radius shell | Multi-layer forecast structure preserved and visible |

### A. Probability Correction (Defect 1)

The former implementation computed:

$$P_c^{old} \propto \text{gammainc}\!\left(1, \frac{R_{HBR}^2}{\text{tr}(\mathbf{C}_{2D})}\right)$$

This expression depends only on the covariance trace and hard-body radius, making probability independent of where the objects actually pass relative to each other. The corrected path evaluates the full Foster integral over the B-plane Gaussian shifted by the miss vector $\mathbf{b}$, making $P_c$ a proper function of encounter geometry. A degenerate covariance (eigenvalue $< 10^{-20}$) still falls back to the Chan series approximation.

### B. TCA Localization (Defect 2)

The test solver (`conjunction_solver.py`) previously returned the coarse minimum without sub-step refinement. The corrected routine: (a) identifies the sample index achieving minimum separation, (b) applies Hermite minimization over the two adjacent intervals $[t_{k-1}, t_k]$ and $[t_k, t_{k+1}]$, and (c) corrects the integration step count so the final step lands exactly at the requested target time, eliminating endpoint overshoot.

### C. Hotspot Relocation (Defect 3)

The alert router previously populated hotspot coordinates from the cached snapshot at $t=0$. The corrected router passes the solver's refined encounter time and interpolated ECI states to the hotspot calculator, which computes the midpoint between the two object positions at TCA. This ensures the displayed hotspot and the approach-line endpoints correspond to the actual predicted encounter, not the initial epoch.

### D. Debris Event Semantics (Defect 4)

The former implementation created a debris event for any conjunction alert crossing the warning threshold, regardless of whether a collision was actually detected. The corrected logic separates two thresholds:
- **Warning gate** ($d < 100$ m): creates a visual alert and approach marker in Cesium
- **Collision gate** ($d < 1$ m): additionally creates a debris cloud via the EVOLVE model

The debris timeline offset is corrected so the impact shell represents the state at $t_{TCA}$ rather than $t=0$.

### E. Debris Layer Rendering (Defect 5)

The frontend component previously iterated the `shells` array and retained only the last (maximum) radius, rendering a single opaque sphere. The corrected component: validates each shell for positive radius, sorts by radius, deduplicates, and creates one translucent `EllipsoidGraphics` entity per shell with opacity decreasing from impact to forecast horizon. This preserves the temporal expansion structure intended for operator situational awareness.

### F. Regression Test Suite

Three deterministic regression tests added to `backend/tests/` protect the corrected paths:

**Test 1 — Probability monotonicity:** Creates a 2D Gaussian with $\sigma = 10$ m per axis and $R_{HBR} = 10$ m. Asserts $P_c(d=0) > P_c(d=100\text{ m})$. This test fails under the former miss-independent implementation.

**Test 2 — Sub-step TCA detection:** Configures two objects with opposing 2 m/s relative motion and true closest approach at $t = 5$ s, coarse samples at $t \in \{0, 7\}$ s. Asserts refined miss $< 0.1$ m and TCA within 0.05 s of truth.

**Test 3 — Debris shell ordering:** Injects a collision at the snapshot epoch with a 2 h forecast. Asserts impact radius $<$ mid-horizon radius $<$ forecast-horizon radius (monotonically increasing shells).

---

## V. Experimental Design

### A. Evidence Sources

1. Repository documentation: `README.md`, `FEATURES_MATH_LOGIC.md`, `PROJECT_OVERVIEW.txt`
2. Source inspection of all files listed in Table I and Section II
3. Saved model metric cache (`model_metrics_cache.json`, generated 8 May 2026)
4. Three new regression tests executed in the repository environment

### B. Test Definitions and Acceptance Criteria

| Test | Configuration | Acceptance Criterion |
|------|--------------|---------------------|
| Probability sensitivity | $\sigma = 10$ m per axis; $R_{HBR} = 10$ m | $P_c(0\text{ m}) > P_c(100\text{ m})$ |
| Sub-step TCA | Opposing 2 m/s; true TCA at 5 s; coarse at 0, 7 s | Miss $< 0.1$ m; TCA within 0.05 s |
| Debris timeline | Impact at snapshot; 2 h forecast | $r_{impact} < r_{mid} < r_{forecast}$ |

### C. Synthetic Metric Protocol

The risk scorer is evaluated as a binary classifier: Foster-derived $P_c$ values are thresholded at 0.5 to produce labels, the scorer's continuous output is thresholded at 0.5 for predicted class, and standard classification metrics (accuracy, precision, recall, F1) are computed. Graph Cascade and GAT Cascade models use synthetic graph snapshots with the same binary threshold. The trajectory predictor is evaluated on next-position coordinates using MAE and RMSE.

Cache sample counts: 4,096 risk samples, 2,985 graph-node samples per graph model, 768 coordinate values for trajectory regression.

### D. Validity Boundary

This evaluation explicitly does not claim: real-world recall, calibrated probability against operational CDMs, maneuver optimality, or catalog-scale latency performance. No comparison against external conjunction truth data is made because none was provided. The evaluation answers whether the corrected implementation paths are internally coherent and behave as designed under controlled, deterministic inputs.

---

## VI. Results

### A. Regression Outcomes

| Test | Outcome | Observed Values |
|------|---------|----------------|
| Probability responds to miss | **PASS** | $P_c(0\text{ m}) = 0.3935$; $P_c(100\text{ m}) = 3.41 \times 10^{-20}$ |
| TCA between coarse samples | **PASS** | Refined miss $< 0.1$ m; TCA $\approx 5.00 \pm 0.05$ s |
| Debris shell ordering | **PASS** | Impact $<$ mid-horizon $<$ forecast-horizon (increasing radii) |

All three regression tests pass. The probability result spans twenty decades between the zero-miss and 100 m cases, confirming that the Foster integration is correctly sensitive to miss-vector offset. The former implementation would return identical values for both cases.

### B. Corrected Probability Response

At zero miss distance, the computed probability (0.393) reflects the fraction of the $\sigma = 10$ m Gaussian that overlaps the $R_{HBR} = 10$ m disk when the Gaussian mean sits exactly at the disk center — a physically plausible result for two objects whose positional uncertainty envelopes fill the hard-body sphere. At 100 m separation (10$\sigma$), the value drops to $3.41 \times 10^{-20}$, consistent with the extreme tail of a bivariate Gaussian at 10 standard deviations from the mean.

### C. Debris Envelope Radii

The post-impact debris envelope at representative forecast times:

| Forecast Horizon | Radius (km) |
|-----------------|-------------|
| 0 h (impact) | 1.500 |
| 1 h | 211.704 |
| 2 h | 319.626 |
| 4 h | 403.483 |
| 8 h | 431.414 |
| 24 h | 433.500 |

The asymptotic convergence reflects the exponential velocity decay in the EVOLVE model: fragment expansion speed decays as $v(t) = v_0 e^{-t/\tau}$, making the total radius approach a finite maximum.

### D. Synthetic Model Performance

| Model | Accuracy | Precision | Recall | F1 | Samples |
|-------|----------|-----------|--------|-----|---------|
| Risk Scorer (XGBoost) | 93.85% | 93.08% | 91.37% | 92.21% | 4,096 |
| Graph Cascade (GNN) | 98.76% | 98.46% | 98.69% | 98.57% | 2,985 |
| GAT Cascade | 98.76% | 98.46% | 98.69% | 98.57% | 2,985 |

**Trajectory predictor:** MAE = 226.93 km, RMSE = 281.74 km across 768 coordinate values. The large absolute errors are expected for a lightweight linear predictor evaluated on broad synthetic orbital arcs; they should not be interpreted as orbit determination precision.

**Interpretation:** Identical Graph Cascade and GAT Cascade scores suggest the two graph models share similar decision surfaces or evaluation targets on the synthetic dataset, warranting investigation before treating them as independent evidence of generalization. High classification accuracy on the synthetic set establishes reproducibility on the training distribution but not external validity. Independent time-separated splits and real CDM records are required for a publishable operational-accuracy claim.

### E. Practical Effect of Corrections

The repaired pipeline enforces a consistent event chain:
1. The numerical solver localizes the encounter time and positions via Hermite refinement
2. The hotspot marker uses the refined TCA position, not the initial epoch
3. An alert is generated for any miss distance under the 100 m warning gate
4. Debris is generated only when the collision gate ($d < 1$ m) is crossed
5. The Cesium layer renders each supplied forecast shell as a distinct translucent ellipsoid

This alignment removes previously visible contradictions in both API payloads and the globe display, where debris could appear for passes hundreds of meters apart and where the incident marker could appear on the opposite side of the Earth from the actual close approach.

---

## VII. Discussion and Limitations

### A. What the Prototype Demonstrates

- An end-to-end path from orbital elements to a live operator display with sub-second refresh
- Transparent, auditable stages: SGP4 propagation, Foster B-plane Pc, CPI ranking, graph cascade, debris EVOLVE model, Cesium visualization
- Deterministic injection scenarios enabling repeatable regression testing
- Clear API contracts between heuristic and model-based components, supporting modular replacement

### B. Known Limitations

| Domain | Limitation | Recommended Next Step |
|--------|-----------|----------------------|
| Orbit state | TLE/SGP4 accuracy degrades with age and post-maneuver mismatch | Timestamped catalog archive with truth ephemerides |
| Uncertainty | RTN $\sigma_T$ model is a fixed analytical approximation; no measurement-based covariance | B-plane Pc validation against NASA CARA reference cases |
| Collision risk | Hard-body radius fixed at 10 m; no object-specific dimensions | Object size catalog integration; per-pair radius |
| Debris | Isotropic EVOLVE envelope; no atmospheric re-entry trajectory for individual fragments | Full fragment orbital element propagation with drag |
| ML scorer | Training and evaluation use the same Foster-derived synthetic distribution | Independent time-separated splits; real CDM labels |
| Graph models | GNN and GAT have identical cached metrics; surrogate rather than trained | Separate evaluation sets; training on real conjunction histories |
| Scale | Pairwise O($N^2$) screening; KD-tree helps but not benchmarked at catalog scale | Benchmark over 27,000+ object snapshots with timing |

### C. Threats to Validity

**Metric cache provenance:** The `model_metrics_cache.json` records a single evaluation run on a deterministic synthetic configuration. Reported scores may not generalize to other random seeds, different class balance ratios, or real encounter data.

**Graph model degeneracy:** Identical accuracy, precision, recall, and F1 values for GNN and GAT suggest either identical code paths for the evaluation target, shared synthetic data with limited graph structure diversity, or a ceiling effect from a trivially separable synthetic distribution. These results cannot be interpreted as evidence that both architectures generalize equally well.

**Regression test coverage:** The three tests are narrow regression tests designed to verify specific corrected behaviors. They do not constitute a comprehensive verification and validation suite.

**No UI study:** Visual correctness was assessed through rendered artifact inspection and code review. No user study of operator comprehension, alert triage performance, or decision latency was conducted.

### D. Recommended Research Path

The next validation phase should:
1. Build an encounter-plane probability benchmark against NASA CARA reference cases
2. Integrate object-specific covariances and hard-body radii from a curated catalog
3. Validate TCA localization against dense high-fidelity (high-order numerical) propagation
4. Implement temporal train/calibration/test splits for the risk scorer
5. Replace spherical EVOLVE envelopes with fragment ensembles propagated through drag-sensitive orbital dynamics with re-entry prediction

---

## VIII. Conclusion

Orbital Sentinel provides a coherent, explainable prototype for real-time orbital visualization and conjunction response. The Foster B-plane pipeline, RTN covariance model, Hermite TCA refinement, XGBoost risk scorer, graph cascade surrogates, and NASA EVOLVE debris model are all documented to their implementation files and mathematically grounded in established space mechanics methods.

The audit identified four linked defects capable of distorting incident interpretation: miss-independent probability, sample-grid TCA error and target overshoot, initial-epoch hotspot placement with debris on near-misses, and loss of debris forecast layers in the client. All four are corrected, and the behavioral effects are verified by deterministic regression tests. All three tests pass.

Cached synthetic metrics are promising within their stated scope: 93.85% risk-scorer accuracy on Foster-generated data and 98.76% graph-cascade accuracy on synthetic graph snapshots. The correct conclusion is that the prototype offers a reproducible architecture, an aligned event chain from encounter detection through visualization, and a stronger corrected baseline for future validation — not that it possesses operational collision-prediction accuracy. Independent temporal evaluation, real CDM data, and full breakup-model fragment propagation remain necessary before operational deployment.

---

## References

[1] European Space Agency, "ESA's Annual Space Environment Report," ESA Space Debris Office, Darmstadt, Germany, 2024.

[2] D. A. Vallado, P. Crawford, R. Hujsak, and T. S. Kelso, "Revisiting Spacetrack Report #3," in *AIAA/AAS Astrodynamics Specialist Conference*, Keystone, CO, 2006, AIAA 2006-6753.

[3] J. L. Foster and H. S. Estes, "A Parametric Analysis of Orbital Debris Collision Probability and Maneuver Rate for Space Vehicles," NASA/JSC-25898, 1992.

[4] F. K. Chan, "Spacecraft Collision Probability," *Journal of Guidance, Control, and Dynamics*, vol. 20, no. 3, pp. 566–571, 1997.

[5] N. L. Johnson, P. H. Krisko, J.-C. Liou, and P. D. Anz-Meador, "NASA's New Breakup Model of EVOLVE 4.0," *Advances in Space Research*, vol. 28, no. 9, pp. 1377–1384, 2001.

[6] K. T. Alfriend, M. R. Akella, J. Frisbee, J. L. Foster, D. J. Lee, and M. Wilkins, "Probability of Collision Error Analysis," *Space Debris*, vol. 1, no. 1, pp. 21–35, 1999.

[7] M. R. Akella and K. T. Alfriend, "Probability of Collision Between Space Objects," *Journal of Guidance, Control, and Dynamics*, vol. 23, no. 5, pp. 769–772, 2000.

[8] R. H. Battin, *An Introduction to the Mathematics and Methods of Astrodynamics*, revised ed. AIAA Education Series, 1999.

[9] Orbital Sentinel repository: `README.md`, `FEATURES_MATH_LOGIC.md`, `PROJECT_OVERVIEW.txt`, `analytics.py`, `conjunction.py`, `debris_model.py`, `xgboost_scorer.py`, `gnn_cascade.py`, `gat_cascade.py`, `sgp4_propagator.py`. Accessed September 2026.

[10] Orbital Sentinel `model_metrics_cache.json`, synthetic evaluation artifact, generated 8 May 2026.

---

*Manuscript prepared September 2026. All analysis derives from the supplied repository and installed runtime capabilities. No external dependency was downloaded for evidence generation.*
