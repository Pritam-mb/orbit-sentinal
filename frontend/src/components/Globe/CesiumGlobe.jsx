import React, { useEffect, useRef } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import useStore from '../../store/useStore';
import useTestMode from '../../hooks/useTestMode';
import { computeGmst, eciToCesiumCartesian } from '../../utils/coords';

// Set Ion token
Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_TOKEN;

const SATELLITE_DEFAULT_SCALE = 0.26;
const SATELLITE_HOVER_SCALE = 0.34;
const SATELLITE_SELECTED_SCALE = 0.42;
const SATELLITE_SCALE_BY_DISTANCE = new Cesium.NearFarScalar(
  1000000.0,
  1.4,
  30000000.0,
  0.2,
);
const SATELLITE_EXTRAPOLATION_LIMIT_SECONDS = 10.0;
const ORBIT_BREAK_DISTANCE_KM = 8000;
const ZERO_VELOCITY = { vx: 0, vy: 0, vz: 0 };

function eciToCesiumCartesianFast(eciPos, cosG, sinG) {
  return {
    x: (eciPos.x * cosG + eciPos.y * sinG) * 1000,
    y: (-eciPos.x * sinG + eciPos.y * cosG) * 1000,
    z: eciPos.z * 1000,
  };
}

function setBillboardPosition(billboard, cartesian) {
  // Always assign a new position instance to ensure Cesium detects the property change
  billboard.position = new Cesium.Cartesian3(cartesian.x, cartesian.y, cartesian.z);
}

const CesiumGlobe = () => {
  const viewerRef = useRef(null);
  const containerRef = useRef(null);
  const motionRef = useRef({
    snapshotPositions: new Map(),
    lastSnapshotTimestampMs: null,
    lastSnapshotReceivedPerfMs: 0,
    animationFrameId: null,
  });
  const primitivesRef = useRef({
    billboards: null,
    labels: null,
    orbitLines: null,
    focusLabel: null,
    orbitPolyline: null,
    orbitSegmentPolylines: [],
    orbitMaterial: null,
    approachLine: null,
    approachMaterial: null,
    hotspotPoints: null,
    map: new Map(),
  });
  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return;

    const viewer = new Cesium.Viewer(containerRef.current, {
      // Show the earth globe with imagery
      imageryProvider: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      vrButton: false,
      infoBox: false,
      selectionIndicator: false,
      creditContainer: document.createElement('div'),
    });

    viewer.scene.requestRenderMode = false;
    viewer.scene.maximumRenderTimeChange = 0;
    viewer.scene.fxaa = false;

    // Add local imagery
    Cesium.SingleTileImageryProvider.fromUrl('/earth-realistic-8k.webp').then((provider) => {
      if (!viewer.isDestroyed()) {
        viewer.imageryLayers.addImageryProvider(provider);
        viewer.scene.requestRender();
      }
    }).catch(console.error);

    // Black background, no atmosphere glow
    viewer.scene.backgroundColor = Cesium.Color.BLACK;
    viewer.scene.sun.show = false;
    viewer.scene.moon.show = false;
    viewer.scene.skyBox.show = false;
    viewer.scene.skyAtmosphere.show = false;
    viewer.scene.fog.enabled = false;
    viewer.scene.globe.showGroundAtmosphere = false;
    viewer.scene.globe.enableLighting = false;
    viewer.scene.globe.depthTestAgainstTerrain = false;

    // Set initial camera to see Earth from space
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(30, 20, 25000000),
    });
    viewer.scene.requestRender();

    // Initialize Collections for high-performance rendering
    const billboards = new Cesium.BillboardCollection({
      blendOption: Cesium.BlendOption.TRANSLUCENT,
    });
    const labels = new Cesium.LabelCollection();
    const orbitLines = new Cesium.PolylineCollection();
    const hotspotPoints = new Cesium.PointPrimitiveCollection();
    viewer.scene.primitives.add(billboards);
    viewer.scene.primitives.add(labels);
    viewer.scene.primitives.add(orbitLines);
    viewer.scene.primitives.add(hotspotPoints);

    const focusLabel = labels.add({
      show: false,
      text: '',
      font: '11px JetBrains Mono',
      fillColor: Cesium.Color.fromCssColorString('#f3f4f6'),
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 2,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      pixelOffset: new Cesium.Cartesian2(15, -5),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });

    const orbitMaterial = Cesium.Material.fromType('Color');
    orbitMaterial.uniforms.color = Cesium.Color.fromCssColorString('#22c55e').withAlpha(0.8);

    const approachMaterial = Cesium.Material.fromType('Color');
    approachMaterial.uniforms.color = Cesium.Color.fromCssColorString('#22c55e').withAlpha(0.9);

    const orbitPolyline = orbitLines.add({
      show: false,
      positions: [],
      width: 2,
      material: orbitMaterial,
      arcType: Cesium.ArcType.NONE,
      id: 'selected-orbit',
    });

    const approachLine = orbitLines.add({
      show: false,
      positions: [],
      width: 2,
      material: approachMaterial,
      arcType: Cesium.ArcType.NONE,
      id: 'approach-line',
    });

    primitivesRef.current.billboards = billboards;
    primitivesRef.current.labels = labels;
    primitivesRef.current.orbitLines = orbitLines;
    primitivesRef.current.focusLabel = focusLabel;
    primitivesRef.current.orbitPolyline = orbitPolyline;
    primitivesRef.current.orbitMaterial = orbitMaterial;
    primitivesRef.current.approachLine = approachLine;
    primitivesRef.current.approachMaterial = approachMaterial;
    primitivesRef.current.hotspotPoints = hotspotPoints;

    // Hover and click handlers for satellite focus
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    const updateHoveredSatellite = (position) => {
      const picked = viewer.scene.pick(position);
      const nextHoveredId = Cesium.defined(picked) && typeof picked.id === 'number'
        ? picked.id
        : null;
      const store = useStore.getState();

      if (store.hoveredSatelliteId !== nextHoveredId) {
        store.setHoveredSatelliteId(nextHoveredId);
      }

      viewer.scene.requestRender();
      return nextHoveredId;
    };

    handler.setInputAction((movement) => {
      updateHoveredSatellite(movement.endPosition);
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    handler.setInputAction((click) => {
      const pickedId = updateHoveredSatellite(click.position);
      if (pickedId) {
        useStore.getState().setSelectedSatelliteId(pickedId);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    const clearHover = () => {
      const store = useStore.getState();
      if (store.hoveredSatelliteId !== null) {
        store.setHoveredSatelliteId(null);
      }

      viewer.scene.requestRender();
    };

    viewer.scene.canvas.addEventListener('mouseleave', clearHover);

    viewerRef.current = viewer;

    return () => {
      handler.destroy();
      viewer.scene.canvas.removeEventListener('mouseleave', clearHover);
      if (viewer && !viewer.isDestroyed()) {
        viewer.destroy();
      }
      viewerRef.current = null;
    };
  }, []);

  // Update satellite positions when store changes
  const satellites = useStore((s) => s.satellites);
  const selectedSatelliteId = useStore((s) => s.selectedSatelliteId);
  const hoveredSatelliteId = useStore((s) => s.hoveredSatelliteId);
  const selectedOrbit = useStore((s) => s.selectedOrbit);
  const hotspots = useStore((s) => s.hotspots);
  const snapshotTimestamp = useStore((s) => s.snapshotTimestamp);
  const testActive = useTestMode((s) => s.testActive);
  const testSatellites = useTestMode((s) => s.testSatellites);
  const testSim = useTestMode((s) => s.sim);
  const overrideAMode = useTestMode((s) => s.overrideA.mode);
  const overrideBMode = useTestMode((s) => s.overrideB.mode);
  const computed = useTestMode((s) => s.computed);
  const selectedAId = useTestMode((s) => s.selectedA?.norad_id ?? null);
  const selectedBId = useTestMode((s) => s.selectedB?.norad_id ?? null);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    const { billboards, focusLabel, map } = primitivesRef.current;
    if (!billboards || !focusLabel) return;

    const parsedSnapshotTimestampMs = snapshotTimestamp ? Date.parse(snapshotTimestamp) : Number.NaN;
    const snapshotTimestampMs = Number.isFinite(parsedSnapshotTimestampMs)
      ? parsedSnapshotTimestampMs
      : Date.now();
    const previousSnapshotTimestampMs = motionRef.current.lastSnapshotTimestampMs;

    // IMPORTANT: Ignore duplicate updates from REST vs WS race conditions.
    // If we process a duplicate timestamp, it resets our animation elapsed time to 0,
    // violently ripping the satellite back to its starting block.
    if (previousSnapshotTimestampMs != null) {
      if (snapshotTimestampMs === previousSnapshotTimestampMs) {
        return; // Ignore exact duplicates
      }
      // If timestamp went backwards (REST poll resolving after WS update), ignore it
      if (snapshotTimestampMs < previousSnapshotTimestampMs && snapshotTimestampMs > previousSnapshotTimestampMs - 10000) {
        return; 
      }
    }

    const previousSnapshotPositions = motionRef.current.snapshotPositions;
    const nextSnapshotPositions = new Map();
    const nextSnapshotVelocities = new Map();
    const existingIds = new Set();
    const focusedSatelliteId = useStore.getState().hoveredSatelliteId;
    const defaultColor = Cesium.Color.WHITE.withAlpha(0.55);
    const deltaSeconds = previousSnapshotTimestampMs != null
      ? Math.max((snapshotTimestampMs - previousSnapshotTimestampMs) / 1000, 0.001)
      : 1;

    for (const sat of satellites) {
      existingIds.add(sat.norad_id);
      nextSnapshotPositions.set(sat.norad_id, sat.position);

      const previousPosition = previousSnapshotPositions.get(sat.norad_id);
      const snapshotVelocity = sat.velocity
        ? {
            vx: sat.velocity.vx || 0,
            vy: sat.velocity.vy || 0,
            vz: sat.velocity.vz || 0,
          }
        : null;
      const derivedVelocity = previousPosition
        ? {
            vx: (sat.position.x - previousPosition.x) / deltaSeconds,
            vy: (sat.position.y - previousPosition.y) / deltaSeconds,
            vz: (sat.position.z - previousPosition.z) / deltaSeconds,
          }
        : ZERO_VELOCITY;
      const velocity = snapshotVelocity || derivedVelocity;

      let item = map.get(sat.norad_id);
      if (item) {
        item.name = sat.name;
        item.eciPosition = sat.position;
        item.eciVelocity = velocity;
        item.snapshotEpochUtc = sat.epoch_utc || null;
      } else {
        const billboard = billboards.add({
          position: new Cesium.Cartesian3(),
          image: '/dot-medium.png',
          color: defaultColor,
          scale: SATELLITE_DEFAULT_SCALE,
          scaleByDistance: SATELLITE_SCALE_BY_DISTANCE,
          id: sat.norad_id,
        });

        item = {
          billboard,
          name: sat.name,
          eciPosition: sat.position,
          eciVelocity: velocity,
          snapshotEpochUtc: sat.epoch_utc || null,
        };
        map.set(sat.norad_id, item);
      }

      nextSnapshotVelocities.set(sat.norad_id, velocity);
    }

    // Remove entities no longer in the satellite list
    for (const [id, item] of map.entries()) {
      if (!existingIds.has(id)) {
        billboards.remove(item.billboard);
        map.delete(id);
      }
    }

    motionRef.current.snapshotPositions = nextSnapshotPositions;
    motionRef.current.snapshotVelocities = nextSnapshotVelocities;
    motionRef.current.lastSnapshotTimestampMs = snapshotTimestampMs;
    motionRef.current.lastSnapshotReceivedPerfMs = performance.now();

    const updateDate = new Date(snapshotTimestampMs);
    const gmst = computeGmst(updateDate);
    const cosG = Math.cos(gmst);
    const sinG = Math.sin(gmst);

    for (const item of map.values()) {
      if (!item.eciPosition) continue;
      const cartesian = eciToCesiumCartesianFast(item.eciPosition, cosG, sinG);
      setBillboardPosition(item.billboard, cartesian);
    }

    const focusedItem = focusedSatelliteId != null ? map.get(focusedSatelliteId) : null;
    if (focusedItem) {
      focusLabel.show = true;
      focusLabel.text = focusedItem.name;
      focusLabel.position = focusedItem.billboard.position;
    } else {
      focusLabel.show = false;
    }

    viewer.scene.requestRender();
  }, [satellites, snapshotTimestamp]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    const {
      billboards,
      orbitPolyline,
      orbitLines,
      orbitMaterial,
      orbitSegmentPolylines,
      map,
      focusLabel,
    } = primitivesRef.current;
    if (!billboards || !orbitPolyline || !orbitLines || !orbitMaterial || !focusLabel) return;

    for (const polyline of orbitSegmentPolylines || []) {
      orbitLines.remove(polyline);
    }
    primitivesRef.current.orbitSegmentPolylines = [];

    const selectedColor = Cesium.Color.fromCssColorString('#22c55e');
    const selectedAColor = Cesium.Color.fromCssColorString('#22c55e');
    const selectedBColor = Cesium.Color.fromCssColorString('#eab308');
    const hoverColor = Cesium.Color.WHITE.withAlpha(0.95);
    const defaultColor = Cesium.Color.WHITE.withAlpha(0.55);
    const normalizedAId = selectedAId == null
      ? null
      : (Number.isNaN(Number(selectedAId)) ? selectedAId : Number(selectedAId));
    const normalizedBId = selectedBId == null
      ? null
      : (Number.isNaN(Number(selectedBId)) ? selectedBId : Number(selectedBId));

    for (const [id, item] of map.entries()) {
      const isSelected = id === selectedSatelliteId;
      const isHovered = id === hoveredSatelliteId;
      const isSelectedA = normalizedAId != null && id === normalizedAId;
      const isSelectedB = normalizedBId != null && id === normalizedBId;

      if (isSelectedA) {
        item.billboard.color = selectedAColor;
      } else if (isSelectedB) {
        item.billboard.color = selectedBColor;
      } else if (isSelected) {
        item.billboard.color = selectedColor;
      } else if (isHovered) {
        item.billboard.color = hoverColor;
      } else {
        item.billboard.color = defaultColor;
      }

      if (isSelectedA || isSelectedB || isSelected) {
        item.billboard.scale = SATELLITE_SELECTED_SCALE;
      } else if (isHovered) {
        item.billboard.scale = SATELLITE_HOVER_SCALE;
      } else {
        item.billboard.scale = SATELLITE_DEFAULT_SCALE;
      }
    }

    const hoverItem = hoveredSatelliteId != null ? map.get(hoveredSatelliteId) : null;
    if (hoverItem) {
      focusLabel.show = true;
      focusLabel.text = hoverItem.name;
      focusLabel.position = hoverItem.billboard.position;
    } else {
      focusLabel.show = false;
    }

    const segments = [];
    let currentSegment = [];
    let previous = null;

    for (const sample of selectedOrbit) {
      if (!sample?.position || !sample?.epoch_utc) continue;
      const pos = sample.position;

      if (previous) {
        const dx = pos.x - previous.x;
        const dy = pos.y - previous.y;
        const dz = pos.z - previous.z;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist > ORBIT_BREAK_DISTANCE_KM) {
          if (currentSegment.length > 1) {
            segments.push(currentSegment);
          }
          currentSegment = [];
        }
      }

      currentSegment.push(sample);
      previous = pos;
    }

    if (currentSegment.length > 1) {
      segments.push(currentSegment);
    }

    if (segments.length > 0) {
      const orbitPositions = segments[0]
        .map((sample) => {
          const sampleDate = new Date(sample.epoch_utc);
          const cartesian = eciToCesiumCartesian(sample.position, sampleDate);
          return new Cesium.Cartesian3(cartesian.x, cartesian.y, cartesian.z);
        });

      if (orbitPositions.length > 1) {
        orbitPolyline.show = true;
        orbitPolyline.positions = orbitPositions;
        orbitMaterial.uniforms.color = selectedColor.withAlpha(0.8);
      } else {
        orbitPolyline.show = false;
      }
    } else {
      orbitPolyline.show = false;
    }

    const nextSegmentPolylines = [];
    for (const segment of segments.slice(1)) {
      const segmentPositions = segment.map((sample) => {
        const sampleDate = new Date(sample.epoch_utc);
        const cartesian = eciToCesiumCartesian(sample.position, sampleDate);
        return new Cesium.Cartesian3(cartesian.x, cartesian.y, cartesian.z);
      });

      if (segmentPositions.length > 1) {
        const polyline = orbitLines.add({
          show: true,
          positions: segmentPositions,
          width: 2,
          material: orbitMaterial,
          arcType: Cesium.ArcType.NONE,
          id: `selected-orbit-${nextSegmentPolylines.length + 1}`,
        });
        nextSegmentPolylines.push(polyline);
      }
    }

    primitivesRef.current.orbitSegmentPolylines = nextSegmentPolylines;

    viewer.scene.requestRender();
  }, [hoveredSatelliteId, selectedSatelliteId, selectedOrbit, selectedAId, selectedBId]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    const { hotspotPoints } = primitivesRef.current;
    if (!hotspotPoints) return;

    hotspotPoints.removeAll();

    const visibleHotspots = (hotspots || []).slice(0, 40);
    for (const hotspot of visibleHotspots) {
      if (!hotspot?.position || !hotspot?.tca_utc) continue;

      const tcaDate = new Date(hotspot.tca_utc);
      const cartesian = eciToCesiumCartesian(hotspot.position, tcaDate);
      const score = Number(hotspot.hotspot_score || 0);
      let color = Cesium.Color.YELLOW.withAlpha(0.95);
      if (score >= 0.75) {
        color = Cesium.Color.RED.withAlpha(0.98);
      } else if (score >= 0.5) {
        color = Cesium.Color.ORANGE.withAlpha(0.95);
      }

      hotspotPoints.add({
        position: new Cesium.Cartesian3(cartesian.x, cartesian.y, cartesian.z),
        color,
        pixelSize: 7 + (score * 10),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      });
    }

    viewer.scene.requestRender();
  }, [hotspots]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    const { approachLine, approachMaterial } = primitivesRef.current;
    if (!approachLine || !approachMaterial) return;

    const satA = testSatellites.a;
    const satB = testSatellites.b;

    if (!testActive || !satA || !satB || !computed || overrideAMode !== 'override' || overrideBMode !== 'override') {
      approachLine.show = false;
      viewer.scene.requestRender();
      return;
    }

    const epoch = testSim.currentEpochUtc || satA.epochUtc || satB.epochUtc || new Date().toISOString();
    const epochDate = new Date(epoch);

    const separationKm = Math.sqrt(
      (satA.position.x - satB.position.x) ** 2 +
      (satA.position.y - satB.position.y) ** 2 +
      (satA.position.z - satB.position.z) ** 2
    );

    let color = '#22c55e';
    if (separationKm < 1) {
      color = '#ef4444';
    } else if (separationKm < 10) {
      color = '#f97316';
    } else if (separationKm < 100) {
      color = '#eab308';
    }

    const cartA = eciToCesiumCartesian(satA.position, epochDate);
    const cartB = eciToCesiumCartesian(satB.position, epochDate);
    approachLine.positions = [
      new Cesium.Cartesian3(cartA.x, cartA.y, cartA.z),
      new Cesium.Cartesian3(cartB.x, cartB.y, cartB.z),
    ];
    approachMaterial.uniforms.color = Cesium.Color.fromCssColorString(color).withAlpha(0.9);
    approachLine.show = true;

    viewer.scene.requestRender();
  }, [testActive, testSatellites, testSim, overrideAMode, overrideBMode, computed]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    const scene = viewer.scene;

    let lastFramePerfMs = performance.now();

    const updateMotion = () => {
      // Re-queue immediately to ensure the loop never dies
      motionRef.current.animationFrameId = requestAnimationFrame(updateMotion);

      const currentPerfMs = performance.now();
      const frameDeltaSec = Math.min((currentPerfMs - lastFramePerfMs) / 1000, 0.1);
      lastFramePerfMs = currentPerfMs;

      const { map, focusLabel } = primitivesRef.current;
      const snapshotTimestampMs = motionRef.current.lastSnapshotTimestampMs;
      const snapshotReceivedPerfMs = motionRef.current.lastSnapshotReceivedPerfMs;

      if (snapshotTimestampMs == null || map.size === 0) return;

      // Elapsed physical time since this data explicitly touched our browser
      const elapsedSeconds = Math.min(
        Math.max((currentPerfMs - snapshotReceivedPerfMs) / 1000, 0),
        SATELLITE_EXTRAPOLATION_LIMIT_SECONDS,
      );

      const frameDate = new Date(snapshotTimestampMs + (elapsedSeconds * 1000));
      const gmst = computeGmst(frameDate);
      const cosG = Math.cos(gmst);
      const sinG = Math.sin(gmst);
      
      const hoveredSatelliteId = useStore.getState().hoveredSatelliteId;
      const focusedItem = hoveredSatelliteId != null ? map.get(hoveredSatelliteId) : null;

      for (const item of map.values()) {
        if (!item.eciPosition) continue;

        const velocity = item.eciVelocity || ZERO_VELOCITY;
        
        // Target physical coordinate using pure local time extrapolation 
        const exactTargetEci = {
          x: item.eciPosition.x + velocity.vx * elapsedSeconds,
          y: item.eciPosition.y + velocity.vy * elapsedSeconds,
          z: item.eciPosition.z + velocity.vz * elapsedSeconds,
        };

        if (!item.renderedEci) {
          item.renderedEci = { ...exactTargetEci };
        } else {
          // Continuously push the rendered dot forward by its exact physical velocity and frame time
          item.renderedEci.x += velocity.vx * frameDeltaSec;
          item.renderedEci.y += velocity.vy * frameDeltaSec;
          item.renderedEci.z += velocity.vz * frameDeltaSec;

          // Compute remaining desync between the "theoretical" Target location and our integrated Rendered location
          const dx = exactTargetEci.x - item.renderedEci.x;
          const dy = exactTargetEci.y - item.renderedEci.y;
          const dz = exactTargetEci.z - item.renderedEci.z;
          const distSq = dx * dx + dy * dy + dz * dz;

          // If desync is huge (>200km distance), teleport.
          // This happens when scrubbing time or returning to a paused tab.
          if (distSq > 40000) {
            item.renderedEci.x = exactTargetEci.x;
            item.renderedEci.y = exactTargetEci.y;
            item.renderedEci.z = exactTargetEci.z;
          } else {
            // Apply a fractional lerp (~3% per frame @ 60fps) to invisibly drift back to perfect sync
            item.renderedEci.x += dx * 0.03;
            item.renderedEci.y += dy * 0.03;
            item.renderedEci.z += dz * 0.03;
          }
        }

        const cartesian = eciToCesiumCartesianFast(item.renderedEci, cosG, sinG);
        setBillboardPosition(item.billboard, cartesian);
      }

      if (focusedItem && focusLabel.show) {
        focusLabel.position = focusedItem.billboard.position;
      }
      
      viewer.scene.requestRender();
    };

    motionRef.current.animationFrameId = requestAnimationFrame(updateMotion);

    return () => {
      if (motionRef.current.animationFrameId) {
        cancelAnimationFrame(motionRef.current.animationFrameId);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', background: '#000' }}
    />
  );
};

export default CesiumGlobe;
