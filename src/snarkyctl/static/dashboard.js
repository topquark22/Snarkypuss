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
  const targetSelect = document.querySelector("#vpn-target");
  const connectButton = document.querySelector("#vpn-connect");
  const controlMessage = document.querySelector("#vpn-control-message");
  const protectedButton = document.querySelector("#mode-protected");
  const lockedButton = document.querySelector("#mode-locked");
  const directButton = document.querySelector("#mode-direct");
  const directConfirmation = document.querySelector("#direct-confirmation");
  const modeControlMessage = document.querySelector("#mode-control-message");
  const targetManager = document.querySelector(".target-manager");
  const managerProvider = document.querySelector("#manager-provider");
  const managerRevision = document.querySelector("#manager-revision");
  const editorList = document.querySelector("#target-editor-list");
  const addTargetButton = document.querySelector("#target-add");
  const reloadTargetsButton = document.querySelector("#target-reload");
  const saveTargetsButton = document.querySelector("#target-save");
  const managerMessage = document.querySelector("#target-manager-message");

  let catalogueAvailable = false;
  let modeControlsAvailable = false;
  let operationInProgress = false;
  let currentTarget = null;
  let managerLoaded = false;
  let managerBusy = false;
  let targetSchema = null;
  let editableCatalogue = null;
  let newDestinationDraft = null;

  const fields = {
    provider: document.querySelector("#provider"),
    target: document.querySelector("#target"),
    server: document.querySelector("#server"),
    interface: document.querySelector("#interface"),
    publicIp: document.querySelector("#public-ip"),
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

  function setControlMessage(message, state = "") {
    controlMessage.textContent = message;
    if (state) {
      controlMessage.dataset.state = state;
    } else {
      delete controlMessage.dataset.state;
    }
  }

  function setModeControlMessage(message, state = "") {
    modeControlMessage.textContent = message;
    if (state) {
      modeControlMessage.dataset.state = state;
    } else {
      delete modeControlMessage.dataset.state;
    }
  }

  function setManagerMessage(message, state = "") {
    managerMessage.textContent = message;
    if (state) {
      managerMessage.dataset.state = state;
    } else {
      delete managerMessage.dataset.state;
    }
  }

  function managerRequest(path, options = {}) {
    return fetch(path, {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
  }

  function selectorDefaults(kindSchema) {
    const selector = { kind: kindSchema.kind };
    for (const field of kindSchema.fields || []) {
      selector[field.name] =
        field.field_type === "boolean"
          ? false
          : field.field_type === "integer"
            ? 0
            : field.choices?.[0] || "";
    }
    return selector;
  }

  function fieldControl(field, value, onChange) {
    const wrapper = document.createElement("label");
    wrapper.className = "editor-field";
    const caption = document.createElement("span");
    caption.textContent = field.label;
    wrapper.append(caption);
    let control;
    if (field.field_type === "choice") {
      control = document.createElement("select");
      for (const choice of field.choices || []) {
        const option = document.createElement("option");
        option.value = choice;
        option.textContent = choice;
        control.append(option);
      }
      control.value = String(value ?? "");
    } else {
      control = document.createElement("input");
      control.type =
        field.field_type === "boolean"
          ? "checkbox"
          : field.field_type === "integer"
            ? "number"
            : "text";
      if (control.type === "checkbox") {
        control.checked = value === true;
      } else {
        control.value = String(value ?? "");
      }
      if (field.max_length) {
        control.maxLength = field.max_length;
      }
    }
    control.required = field.required === true;
    control.addEventListener("input", () => {
      const nextValue =
        control.type === "checkbox"
          ? control.checked
          : field.field_type === "integer"
            ? Number(control.value)
            : control.value;
      onChange(nextValue);
    });
    wrapper.append(control);
    return wrapper;
  }

  function hasUnfinishedDestination() {
    return editableCatalogue?.targets.some(
      (target) => target.alias.trim() === "" || target.label.trim() === "",
    );
  }

  function renderEditor() {
    editorList.replaceChildren();
    if (!editableCatalogue || !targetSchema) {
      return;
    }
    editableCatalogue.targets.forEach((target, index) => {
      const card = document.createElement("article");
      card.className = "target-editor-card";
      const heading = document.createElement("div");
      heading.className = "editor-card-heading";
      const title = document.createElement("strong");
      title.textContent = `Destination ${index + 1}`;
      const controls = document.createElement("div");
      for (const [label, offset] of [["↑", -1], ["↓", 1]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = offset < 0 ? "Move up" : "Move down";
        button.disabled =
          managerBusy ||
          (offset < 0 && index === 0) ||
          (offset > 0 && index === editableCatalogue.targets.length - 1);
        button.addEventListener("click", () => {
          const other = index + offset;
          [editableCatalogue.targets[index], editableCatalogue.targets[other]] = [
            editableCatalogue.targets[other],
            editableCatalogue.targets[index],
          ];
          renderEditor();
        });
        controls.append(button);
      }
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Remove";
      remove.disabled = managerBusy;
      remove.addEventListener("click", () => {
        if (window.confirm(`Remove destination “${target.label || target.alias || index + 1}”?`)) {
          if (target === newDestinationDraft) {
            newDestinationDraft = null;
          }
          editableCatalogue.targets.splice(index, 1);
          renderEditor();
        }
      });
      controls.append(remove);
      heading.append(title, controls);
      card.append(heading);

      const core = document.createElement("div");
      core.className = "editor-fields";
      core.append(
        fieldControl(
          { label: "Alias", field_type: "text", required: true, max_length: 32 },
          target.alias,
          (value) => {
            target.alias = value;
          },
        ),
        fieldControl(
          { label: "Label", field_type: "text", required: true, max_length: 100 },
          target.label,
          (value) => {
            target.label = value;
          },
        ),
      );
      const kindLabel = document.createElement("label");
      kindLabel.className = "editor-field";
      const kindCaption = document.createElement("span");
      kindCaption.textContent = "Target type";
      const kindSelect = document.createElement("select");
      for (const kind of targetSchema.selector_kinds) {
        const option = document.createElement("option");
        option.value = kind.kind;
        option.textContent = kind.label;
        kindSelect.append(option);
      }
      kindSelect.value = target.selector.kind;
      kindSelect.addEventListener("change", () => {
        const kind = targetSchema.selector_kinds.find((item) => item.kind === kindSelect.value);
        target.selector = selectorDefaults(kind);
        renderEditor();
      });
      kindLabel.append(kindCaption, kindSelect);
      core.append(kindLabel);
      card.append(core);

      const selectedKind = targetSchema.selector_kinds.find(
        (item) => item.kind === target.selector.kind,
      );
      const selectorFields = document.createElement("div");
      selectorFields.className = "editor-fields selector-fields";
      for (const field of selectedKind?.fields || []) {
        selectorFields.append(
          fieldControl(field, target.selector[field.name], (value) => {
            target.selector[field.name] = value;
          }),
        );
      }
      card.append(selectorFields);
      editorList.append(card);
    });
    addTargetButton.disabled =
      managerBusy ||
      editableCatalogue.targets.length >= 100 ||
      newDestinationDraft !== null ||
      hasUnfinishedDestination();
    reloadTargetsButton.disabled = managerBusy;
    saveTargetsButton.disabled = managerBusy;
  }

  async function loadManager() {
    if (managerBusy) {
      return;
    }
    managerBusy = true;
    setManagerMessage("Loading editable catalogue…");
    renderEditor();
    try {
      const [schemaResponse, catalogueResponse] = await Promise.all([
        managerRequest("/api/v3/admin/vpn/target-schema"),
        managerRequest("/api/v3/admin/vpn/targets"),
      ]);
      const schemaPayload = await schemaResponse.json();
      const cataloguePayload = await catalogueResponse.json();
      if (!schemaResponse.ok) {
        throw new Error(schemaPayload.error?.message || "Target schema request failed.");
      }
      if (!catalogueResponse.ok) {
        throw new Error(cataloguePayload.error?.message || "Editable catalogue request failed.");
      }
      targetSchema = schemaPayload;
      editableCatalogue = {
        ...cataloguePayload,
        targets: cataloguePayload.targets.map((target) => ({
          ...target,
          selector: { ...target.selector },
        })),
      };
      managerProvider.textContent = editableCatalogue.provider;
      managerRevision.textContent = String(editableCatalogue.revision);
      newDestinationDraft = null;
      managerLoaded = true;
      setManagerMessage(`${editableCatalogue.targets.length} destination(s) loaded.`);
    } catch (error) {
      managerLoaded = false;
      setManagerMessage(error instanceof Error ? error.message : "Catalogue loading failed.", "error");
    } finally {
      managerBusy = false;
      renderEditor();
    }
  }

  function addDestination() {
    if (
      !targetSchema ||
      !editableCatalogue ||
      editableCatalogue.targets.length >= 100 ||
      newDestinationDraft !== null ||
      hasUnfinishedDestination()
    ) {
      return;
    }
    const kind = targetSchema.selector_kinds[0];
    newDestinationDraft = {
      alias: "",
      label: "",
      selector: selectorDefaults(kind),
    };
    editableCatalogue.targets.push(newDestinationDraft);
    renderEditor();
  }

  function validateEditor() {
    if (!editableCatalogue?.targets.length) {
      return "The catalogue must contain at least one destination.";
    }
    const aliases = new Set();
    for (const target of editableCatalogue.targets) {
      if (!/^[a-z][a-z0-9_-]{0,31}$/.test(target.alias)) {
        return `Invalid alias: ${target.alias || "(empty)"}`;
      }
      if (aliases.has(target.alias)) {
        return `Duplicate alias: ${target.alias}`;
      }
      aliases.add(target.alias);
      if (!target.label || target.label.length > 100) {
        return `Destination ${target.alias} requires a label of at most 100 characters.`;
      }
      const kind = targetSchema.selector_kinds.find(
        (item) => item.kind === target.selector.kind,
      );
      if (!kind) {
        return `Destination ${target.alias} has an unsupported target type.`;
      }
      for (const field of kind.fields || []) {
        if (field.required && (target.selector[field.name] === "" || target.selector[field.name] == null)) {
          return `Destination ${target.alias} requires ${field.label}.`;
        }
      }
    }
    return null;
  }

  async function saveManager() {
    if (!managerLoaded || managerBusy) {
      return;
    }
    const validation = validateEditor();
    if (validation) {
      setManagerMessage(validation, "error");
      return;
    }
    managerBusy = true;
    setManagerMessage("Saving complete catalogue…");
    renderEditor();
    const targets = editableCatalogue.targets.map((target, position) => ({
      alias: target.alias,
      label: target.label,
      position,
      selector: target.selector,
    }));
    try {
      const response = await managerRequest("/api/v3/admin/vpn/targets", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-SnarkyCtl-Request": "1",
        },
        body: JSON.stringify({
          provider: editableCatalogue.provider,
          expected_revision: editableCatalogue.revision,
          targets,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        const conflict = payload.error?.code === "CATALOG_CONFLICT";
        throw new Error(
          conflict
            ? "The catalogue changed in another session. Reload before saving again."
            : payload.error?.message || `Catalogue save failed (${response.status}).`,
        );
      }
      editableCatalogue = { ...payload, targets: payload.targets.map((target) => ({
        ...target,
        selector: { ...target.selector },
      })) };
      newDestinationDraft = null;
      managerRevision.textContent = String(editableCatalogue.revision);
      setManagerMessage("Catalogue saved.", "success");
      await loadTargets();
    } catch (error) {
      setManagerMessage(error instanceof Error ? error.message : "Catalogue save failed.", "error");
    } finally {
      managerBusy = false;
      renderEditor();
    }
  }

  function syncTargetControl() {
    const selectedTarget = targetSelect.value;
    targetSelect.disabled = !catalogueAvailable || operationInProgress;
    connectButton.disabled = !catalogueAvailable || operationInProgress || !selectedTarget;
    connectButton.textContent =
      selectedTarget && selectedTarget === currentTarget ? "Reconnect" : "Connect / switch";
  }

  function syncModeControls() {
    const selectedTarget = targetSelect.value;
    protectedButton.disabled =
      !modeControlsAvailable || operationInProgress || !selectedTarget;
    lockedButton.disabled = !modeControlsAvailable || operationInProgress;
    directConfirmation.disabled = !modeControlsAvailable || operationInProgress;
    directButton.disabled =
      !modeControlsAvailable ||
      operationInProgress ||
      directConfirmation.value !== "EXPOSE VPS IP";
  }

  function syncControls() {
    syncTargetControl();
    syncModeControls();
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
    fields.publicIp.textContent = display(payload.public_ip?.address);
    fields.leakProtection.textContent = leakProtection(status?.leak_protection_active);
    fields.lastRefreshed.textContent = new Date(payload.checked_at).toLocaleTimeString();
    currentTarget = status?.target || null;
    if (currentTarget && targetSelect.querySelector(`option[value="${currentTarget}"]`)) {
      targetSelect.value = currentTarget;
    }
    syncControls();

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
    fields.publicIp.textContent = "Unavailable";
    fields.dnsService.textContent = "Unavailable";
    fields.dnsState.textContent = "Unavailable";
    fields.systemUptime.textContent = "Unavailable";
    fields.systemLoad.textContent = "Unavailable";
    fields.systemMemory.textContent = "Unavailable";
    fields.systemDisk.textContent = "Unavailable";
    fields.lastRefreshed.textContent = new Date().toLocaleTimeString();
    partialFailures.hidden = true;
  }

  async function loadTargets() {
    try {
      const response = await fetch("/api/v2/vpn/targets", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(
          payload.error?.message || `Target catalogue request failed (${response.status})`,
        );
      }

      targetSelect.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Select a target…";
      placeholder.disabled = true;
      placeholder.selected = true;
      targetSelect.append(placeholder);
      for (const target of payload.targets || []) {
        const option = document.createElement("option");
        option.value = target.alias;
        option.textContent = target.label;
        targetSelect.append(option);
      }

      catalogueAvailable =
        payload.capabilities?.connect === true &&
        payload.capabilities?.target_selection === true &&
        targetSelect.options.length > 1;
      modeControlsAvailable =
        payload.capabilities?.disconnect === true &&
        payload.capabilities?.leak_protection_configuration === true;

      if (!catalogueAvailable) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "Target selection is unavailable";
        targetSelect.replaceChildren(option);
        setControlMessage("The configured provider does not support target selection.");
      } else {
        if (currentTarget && targetSelect.querySelector(`option[value="${currentTarget}"]`)) {
          targetSelect.value = currentTarget;
        }
        setControlMessage(`${targetSelect.options.length - 1} approved target(s) available.`);
      }
      setModeControlMessage(
        modeControlsAvailable
          ? "Choose a mode. Direct VPS requires explicit confirmation."
          : "The configured provider cannot change leak-protection policy.",
      );
    } catch (error) {
      catalogueAvailable = false;
      modeControlsAvailable = false;
      targetSelect.replaceChildren();
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Targets unavailable";
      targetSelect.append(option);
      setControlMessage(
        error instanceof Error ? error.message : "Target catalogue request failed.",
        "error",
      );
      setModeControlMessage("Advanced gateway modes are unavailable.", "error");
    }
    syncControls();
  }

  async function connectSelectedTarget() {
    const target = targetSelect.value;
    if (!catalogueAvailable || operationInProgress || !target) {
      return;
    }

    operationInProgress = true;
    setControlMessage("Requesting VPN connection…");
    syncControls();
    try {
      const response = await fetch("/api/v2/vpn/connect", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-SnarkyCtl-Request": "1",
        },
        body: JSON.stringify({ target }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error?.message || `Connection request failed (${response.status})`);
      }
      currentTarget = payload.vpn_status?.target || target;
      targetSelect.value = currentTarget;
      setControlMessage(payload.message || "VPN connection completed.", "success");
      await refresh();
    } catch (error) {
      setControlMessage(
        error instanceof Error ? error.message : "Connection request failed.",
        "error",
      );
    } finally {
      operationInProgress = false;
      syncControls();
    }
  }

  async function requestMode(path, body, pendingMessage) {
    if (!modeControlsAvailable || operationInProgress) {
      return;
    }

    operationInProgress = true;
    setModeControlMessage(pendingMessage);
    syncControls();
    try {
      const response = await fetch(path, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-SnarkyCtl-Request": "1",
        },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error?.message || `Mode request failed (${response.status})`);
      }
      currentTarget = payload.vpn_status?.target || currentTarget;
      setModeControlMessage(payload.message || "Gateway mode changed.", "success");
      directConfirmation.value = "";
      await refresh();
    } catch (error) {
      setModeControlMessage(
        error instanceof Error ? error.message : "Gateway mode request failed.",
        "error",
      );
    } finally {
      operationInProgress = false;
      syncControls();
    }
  }

  function enableProtectedMode() {
    const target = targetSelect.value;
    if (!target) {
      return;
    }
    requestMode(
      "/api/v2/mode/protected",
      { target },
      "Enabling leak protection and connecting…",
    );
  }

  function enableLockedMode() {
    requestMode("/api/v2/mode/locked", {}, "Enabling leak protection and disconnecting…");
  }

  function enableDirectMode() {
    if (directConfirmation.value !== "EXPOSE VPS IP") {
      return;
    }
    requestMode(
      "/api/v2/mode/direct",
      { confirmation: directConfirmation.value },
      "Disabling leak protection and disconnecting…",
    );
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

  targetSelect.addEventListener("change", syncControls);
  connectButton.addEventListener("click", connectSelectedTarget);
  protectedButton.addEventListener("click", enableProtectedMode);
  lockedButton.addEventListener("click", enableLockedMode);
  directConfirmation.addEventListener("input", syncModeControls);
  directButton.addEventListener("click", enableDirectMode);
  targetManager.addEventListener("toggle", () => {
    if (targetManager.open && !managerLoaded) {
      loadManager();
    }
  });
  addTargetButton.addEventListener("click", addDestination);
  reloadTargetsButton.addEventListener("click", loadManager);
  saveTargetsButton.addEventListener("click", saveManager);
  refresh();
  loadTargets();
  window.setInterval(refresh, 5000);
})();
