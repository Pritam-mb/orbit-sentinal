/**
 * Coordinate conversion utilities.
 * ECI (Earth-Centered Inertial) -> ECEF (Earth-Centered Earth-Fixed) -> LLA
 * Uses Greenwich Sidereal Time rotation matrix.
 */

/**
 * Compute Greenwich Mean Sidereal Time from a JS Date.
 * Returns angle in radians.
 */
export function computeGmst(date) {
  const JD_J2000 = 2451545.0;
  const msPerDay = 86400000;

  // Julian Date
  const jd = date.getTime() / msPerDay + 2440587.5;
  const T = (jd - JD_J2000) / 36525.0;

  // GMST in degrees
  let gmstDeg =
    280.46061837 +
    360.98564736629 * (jd - JD_J2000) +
    0.000387933 * T * T -
    (T * T * T) / 38710000.0;

  // Normalize to 0-360
  gmstDeg = ((gmstDeg % 360) + 360) % 360;

  return (gmstDeg * Math.PI) / 180.0;
}

/**
 * Convert ECI position to ECEF using GST rotation matrix.
 *
 * R_GST = [ cos(θ)   sin(θ)   0 ]
 *         [-sin(θ)   cos(θ)   0 ]
 *         [  0         0      1 ]
 *
 * @param {Object} eci - {x, y, z} in km (ECI frame)
 * @param {number} gmst - Greenwich Mean Sidereal Time in radians
 * @returns {Object} {x, y, z} in km (ECEF frame)
 */
export function eciToEcef(eci, gmst) {
  const cosG = Math.cos(gmst);
  const sinG = Math.sin(gmst);

  return {
    x: eci.x * cosG + eci.y * sinG,
    y: -eci.x * sinG + eci.y * cosG,
    z: eci.z,
  };
}

/**
 * Convert ECEF (km) to Cesium Cartesian3 (meters).
 * Cesium uses meters internally.
 *
 * @param {Object} ecef - {x, y, z} in km
 * @returns {Object} {x, y, z} in meters
 */
export function ecefToCartesian(ecef) {
  return {
    x: ecef.x * 1000,
    y: ecef.y * 1000,
    z: ecef.z * 1000,
  };
}

/**
 * Convert ECEF position to geodetic coordinates (lat, lon, alt).
 * Uses iterative method for WGS84 ellipsoid.
 *
 * @param {Object} ecef - {x, y, z} in km
 * @returns {Object} {lat, lon, alt} in degrees and km
 */
export function ecefToLla(ecef) {
  const a = 6378.137; // WGS84 semi-major axis (km)
  const f = 1.0 / 298.257223563;
  const b = a * (1 - f);
  const e2 = 1 - (b * b) / (a * a);

  const x = ecef.x;
  const y = ecef.y;
  const z = ecef.z;

  const lon = Math.atan2(y, x);
  const p = Math.sqrt(x * x + y * y);

  // Iterative latitude computation
  let lat = Math.atan2(z, p * (1 - e2));
  for (let i = 0; i < 10; i++) {
    const sinLat = Math.sin(lat);
    const N = a / Math.sqrt(1 - e2 * sinLat * sinLat);
    lat = Math.atan2(z + e2 * N * sinLat, p);
  }

  const sinLat = Math.sin(lat);
  const N = a / Math.sqrt(1 - e2 * sinLat * sinLat);
  const alt = p / Math.cos(lat) - N;

  return {
    lat: (lat * 180) / Math.PI,
    lon: (lon * 180) / Math.PI,
    alt: alt,
  };
}

/**
 * Full pipeline: ECI -> ECEF -> Cesium Cartesian3
 * @param {Object} eciPos - {x, y, z} in km
 * @param {Date} date - timestamp for GMST calculation
 * @returns {Object} {x, y, z} in meters (Cesium-ready)
 */
export function eciToCesiumCartesian(eciPos, date) {
  const gmst = computeGmst(date);
  const ecef = eciToEcef(eciPos, gmst);
  return ecefToCartesian(ecef);
}

/**
 * Full pipeline: ECI -> geodetic
 * @param {Object} eciPos - {x, y, z} in km
 * @param {Date} date - timestamp for GMST calculation
 * @returns {Object} {lat, lon, alt} in degrees and km
 */
export function eciToLla(eciPos, date) {
  const gmst = computeGmst(date);
  const ecef = eciToEcef(eciPos, gmst);
  return ecefToLla(ecef);
}
