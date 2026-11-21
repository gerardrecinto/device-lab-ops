// Same formula as src/devicelab/capacity.py. tests/test_page.py checks the two agree.
function plan(o) {
  const util = o.targetUtil, spare = o.sparePct;
  if (!(util > 0 && util <= 1) || !(spare >= 0 && spare < 100) || o.devicesPerHost < 1 || o.peak < 1 || o.jobsPerDay < 0 || o.jobMinutes < 0) return null;
  const working = Math.ceil((o.jobsPerDay * o.jobMinutes * o.peak) / (1440 * util) - 1e-9);
  const devices = Math.ceil(working / (1 - spare / 100) - 1e-9);
  const hosts = Math.ceil(devices / o.devicesPerHost - 1e-9) + o.spareHosts;
  return { working_devices: working, devices: devices, hosts: hosts, to_buy: Math.max(0, devices - o.existing) };
}
if (typeof module !== 'undefined') module.exports = { plan };
