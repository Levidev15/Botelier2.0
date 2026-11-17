// Process preload for candidate-only offline build/test processes. The sole
// permitted TCP target is the local temporary frontend server on port 5011.
const dns = require("node:dns");
const net = require("node:net");
const http = require("node:http");
const https = require("node:https");
const allowedPort = Number(process.env.OFFLINE_ALLOWED_PORT || "5011");
const allowedHosts = new Set(["127.0.0.1", "::1", "localhost"]);

function assertAllowed(host, port, operation) {
  const normalizedHost = String(host || "localhost").replace(/^\[|\]$/g, "").toLowerCase();
  if (!allowedHosts.has(normalizedHost) || Number(port) !== allowedPort) {
    throw new Error(`Offline test network guard denied ${operation} to ${normalizedHost}:${port}`);
  }
}

function optionsFrom(args, protocol) {
  const first = args[0];
  if (first instanceof URL || typeof first === "string") {
    const url = new URL(String(first));
    return { host: url.hostname, port: url.port || (url.protocol === "https:" ? 443 : 80) };
  }
  if (first && typeof first === "object") {
    const options = args[1] && typeof args[1] === "object"
      ? { ...first, ...args[1] }
      : first;
    return {
      host: options.hostname || options.host || "localhost",
      port: options.port || (protocol === "https:" ? 443 : 80),
      path: options.socketPath,
    };
  }
  return {
    host: typeof args[1] === "string" ? args[1] : "localhost",
    port: first,
  };
}

function guardOptions(args, protocol, operation) {
  const options = optionsFrom(args, protocol);
  if (options.path) {
    throw new Error(`Offline test network guard denied ${operation} over a socket path`);
  }
  assertAllowed(options.host, options.port, operation);
}

const originalSocketConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  guardOptions(args, "http:", "TCP");
  return originalSocketConnect.apply(this, args);
};

for (const [module, protocol] of [[http, "http:"], [https, "https:"]]) {
  const originalRequest = module.request;
  module.request = function (...args) {
    guardOptions(args, protocol, `${protocol} request`);
    return originalRequest.apply(this, args);
  };
  const originalGet = module.get;
  module.get = function (...args) {
    guardOptions(args, protocol, `${protocol} GET`);
    return originalGet.apply(this, args);
  };
}

const originalDnsLookup = dns.lookup;
dns.lookup = function (hostname, ...args) {
  if (!allowedHosts.has(String(hostname).toLowerCase())) {
    throw new Error(`Offline test network guard denied DNS lookup for ${hostname}`);
  }
  return originalDnsLookup.call(this, hostname, ...args);
};
for (const method of ["resolve", "resolve4", "resolve6", "resolveAny", "reverse"]) {
  if (typeof dns[method] === "function") {
    const originalResolve = dns[method];
    dns[method] = function (hostname, ...args) {
      if (!allowedHosts.has(String(hostname).toLowerCase())) {
        throw new Error(`Offline test network guard denied DNS lookup for ${hostname}`);
      }
      return originalResolve.call(this, hostname, ...args);
    };
  }
}

if (typeof globalThis.fetch === "function") {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = function (input, ...args) {
    const url = input instanceof URL ? input : new URL(String(input));
    assertAllowed(url.hostname, url.port || (url.protocol === "https:" ? 443 : 80), "fetch");
    return originalFetch.call(this, input, ...args);
  };
}
