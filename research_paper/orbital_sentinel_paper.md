# Orbital Sentinel: An Open, Cross-Checked Pipeline for Satellite Conjunction Assessment with Cascade-Aware Maneuver Planning

**Authors:** Soumyadeep Dey, Pritam Patra, Subarna Maity, Sourish Panda  
**Affiliation:** Guru Nanak Institute of Technology, Howrah, West Bengal, India

> Markdown mirror of `orbital_sentinel_paper.tex`, the IEEE submission source. Figures are rendered only in the PDF.

# Abstract

As the tracked catalog grows, satellite operators must screen more object pairs and justify each maneuver decision. This paper presents Orbital Sentinel, an open-source pipeline that screens a two-line element (TLE) catalog for close approaches over a 24-h horizon, computes the Foster two-dimensional probability of collision using per-object hard-body radii and a covariance that grows with TLE age, and streams the results to a three-dimensional web globe. Every probability is cross-checked against the Chan series and the Alfano maximum-probability bound, and the highest-risk alerts are also checked by Monte Carlo sampling. Candidate avoidance burns are verified by re-propagation, and the best candidates are re-screened against the whole catalog and simulated debris, so a burn that creates a secondary conjunction is rejected. Collision consequences are modeled with the NASA Standard Breakup Model and fragment propagation under J2 and drag. An XGBoost surrogate of the logarithmic probability, explained with TreeSHAP, never changes the published probability and can only escalate, never lower, the physics-based action. On 12 000 held-out synthetic encounters it attains a mean absolute error of 0.106 decades, with 0.975 precision and 0.950 recall at the $`10^{-4}`$ maneuver threshold, whereas a miss-distance-only baseline detects no high-risk encounter. Screening 500 objects takes about 1 s on a laptop processor, and all 18 analytical physics checks and 204 regression tests pass.

**Index Terms**: collision avoidance, collision probability, conjunction assessment, explainable machine learning, orbital debris, space situational awareness, SGP4, XGBoost

# Introduction

According to the European Space Agency (ESA), about 1.5 million objects between 1 and 10 cm are in orbit, and about 47 000 objects are regularly tracked and cataloged \[1\]\[2\]. The 2009 collision between Iridium 33 and Cosmos 2251 created thousands of trackable fragments \[3\], and collisions are expected to dominate future debris growth through the cascade described by Kessler and Cour-Palais \[4\]\[5\].

Operational conjunction assessment (CA) relies on precise orbit data, the two-dimensional probability of collision ($`P_c`$), and expert review \[6\]. Open tools for education, prototyping, and research rarely expose the complete chain from screening to probability to maneuver decision. Two gaps are common. First, operational practice screens a planned maneuver against the full catalog before execution \[6\], but open research tools rarely implement this step and often check a burn only against the primary threat, so a burn that resolves one conjunction can create another. Second, machine-learning (ML) components are increasingly proposed for CA \[7\]\[8\]\[9\], but their outputs are rarely explained or prevented from lowering physically derived risk.

This paper presents Orbital Sentinel, an open-source system that addresses both gaps. Its contributions are:

1.  a 24-h future-window screening pipeline that combines a spatial-index candidate search, a linear relative-motion filter, and Brent refinement of the time of closest approach (TCA);

2.  a Foster $`P_c`$ engine with a TLE-age covariance model and per-object hard-body radius (HBR), cross-checked on every alert by the Chan series and the Alfano bound and, for the highest-risk alerts, by Monte Carlo sampling;

3.  a cascade-aware maneuver planner that re-propagates every candidate burn and re-screens the best candidates against the full catalog and simulated fragments;

4.  an explainable XGBoost $`P_c`$ surrogate whose held-out accuracy, baselines, and per-alert TreeSHAP attributions are reported, and which can raise but never lower the physics-based action; and

5.  a reproducible evaluation, including negative results that justify keeping weaker learned components out of the decision path.

Our evaluation is internal: it checks consistency against analytical solutions, independent numerical references, and synthetic data, not operational skill.

# Related Work

*Orbit propagation and screening.* Public TLEs are propagated with the Simplified General Perturbations 4 (SGP4) model \[10\], whose reference implementation was revised by Vallado *et al.* \[11\]. SGP4 accuracy degrades with element age \[12\]\[13\]. Classical screening first removes pairs whose apogee/perigee shells cannot overlap \[14\].

*Collision probability.* For short encounters with linear relative motion, $`P_c`$ reduces to a two-dimensional Gaussian integral over the hard-body disk in the encounter plane, introduced by Foster and Estes \[15\]. Equivalent formulations include the Chan series \[16\] and the contour integral of Patera \[17\]. Akella and Alfriend \[18\] formalized the short-encounter assumptions, and Alfriend *et al.* \[19\] showed how strongly $`P_c`$ depends on covariance error. NASA’s Conjunction Assessment Risk Analysis (CARA) program has documented the usage boundaries of the two-dimensional method \[20\], Monte Carlo verification \[21\], and operational practice, including the $`10^{-4}`$ maneuver threshold \[6\]. Open implementations cover parts of this chain: CARA publishes its probability tools as open source \[22\], and the SOCRATES service publishes TLE-based conjunction screening reports \[23\]. To our knowledge, none couples screening, probability, breakup, and catalog-wide maneuver re-screening in one open pipeline.

*Machine learning for CA.* The ESA Collision Avoidance Challenge trained models to forecast the final risk in a sequence of conjunction data messages (CDMs) \[7\]. Other work combined ML with evidence theory \[8\], benchmarked deep networks for all-vs-all screening \[9\], and corrected orbit-prediction error \[24\]. These studies rarely report feature attributions or limit a model’s authority over the physical estimate. We use the exact tree form of Shapley additive explanations, TreeSHAP \[25\], with gradient-boosted trees \[26\], and keep the physical $`P_c`$ authoritative.

*Debris and cascades.* The NASA Standard Breakup Model (SBM) \[27\] is the standard tool for generating fragment populations. Graph neural networks \[28\] suggest learned formulations of cascade risk; we use a physics-first graph and evaluate learned graph rankers only as advisory cross-checks.

# System Architecture

Fig. <a href="#fig:pipeline" data-reference-type="ref" data-reference="fig:pipeline">1</a> shows the pipeline. A Python backend (FastAPI) propagates the catalog, refreshes alerts every 30 s and after every state change, and serves a representational state transfer (REST) application programming interface (API) together with a WebSocket stream that pushes positions at 1 Hz. A React client renders objects, encounter hotspots, and debris on a CesiumJS globe, converting inertial coordinates to Earth-fixed ones with Greenwich mean sidereal time \[11\]. TLEs come from Space-Track when credentials are configured, then from a public mirror, and otherwise from a bundled 31 068-object snapshot. All physics runs on a simulation clock, defined as wall-clock time plus an operator offset of up to $`\pm24`$ h, so scenarios are repeatable. Every assumed input, such as an object’s mass or radius, is a named constant, and each output records which assumption it used.

<figure id="fig:pipeline" data-latex-placement="!t">
<p><em>[Figure rendered in the PDF version]</em></p>
<figcaption>Orbital Sentinel pipeline. Solid boxes produce authoritative quantities. Dashed boxes are verification or learned outputs that never modify the physical <span class="math inline"><em>P</em><sub><em>c</em></sub></span>; the surrogate feeds the decision score and can only escalate the action.</figcaption>
</figure>

# Methods

## Propagation and Executed Burns

States are propagated with SGP4, using World Geodetic System 1972 (WGS-72) constants in the true-equator mean-equinox frame \[10\]\[11\]. Refitting a TLE after a maneuver would introduce fitting error, so an executed impulse $`\Delta\mathbf{v}`$ is applied as a deviation computed with a two-body plus Earth-oblateness ($`J_2`$) integrator (fourth-order Runge–Kutta):
``` math
\begin{equation}
  \mathbf{r}(t) = \mathbf{r}_{\mathrm{SGP4}}(t)
  + \left[\mathbf{r}_{J_2}\big(t;\mathbf{x}_0+[\mathbf{0};\Delta\mathbf{v}]\big)
          - \mathbf{r}_{J_2}(t;\mathbf{x}_0)\right],
\label{eq:burn}
\end{equation}
```
where $`\mathbf{x}_0`$ is the position–velocity state at burn time. A zero burn therefore leaves the trajectory unchanged, and the planner and the executed burn share one model.

## Future-Window Screening

All objects are propagated on a 60-s grid over 24 h. An apogee/perigee shell filter removes objects whose radial range cannot overlap any other object \[14\]. At each step $`t_k`$, candidate pairs are found with a $`k`$-dimensional tree (KD-tree) \[29\] using the search radius
``` math
\begin{equation}
  \rho = d_{\mathrm{th}} + \tfrac{1}{2}\,v_{\mathrm{max}}\,\Delta t,
\end{equation}
```
with threshold $`d_{\mathrm{th}}=25`$ km, step $`\Delta t=60`$ s, and $`v_{\mathrm{max}}`$ equal to twice the largest orbital speed in the window. Each candidate is passed through a linear relative-motion filter. With relative position $`\mathbf{r}_{\mathrm{r}}`$ and relative velocity $`\mathbf{v}_{\mathrm{r}}`$, the local closest-approach time is
``` math
\begin{equation}
  t^{*} = -\frac{\mathbf{r}_{\mathrm{r}}\cdot\mathbf{v}_{\mathrm{r}}}{\left\|\mathbf{v}_{\mathrm{r}}\right\|^{2}},
\end{equation}
```
and the candidate is kept if $`|t^{*}|\le\Delta t/2`$ and $`\left\|\mathbf{r}_{\mathrm{r}}+\mathbf{v}_{\mathrm{r}}\,t^{*}\right\|\le d_{\mathrm{th}}+5`$ km. Slow co-orbital pairs ($`\left\|\mathbf{v}_{\mathrm{r}}\right\|<0.05`$ km/s) skip the $`t^{*}`$ test, and at most three candidate steps per pair are refined, smallest linearized miss first. The TCA is refined by bounded Brent minimization \[30\]\[31\] of the exact SGP4 distance on $`[t_k-\Delta t,\,t_k+\Delta t]`$ with 1-ms tolerance, and the closest encounter per pair within $`d_{\mathrm{th}}`$ becomes an alert.

## Covariance Model and Foster Probability

TLEs carry no covariance, so a per-object covariance is modeled in the radial, transverse, and normal (RTN) frame. Its 1$`\sigma`$ values grow linearly with the propagation span $`\tau`$ (days) from the TLE epoch to the TCA:
``` math
\begin{equation}
\begin{aligned}
  \boldsymbol{\sigma}(\tau) &= \boldsymbol{\sigma}_0 + \mathbf{g}\,\tau,\qquad
  \boldsymbol{\sigma}_0=(0.10,\,0.50,\,0.15)~\text{km},\\
  \mathbf{g} &= (0.10,\,1.00,\,0.10)~\text{km/day}.
\end{aligned}
\label{eq:cov}
\end{equation}
```
This is a single, regime-independent simplification chosen to match the order of magnitude of low-Earth-orbit TLE errors \[12\]\[13\]; actual errors vary with orbit regime and drag, so absolute $`P_c`$ values are indicative. Each covariance is rotated to the inertial frame, $`\mathbf{C}=\mathbf{R}\,\mathrm{diag}(\boldsymbol{\sigma}^2)\mathbf{R}^{T}`$, and the two are summed. The encounter plane is normal to $`\mathbf{v}_{\mathrm{r}}`$. With unit vectors $`\hat{\mathbf{h}}=\mathbf{v}_{\mathrm{r}}/\left\|\mathbf{v}_{\mathrm{r}}\right\|`$, $`\hat{\mathbf{t}}\propto\hat{\mathbf{h}}\times\mathbf{r}_1`$, and $`\hat{\mathbf{n}}=\hat{\mathbf{t}}\times\hat{\mathbf{h}}`$, the projection $`\mathbf{B}=[\hat{\mathbf{t}}\;\hat{\mathbf{n}}]^{T}`$ gives the miss vector $`\mathbf{b}=\mathbf{B}\mathbf{r}_{\mathrm{r}}`$ and the encounter covariance $`\mathbf{C}_B=\mathbf{B}(\mathbf{C}_1+\mathbf{C}_2)\mathbf{B}^{T}`$. Foster’s probability \[15\] is
``` math
\begin{equation}
  P_c=\frac{1}{2\pi\sqrt{|\mathbf{C}_B|}}\iint_{\left\|\mathbf{x}\right\|\le R_{\mathrm{HB}}}
  e^{-\frac{1}{2}(\mathbf{x}-\mathbf{b})^{T}\mathbf{C}_B^{-1}(\mathbf{x}-\mathbf{b})}
  \,d\mathbf{x}.
\label{eq:foster}
\end{equation}
```
It is evaluated in polar coordinates with 48-point Gauss–Legendre quadrature in radius and a 96-point trapezoid rule in angle. The combined radius $`R_{\mathrm{HB}}`$ is the sum of the objects’ radii. Each radius is taken from the radar cross-section class in the public satellite catalog (SATCAT): 0.18 m for small and 0.56 m for medium objects. Otherwise it defaults by object type: 5 m for payloads, 4 m for rocket bodies, 0.5 m for debris, and 1 m for unknown objects. Named large structures have their own values, for example 55 m for the International Space Station. An alert is flagged when the short-encounter assumption is questionable ($`\left\|\mathbf{v}_{\mathrm{r}}\right\|<0.1`$ km/s) \[18\]\[20\].

## Independent Probability Cross-Checks

Each alert also carries independent estimates computed from its published encounter-plane fields (miss vector, $`3\sigma`$ ellipse, and HBR). The first is the Chan equivalent-area series \[16\]. With $`(x,y)`$ the miss components in the covariance principal axes, $`u=R_{\mathrm{HB}}^{2}/(\sigma_x\sigma_y)`$, and $`v=x^{2}/\sigma_x^{2}+y^{2}/\sigma_y^{2}`$,
``` math
\begin{equation}
  P_c^{\mathrm{Chan}}=e^{-v/2}\sum_{m=0}^{\infty}\frac{(v/2)^m}{m!}
  \Big[1-e^{-u/2}\sum_{k=0}^{m}\frac{(u/2)^k}{k!}\Big],
\label{eq:chan}
\end{equation}
```
which is evaluated in log space and is exact for an isotropic covariance \[16\]. The second is the Alfano maximum probability over covariance scaling \[32\]. Its closed form, $`R_{\mathrm{HB}}^{2}/(e\,\sigma_x\sigma_y\,\mathbf{b}^{T}\mathbf{C}_B^{-1}\mathbf{b})`$, is refined numerically and bounds $`P_c`$ when the covariance size is uncertain. Both are computed for every alert. The third, applied to the ten highest-$`P_c`$ alerts of each refresh, is seeded Monte Carlo sampling \[21\] with up to $`2\times10^{5}`$ draws; it reports no value when fewer than ten hits occur, rather than a noisy estimate. The spread of $`\log_{10}P_c`$ across methods is published with each alert, together with a flag that is set when Foster and Chan agree within 0.5 decades (one decade is a factor of 10 in $`P_c`$).

## Breakup Model and Fragment Screening

When a collision is simulated, both objects are propagated to the predicted TCA and the NASA SBM \[27\] is applied. With projectile (smaller) mass $`m_p`$, target mass $`M_t`$, and impact speed $`v`$, the collision is catastrophic if $`\tfrac{1}{2}m_p v^{2}/M_t\ge 40`$ J/g. The reference mass is $`M=m_1+m_2`$ for a catastrophic collision and $`M=m_p v^{2}`$ ($`v`$ in km/s) otherwise. The number of fragments of characteristic length $`L_c`$ between 10 cm and $`L_{\max}=(m_{\max}/\rho_b)^{1/3}`$, with $`m_{\max}`$ the larger parent mass and bulk density $`\rho_b=100`$ kg/m$`^3`$, is
``` math
\begin{equation}
  N=0.1\,M^{0.75}\left(L_{\min}^{-1.71}-L_{\max}^{-1.71}\right),\quad
  L_{\min}=0.1~\text{m}.
\label{eq:sbm}
\end{equation}
```
The area-to-mass exponent $`\chi=\log_{10}(A/M)`$ is drawn from the bimodal SBM distributions, and the ejection speed follows $`\log_{10}\Delta v\sim\mathcal{N}(0.9\chi+2.9,\,0.4)`$ in isotropic directions. Momentum is re-centered for each parent body. Up to 1 000 weighted fragments are propagated with two-body, $`J_2`$, and drag dynamics (drag coefficient 2.2, exponential atmosphere \[11\]). Each fragment is screened against the catalog over 6 h on a 30-s grid with a 5-km threshold, using an isotropic encounter-plane covariance (satellite 0.2 km; fragment 0.1 km growing at 1 m/s) instead of <a href="#eq:cov" data-reference-type="eqref" data-reference="eq:cov">[eq:cov]</a>.

## Cascade Graph

Alerts form an undirected graph whose nodes are objects and simulated collision events. Each event is linked to its two parent objects and its fragments, and each alert links its two objects. Cascade depth is the number of breadth-first-search (BFS) hops from the nearest event; an alert not connected to any event has depth 1. Assuming independent encounters, a node’s hit probability is $`P_{\mathrm{hit}}=1-\prod_i(1-P_{c,i})`$ over its incident alerts.

## Cascade-Aware Maneuver Planning

For up to 15 alerts with $`P_c\ge10^{-6}`$, the planner evaluates impulsive burns in the positive and negative radial, along-track, and cross-track directions, with eight magnitudes from 0.01 to 2 m/s. Every candidate is applied with <a href="#eq:burn" data-reference-type="eqref" data-reference="eq:burn">[eq:burn]</a>, the encounter with the threat is re-screened within $`\pm15`$ min, and $`P_c`$ is recomputed with <a href="#eq:foster" data-reference-type="eqref" data-reference="eq:foster">[eq:foster]</a>. The target is $`P_c<10^{-6}`$. Up to four shortlisted options are then re-screened for 24 h against the whole catalog and up to 2 000 live fragments within a 2.5-s budget; options left unchecked are flagged. Secondary encounters that also appear in a zero-burn pass are discounted, so only conjunctions that the burn creates or worsens are counted. An option is *cascade-safe* if it induces no secondary conjunction with $`P_c\ge10^{-6}`$ or a miss distance below 1 km. The planner selects the smallest cascade-safe $`\Delta v`$ that reaches the target; otherwise the cascade-safe option with the largest $`P_c`$ reduction; otherwise it reports that no cascade-safe option exists. Propellant is costed with the rocket equation, $`m_{\mathrm{prop}}=m_0\big(1-e^{-\Delta v/(I_{sp}g_0)}\big)`$, for a catalog of 12 chemical, cold-gas, and electric thrusters. A burn is flagged as non-impulsive when its duration exceeds 10% of the lead time to TCA or one tenth of an orbit. As an analytic check, the along-track shift predicted by the Clohessy–Wiltshire equations \[33\] is compared with the numerically propagated shift.

## Explainable Probability Surrogate

The surrogate is an XGBoost regressor \[26\] of $`\log_{10}P_c`$ (floored at $`10^{-12}`$) with seven inputs: miss distance, radial miss, relative speed, the larger and smaller TLE ages, HBR, and altitude. It does not see the covariance or the encounter-plane geometry. Labels are computed with <a href="#eq:cov" data-reference-type="eqref" data-reference="eq:cov">[eq:cov]</a> and <a href="#eq:foster" data-reference-type="eqref" data-reference="eq:foster">[eq:foster]</a> on 60 000 sampled encounters (seed 20261008), with altitude uniform in 300–2000 km, crossing angles of 0.5–175$`^\circ`$, miss distances log-uniform from 3 m to 25 km, per-object TLE ages log-uniform from 0.5 h to 1 year, and combined HBR log-uniform from 3 to 50 m. Before training, the radial miss is removed from 30% of rows, the altitude from 30%, and both TLE ages from 15%, so that the model tolerates missing inputs. The data are split 70/10/20 into training, early-stopping validation, and held-out test sets. Training uses squared error, a learning rate of 0.08, and depth 8, and early stopping retains 88 rounds.

Because the Foster $`P_c`$ is computed for every alert, the surrogate is not used for speed. Its role is to provide additive per-alert attributions whose sum with a base value equals the prediction: exact TreeSHAP \[25\] for the eight highest-risk alerts per refresh, and the cheaper Saabas path attribution \[25\] for the rest. These attributions explain the surrogate, not the physical computation. The surrogate never writes the published $`P_c`$, and its disagreement with physics, $`|\Delta\log_{10}P_c|`$, is reported as a diagnostic.

## Decision Score

For ranking and display, the models are combined in a bounded score whose weights are design choices, not fitted or validated. With $`L(p)=\mathrm{clip}\big((\log_{10}p+7)/3,\,0,\,1\big)`$,
``` math
\begin{equation}
\begin{aligned}
  S = 100\,\big[\,&0.60\,L(P_c)+0.15\,L(\hat P_c)\\
  &+0.15\,(1-e^{-D/5})+0.10\,\kappa\,e^{-\Delta v/v_0}\,\big],
\end{aligned}
\label{eq:score}
\end{equation}
```
where $`\hat P_c`$ is the surrogate output, $`D`$ the number of downstream objects, $`v_0=1`$ m/s, and $`\kappa\in\{1,0.5,0\}`$ for a cascade-safe plan, an unsafe plan, and no plan. The physics term outweighs all other terms combined. The action is set by the physical $`P_c`$: maneuver at $`P_c\ge10^{-4}`$ \[6\], and prepare and monitor at $`10^{-5}`$ and $`10^{-7}`$, our own planning tiers. A prepare action is escalated to maneuver only when the surrogate predicts $`\hat P_c\ge10^{-4}`$ and the cascade term is at least 0.5 ($`D\ge4`$). This is the only way a learned output affects the action, and no model can lower the physics action.

# Evaluation Setup

Experiments ran on a laptop with an Intel Core i3-1215U processor and 16 GB of memory, using Python 3.14, NumPy 2.5, SciPy 1.18 \[31\], XGBoost 3.4, and sgp4 2.27. Probability accuracy is measured against the exact noncentral chi-square (Rice) distribution, which is the closed-form solution for an isotropic covariance \[16\]. Physics consistency is assessed with 18 analytical checks. Screening throughput is measured on the first 500 objects of the bundled catalog (the default size of the live server) at a simulation epoch of 2026-05-12 00:00 UTC; these are the first entries in catalog order, not a regime-stratified sample. Surrogate accuracy is measured on the 12 000 held-out encounters against a constant predictor and a miss-distance-only XGBoost baseline. Behavior is protected by a 204-test regression suite (20 files, under 30 s), which passes in full. Several tests compute their expected values independently, for example by brute-force screening on a 1-s grid refined at 1-ms resolution, which screening matches within 1 s in TCA and 0.1 km in miss distance.

# Results

## Probability Accuracy

Fig. <a href="#fig:pc" data-reference-type="ref" data-reference="fig:pc">2</a> uses $`\sigma=10`$ m per axis and $`R_{\mathrm{HB}}=10`$ m. The quadrature implementation of <a href="#eq:foster" data-reference-type="eqref" data-reference="eq:foster">[eq:foster]</a> matches the exact solution to at least six significant digits from $`3.9\times10^{-1}`$ down to $`3.4\times10^{-20}`$, and the Chan series <a href="#eq:chan" data-reference-type="eqref" data-reference="eq:chan">[eq:chan]</a> is exact here, as expected. SciPy’s adaptive `dblquad` integrator, used as a reference, drifts by up to $`3.3\times10^{-4}`$ relative error in the far tail. A single-term small-body approximation, to which earlier versions of the system fell back when `dblquad` failed or exceeded its 2-s timeout, underestimates $`P_c`$ by 23% at zero miss distance and overestimates it by factors of 2.4 at 50 m and 4.8 at 100 m. It has therefore been replaced everywhere, including that fallback, by the full series <a href="#eq:chan" data-reference-type="eqref" data-reference="eq:chan">[eq:chan]</a>.

<figure id="fig:pc" data-latex-placement="!t">
<p><em>[Figure rendered in the PDF version]</em></p>
<figcaption>Collision probability versus miss distance for <span class="math inline"><em>σ</em> = 10</span> m per axis and <span class="math inline"><em>R</em><sub>HB</sub> = 10</span> m. The Foster quadrature coincides with the exact solution over 19 decades.</figcaption>
</figure>

## Physics Validation

All 18 analytical checks pass in under 0.7 s. Foster agrees with the Rice solution to $`2.3\times10^{-16}`$ and with Chan to $`4.6\times10^{-16}`$ (isotropic) and $`\le1.3\times10^{-3}`$ (5:1 and rotated 3.3:1 covariances), relative. Monte Carlo ($`2\times10^{5}`$ draws) agrees within four standard errors on all three geometries, and the Alfano bound ($`2.60\times10^{-3}`$) exceeds Foster ($`2.30\times10^{-3}`$), as required. The $`J_2`$ Runge–Kutta integrator drifts in energy by $`6.7\times10^{-11}`$ over 3 h and stays within 0.040 km of SGP4 over 30 min. The Clohessy–Wiltshire, Hohmann, and rocket-equation checks agree with numerical results to $`2.3\times10^{-3}`$, $`1.6\times10^{-7}`$, and $`1.4\times10^{-9}`$, and the SBM produces 778 fragments where <a href="#eq:sbm" data-reference-type="eqref" data-reference="eq:sbm">[eq:sbm]</a> predicts 777.6 (800 + 15 kg at 10 km/s).

## Screening Throughput

Table <a href="#tab:screen" data-reference-type="ref" data-reference="tab:screen">[tab:screen]</a> shows the screening funnel for 500 objects. The KD-tree search returns 153 144 candidate pair-steps out of about $`1.8\times10^{8}`$ (124 750 pairs at each of 1 441 epochs). The linear filter keeps 314 pair-steps. After the cap of three refinements per pair, 274 Brent refinements are run over 240 distinct pairs; 189 of them, covering 165 distinct pairs, end within 25 km, giving 165 alerts. The funnel is identical across runs, and end-to-end screening took 0.86–1.00 s over four runs, well inside the 30-s refresh interval.

Because the bundled TLEs are old at this epoch (median span of the older TLE at TCA 6.3 days, maximum 25.6 days), the modeled covariance is large and the maximum $`P_c`$ is $`7.6\times10^{-8}`$. Seven alerts are rated WARNING because their miss distance is below 5 km, and 158 are rated WATCH. No alert reaches even the $`10^{-7}`$ monitor tier, so every decision action is NONE and the maneuver planner was not triggered in this run; its evaluation rests on the constructed encounters in Section <a href="#sec:maneuver" data-reference-type="ref" data-reference="sec:maneuver">6.4</a>. Operational use would require recent TLEs.

<div class="tabular">

@lrr@ Stage & Output & Time (s)\
SGP4 propagation on 60-s grid & 500 objects & 0.198\
KD-tree candidate search & 153 144 pair-steps & 0.432\
Linear relative-motion filter & 314 pair-steps & –\
Brent TCA refinement ($`\le`$<!-- -->3 per pair) & 274 runs & 0.073\
Foster $`P_c`$ and alert assembly & 165 alerts & 0.247\
Total (representative run) & & 0.950\

</div>

## Maneuver Verification

Regression tests exercise the planner on constructed encounters. In one test, the naive minimum-$`\Delta v`$ burn, executed on a clone of the satellite, brings the maneuvering satellite within 30 m of a third payload, which full screening confirms. The planner marks that option as not cascade-safe, matches the secondary miss distance to within 50 m, and selects a different burn that still reaches $`P_c<10^{-6}`$. In a separate test, the planner’s predicted post-burn miss distance equals the executed result to within 10 m and its predicted TCA to within 1 s. The two-body Clohessy–Wiltshire along-track drift agrees with numerical propagation to within 0.5% (or 2 m) for burns of up to 0.05 m/s over 2 h.

## Surrogate Accuracy and Explanations

Table <a href="#tab:ml" data-reference-type="ref" data-reference="tab:ml">[tab:ml]</a> reports held-out results; F1 is the harmonic mean of precision and recall. The surrogate’s mean absolute error (MAE) of 0.106 decades is 15 times lower than that of the miss-distance-only baseline. That baseline is deliberately weak: it never predicts $`P_c\ge10^{-4}`$, which shows that miss distance alone cannot rank risk when the covariance depends on TLE age. At the $`10^{-6}`$ tier the surrogate reaches 0.986 precision and 0.979 recall. Removing the radial miss, or masking features as happens in the live pipeline, raises the error but keeps F1 above 0.88. Projecting the inputs onto principal components hurts accuracy, because the features are weakly redundant (six of seven components are needed for 95% of the variance) and trees split along one axis at a time. The mean absolute TreeSHAP contributions show that the larger TLE age dominates (1.00 decades), because it drives the along-track covariance. It is followed by miss distance (0.78), HBR (0.57), radial miss (0.29), and relative speed (0.15), which is consistent with <a href="#eq:cov" data-reference-type="eqref" data-reference="eq:cov">[eq:cov]</a> and <a href="#eq:foster" data-reference-type="eqref" data-reference="eq:foster">[eq:foster]</a>.

<div class="tabular">

@lccccc@ Model & MAE & RMSE & Prec. & Rec. & F1\
XGBoost, 7 features & **0.106** & **0.241** & **0.975** & **0.950** & **0.962**\
without radial miss & 0.224 & 0.634 & 0.971 & 0.924 & 0.947\
masked features & 0.337 & 0.756 & 0.965 & 0.811 & 0.881\
first 6 principal comp. & 0.250 & – & – & – & 0.910\
Miss-only XGBoost & 1.565 & 1.879 & 0 & 0 & 0\
Constant predictor & 1.739 & 2.277 & – & – & –\
\

</div>

## Negative Results

Two learned components were evaluated and excluded from the decision path. A 12-unit ungated Elman recurrent network \[34\] for trajectory prediction reaches a position MAE of 459 km on 512 test sequences. That is worse than both persistence (347 km) and linear extrapolation (20.5 km), so it is labeled experimental and feeds no alert. Two graph rankers, a summary-statistics network and a four-head graph attention network \[28\], reach 98.8% and 95.5% accuracy on synthetic graphs, but their labels come from a heuristic, which makes those scores circular. On the 500-object benchmark graph, the attention ranker’s Spearman correlation with the physics $`P_{\mathrm{hit}}`$ is only 0.14, and the two rankers disagree with each other by up to 0.38 in probability. They are therefore shown only as an advisory cross-check and never set depth, probability, or the maneuver plan.

# Discussion and Limitations

The design keeps the physical $`P_c`$ separate from learned estimates, and the negative results show why baselines matter: without them, the recurrent network and the two graph models would have appeared useful. The system has important limitations. The covariance is modeled from TLE age rather than taken from CDMs, so absolute $`P_c`$ values are only as good as <a href="#eq:cov" data-reference-type="eqref" data-reference="eq:cov">[eq:cov]</a> \[19\]\[20\]. Object masses are assumed, because SATCAT provides none, and they set the SBM fragment count through $`M^{0.75}`$. The surrogate is trained on synthetic geometry with combined radii of 3–50 m, whereas live combined radii are often below 3 m. On the 500-object benchmark its median disagreement with the physics $`P_c`$ is 0.90 decades, mostly for $`P_c<10^{-7}`$, where training labels are floored; its held-out accuracy therefore measures how well it reproduces the physics on the training distribution, not operational skill. The planner checks each alert’s options independently, so two simultaneous burns are not screened against each other, and burns are impulsive. Throughput was measured for 500 objects; candidate counts grow roughly quadratically with catalog size, so a full catalog would require parallelization. Future work includes validation on real CDM sequences \[7\], comparison with the CARA tools \[22\], and multi-burn coordination.

# Conclusion

Orbital Sentinel couples future-window screening, cross-checked Foster collision probability, NASA SBM fragment screening, an alert-based cascade graph, and maneuver planning that rejects burns that create new conjunctions in one open pipeline. Its probability engine matches the exact solution over 19 decades, it screens 500 objects in about one second on a laptop processor, and it passes 18 analytical checks and 204 regression tests. The explainable surrogate reaches 0.106-decade error with 0.95 recall at the maneuver threshold but can never lower the physics action. The source code is available at <https://github.com/Pritam-mb/orbit-sentinal>.

# Author Contributions (CRediT)

**Soumyadeep Dey:** Conceptualization, Methodology, Software, Validation, Formal analysis, Writing – original draft. **Pritam Patra:** Software, Visualization, Project administration, Writing – original draft, Writing – review & editing. **Subarna Maity:** Software, Visualization. **Sourish Panda:** Investigation, Writing – review & editing.

# Acknowledgment

The authors thank CelesTrak and Space-Track for public TLE and SATCAT data, and the maintainers of sgp4, SciPy, XGBoost, PyTorch, and CesiumJS.

*Use of AI-generated content:* Claude Opus 5.5 (Anthropic), a large language model, drafted and edited the text of all sections, generated the LaTeX source of the figures and tables from values produced by the authors’ software, helped check the references, and was used to review and correct parts of the software described in Sections III and IV. All reported results come from running that software. The authors reviewed all content and take full responsibility for it.

# References

1.  ESA Space Debris Office, “ESA’s annual space environment report,” ESA ESOC, Darmstadt, Germany, Rep. GEN-DB-LOG-00288-OPS-SD, Iss. 10.1, Sept. 2026. \[Online\]. Available: <https://www.sdo.esoc.esa.int/environment_report/Space_Environment_Report_I10R1_20260908.pdf>

2.  ESA Space Debris Office, “Space environment statistics,” DISCOSweb, ESA ESOC. Accessed: Oct. 12, 2026. \[Online\]. Available: <https://sdup.esoc.esa.int/discosweb/statistics/>

3.  T. S. Kelso, “Analysis of the Iridium 33–Cosmos 2251 collision,” in *Proc. AAS/AIAA Astrodyn. Specialist Conf.*, Pittsburgh, PA, USA, Aug. 2009, Paper AAS 09-368.

4.  D. J. Kessler and B. G. Cour-Palais, “Collision frequency of artificial satellites: The creation of a debris belt,” *J. Geophys. Res.*, vol. 83, no. A6, pp. 2637–2646, June 1978, doi: 10.1029/JA083iA06p02637.

5.  J.-C. Liou and N. L. Johnson, “Risks in space from orbiting debris,” *Science*, vol. 311, no. 5759, pp. 340–341, Jan. 2006, doi: 10.1126/science.1121337.

6.  NASA, “NASA spacecraft conjunction assessment and collision avoidance best practices handbook,” NASA, Washington, DC, USA, NASA/SP-20205011318, Dec. 2020. \[Online\]. Available: <https://ntrs.nasa.gov/citations/20205011318>

7.  T. Uriot *et al.*, “Spacecraft collision avoidance challenge: Design and results of a machine learning competition,” *Astrodynamics*, vol. 6, no. 2, pp. 121–140, June 2022, doi: 10.1007/s42064-021-0101-5.

8.  L. Sánchez Fernández-Mellado and M. Vasile, “On the use of machine learning and evidence theory to improve collision risk management,” *Acta Astronaut.*, vol. 181, pp. 694–706, Apr. 2021, doi: 10.1016/j.actaastro.2020.08.004.

9.  E. Stevenson, V. Rodriguez-Fernandez, H. Urrutxua, and D. Camacho, “Benchmarking deep learning approaches for all-vs-all conjunction screening,” *Adv. Space Res.*, vol. 72, no. 7, pp. 2660–2675, Oct. 2023, doi: 10.1016/j.asr.2023.01.036.

10. F. R. Hoots and R. L. Roehrich, “Models for propagation of NORAD element sets,” Aerospace Defense Command, U.S. Air Force, Peterson AFB, CO, USA, Spacetrack Rep. No. 3, Dec. 1980. \[Online\]. Available: <https://celestrak.org/NORAD/documentation/spacetrk.pdf>

11. D. A. Vallado, P. Crawford, R. Hujsak, and T. S. Kelso, “Revisiting Spacetrack Report \#3,” in *Proc. AIAA/AAS Astrodyn. Specialist Conf. Exhib.*, Keystone, CO, USA, Aug. 2006, Paper AIAA 2006-6753, doi: 10.2514/6.2006-6753.

12. T. Flohrer, H. Krag, and H. Klinkrad, “Assessment and categorization of TLE orbit errors for the US SSN catalogue,” in *Proc. Adv. Maui Opt. Space Surveill. Technol. Conf. (AMOS)*, Maui, HI, USA, Sept. 2008, pp. 513–524.

13. D. A. Vallado and P. J. Cefola, “Two-line element sets—Practice and use,” in *Proc. 63rd Int. Astronaut. Congr. (IAC)*, Naples, Italy, Oct. 2012, pp. 5812–5825.

14. F. R. Hoots, L. L. Crawford, and R. L. Roehrich, “An analytic method to determine future close approaches between satellites,” *Celest. Mech.*, vol. 33, no. 2, pp. 143–158, 1984.

15. J. L. Foster and H. S. Estes, “A parametric analysis of orbital debris collision probability and maneuver rate for space vehicles,” NASA Johnson Space Center, Houston, TX, USA, Tech. Rep. JSC-25898, Aug. 1992.

16. F. K. Chan, *Spacecraft Collision Probability*. El Segundo, CA, USA: Aerospace Press, 2008, doi: 10.2514/4.989186.

17. R. P. Patera, “General method for calculating satellite collision probability,” *J. Guid. Control Dyn.*, vol. 24, no. 4, pp. 716–722, July 2001, doi: 10.2514/2.4771.

18. M. R. Akella and K. T. Alfriend, “Probability of collision between space objects,” *J. Guid. Control Dyn.*, vol. 23, no. 5, pp. 769–772, Sept. 2000, doi: 10.2514/2.4611.

19. K. T. Alfriend, M. R. Akella, J. Frisbee, J. L. Foster, D.-J. Lee, and M. Wilkins, “Probability of collision error analysis,” *Space Debris*, vol. 1, no. 1, pp. 21–35, Mar. 1999, doi: 10.1023/A:1010056509803.

20. D. T. Hall, “Implementation recommendations and usage boundaries for the two-dimensional probability of collision calculation,” in *Proc. AAS/AIAA Astrodyn. Specialist Conf.*, Portland, ME, USA, Aug. 2019, Paper AAS 19-632.

21. D. T. Hall, S. J. Casali, L. C. Johnson, B. B. Skrehart, and L. G. Baars, “High fidelity collision probabilities estimated using brute force Monte Carlo simulations,” in *Proc. AAS/AIAA Astrodyn. Specialist Conf.*, Snowbird, UT, USA, Aug. 2018, Paper AAS 18-244.

22. NASA CARA, “CARA Analysis Tools,” GitHub repository. Accessed: Oct. 12, 2026. \[Online\]. Available: <https://github.com/nasa/CARA_Analysis_Tools>

23. T. S. Kelso and S. Alfano, “Satellite orbital conjunction reports assessing threatening encounters in space (SOCRATES),” in *Proc. SPIE, Modeling, Simulation, and Verification of Space-Based Systems III*, vol. 6221, May 2006.

24. H. Peng and X. Bai, “Machine learning approach to improve satellite orbit prediction accuracy using publicly available data,” *J. Astronaut. Sci.*, vol. 67, no. 2, pp. 762–793, June 2020, doi: 10.1007/s40295-019-00158-3.

25. S. M. Lundberg *et al.*, “From local explanations to global understanding with explainable AI for trees,” *Nat. Mach. Intell.*, vol. 2, no. 1, pp. 56–67, Jan. 2020, doi: 10.1038/s42256-019-0138-9.

26. T. Chen and C. Guestrin, “XGBoost: A scalable tree boosting system,” in *Proc. 22nd ACM SIGKDD Int. Conf. Knowl. Discov. Data Mining*, San Francisco, CA, USA, Aug. 2016, pp. 785–794, doi: 10.1145/2939672.2939785.

27. N. L. Johnson, P. H. Krisko, J.-C. Liou, and P. D. Anz-Meador, “NASA’s new breakup model of EVOLVE 4.0,” *Adv. Space Res.*, vol. 28, no. 9, pp. 1377–1384, 2001, doi: 10.1016/S0273-1177(01)00423-9.

28. P. Veličković, G. Cucurull, A. Casanova, A. Romero, P. Liò, and Y. Bengio, “Graph attention networks,” in *Proc. Int. Conf. Learn. Represent. (ICLR)*, 2018. \[Online\]. Available: <https://arxiv.org/abs/1710.10903>

29. J. L. Bentley, “Multidimensional binary search trees used for associative searching,” *Commun. ACM*, vol. 18, no. 9, pp. 509–517, Sept. 1975, doi: 10.1145/361002.361007.

30. R. P. Brent, *Algorithms for Minimization Without Derivatives*. Englewood Cliffs, NJ, USA: Prentice-Hall, 1973.

31. P. Virtanen *et al.*, “SciPy 1.0: Fundamental algorithms for scientific computing in Python,” *Nat. Methods*, vol. 17, no. 3, pp. 261–272, Mar. 2020, doi: 10.1038/s41592-019-0686-2.

32. S. Alfano, “Relating position uncertainty to maximum conjunction probability,” *J. Astronaut. Sci.*, vol. 53, no. 2, pp. 193–205, 2005.

33. W. H. Clohessy and R. S. Wiltshire, “Terminal guidance system for satellite rendezvous,” *J. Aerosp. Sci.*, vol. 27, no. 9, pp. 653–658, Sept. 1960, doi: 10.2514/8.8704.

34. J. L. Elman, “Finding structure in time,” *Cogn. Sci.*, vol. 14, no. 2, pp. 179–211, Mar. 1990, doi: 10.1207/s15516709cog1402_1.
