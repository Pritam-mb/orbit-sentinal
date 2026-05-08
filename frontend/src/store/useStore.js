import { create } from 'zustand';

const useStore = create((set, get) => ({
  // Satellite data
  satellites: [],
  selectedSatelliteId: null,
  hoveredSatelliteId: null,
  selectedOrbit: [],
  snapshotTimestamp: null,

  // Conjunction alerts
  alerts: [],

  // Maneuver controls
  maneuver: { dvx: 0, dvy: 0, dvz: 0 },

  // Connection status
  wsConnected: false,

  // Simulation
  simulationActive: false,

  // Actions
  setSatellites: (sats) => set({ satellites: sats }),

  setSnapshotTimestamp: (timestamp) => set({ snapshotTimestamp: timestamp }),

  setSelectedSatelliteId: (id) => set({ selectedSatelliteId: id }),

  setHoveredSatelliteId: (id) => set({ hoveredSatelliteId: id }),

  setSelectedOrbit: (orbit) => set({ selectedOrbit: orbit }),

  clearSelectedOrbit: () => set({ selectedOrbit: [] }),

  getSelectedSatellite: () => {
    const { satellites, selectedSatelliteId } = get();
    if (!selectedSatelliteId) return satellites[0] || null;
    return satellites.find((s) => s.norad_id === selectedSatelliteId) || null;
  },

  setAlerts: (alerts) => set({ alerts }),

  setManeuver: (axis, value) =>
    set((state) => ({
      maneuver: { ...state.maneuver, [axis]: value },
    })),

  resetManeuver: () => set({ maneuver: { dvx: 0, dvy: 0, dvz: 0 } }),

  setWsConnected: (connected) => set({ wsConnected: connected }),

  setSimulationActive: (active) => set({ simulationActive: active }),
}));

export default useStore;
