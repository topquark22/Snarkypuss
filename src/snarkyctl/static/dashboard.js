(() => {
  "use strict";

  const dashboard = document.querySelector(".dashboard");
  const gatewayHeading = document.querySelector("#gateway-heading");
  const modeSummary = document.querySelector("#mode-summary");
  const exposureAlert = document.querySelector("#exposure-alert");
  const exposureMessage = document.querySelector("#exposure-message");
  const connectionState = document.querySelector("#connection-state");
  const partialFailures = document.querySelector("#partial-failures");
  const partialFailureList = document.querySelector("#partial-failure-list");

  const fields = {
    provider: document.querySelector("#provider"),
    target: document.querySelector("#target"),
    server: document.querySelector("#server"),
    interface: document.querySelector("#interface"),
    leakProtection: document.querySelector("#leak-protection"),
    lastRefreshed: document.querySelector("#last-refreshed"),
    dnsService: document.querySelector("#dns-service"),
    dnsState: document.querySelector("#dns-state"),
    systemUptime: document.querySelector("#system-uptime"),
    systemLoad: document.querySelector("#system-load"),
    systemMemory: document.querySelector("#system-memory"),
    systemDisk: document.querySelector("#system-disk"),
  };

  const summaries = {
    VPN: "Client traffic is using the configured upstream VPN.",
    LOCKED: "Public Internet forwarding is blocked to prevent an IP leak.",
    DIRECT: "Client traffic may leave through the VPS public connection.",
    UNKNOWN: "SnarkyCtl cannot confirm how client traffic reaches the Internet.",
  };

  function display(value) {
    return value === null || value === undefined || value === "" ? "—" : String(value);
  }

  function leakProtection(value) {
    if (value === true) {
      return "Active";
    }
    if (value === false) {
      return "Inactive";
    }
    return "Unknown";
  }

  function bytes(value) {
    if (!Number.isFinite(value)) {
      return "—";
    }
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let amount = value;
    let unit = units[0];
    for (const candidate of units) {
      unit = candidate;
      if (amount < 1024 || candidate === units.at(-1)) {
        break;
      }
      amount /= 1024;
    }
    return `${amount.toFixed(1)} ${unit}`;
  }

  function duration(totalSeconds) {
    if (!Number.isFinite(totalSeconds)) {
      return "—";
    }
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    return [days ? `${days}d` : "", hours || days ? `${hours}h` : "", `${minutes}m`]
      .filter(Boolean)
      .join(" ");
  }

  function applyStatus(payload) {
    const status = payload.vpn_status;
    const mode = status?.gateway_mode || "UNKNOWN";
    dashboard.dataset.mode = mode;
    gatewayHeading.textContent = mode;
    modeSummary.textContent = summaries[mode] || summaries.UNKNOWN;
    connectionState.textContent = display(status?.state || "Unavailable");
    fields.provider.textContent = display(status?.provider);
    fields.target.textContent = display(status?.target);
    fields.server.textContent = display(status?.display_name);
    fields.interface.textContent = display(status?.interface);
    fields.leakProtection.textContent = leakProtection(status?.leak_protection_active);
    fields.lastRefreshed.textContent = new Date(payload.checked_at).toLocaleTimeString();

    fields.dnsService.textContent = display(payload.dns?.service);
    fields.dnsState.textContent = payload.dns
      ? `${display(payload.dns.active_state)} (${display(payload.dns.sub_state)})`
      : "Unavailable";

    fields.systemUptime.textContent = duration(payload.system?.uptime_seconds);
    fields.systemLoad.textContent = payload.system?.load_average
      ? payload.system.load_average.map((value) => value.toFixed(2)).join(" / ")
      : "Unavailable";
    fields.systemMemory.textContent = payload.system
      ? `${bytes(payload.system.memory_available_bytes)} / ${bytes(payload.system.memory_total_bytes)}`
      : "Unavailable";
    fields.systemDisk.textContent = payload.system
      ? `${bytes(payload.system.root_disk_free_bytes)} / ${bytes(payload.system.root_disk_total_bytes)}`
      : "Unavailable";

    partialFailureList.replaceChildren();
    for (const failure of payload.partial_failures || []) {
      const item = document.createElement("li");
      item.textContent = `${failure.component}: ${failure.message}`;
      partialFailureList.append(item);
    }
    partialFailures.hidden = partialFailureList.children.length === 0;

    const showWarning = payload.public_ip_exposed !== false;
    exposureAlert.hidden = !showWarning;
    exposureMessage.textContent = showWarning ? display(payload.exposure_warning) : "";
  }

  function applyError(message) {
    dashboard.dataset.mode = "ERROR";
    gatewayHeading.textContent = "UNAVAILABLE";
    modeSummary.textContent = message;
    connectionState.textContent = "Unavailable";
    exposureAlert.hidden = false;
    exposureMessage.textContent =
      "Gateway safety cannot be confirmed until status communication is restored.";
    fields.lastRefreshed.textContent = new Date().toLocaleTimeString();
    partialFailures.hidden = true;
  }

  async function refresh() {
    try {
      const response = await fetch("/api/v2/status", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error?.message || `Status request failed (${response.status})`);
      }
      applyStatus(payload);
    } catch (error) {
      applyError(error instanceof Error ? error.message : "Status request failed.");
    }
  }

  refresh();
  window.setInterval(refresh, 5000);
})();
