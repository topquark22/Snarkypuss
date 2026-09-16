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
  let committedCatalogue = null;
  let newDestinationDraft = null;
  let cleanupInProgress = false;
  const discoveryState = new WeakMap();
  const autoLabelTargets = new WeakSet();
  const autoAliasTargets = new WeakSet();
  const targetIdentity = new WeakMap();
  const unavailableTargets = new Set();

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

  function fieldDefault(field) {
    if (field.field_type === "boolean") {
      return false;
    }
    if (field.field_type === "integer") {
      return 0;
    }
    if (field.option_source !== "provider" && field.choices?.length) {
      return field.choices[0];
    }
    return "";
  }

  function selectorDefaults(kindSchema) {
    const selector = { kind: kindSchema.kind };
    for (const field of kindSchema.fields || []) {
      selector[field.name] = fieldDefault(field);
    }
    return selector;
  }

  function fieldControl(field, value, onChange, settings = {}) {
    const wrapper = document.createElement("label");
    wrapper.className = "editor-field";
    const caption = document.createElement("span");
    caption.textContent = field.label;
    wrapper.append(caption);
    let control;
    if (field.field_type === "choice") {
      control = document.createElement("select");
      const choices = settings.choices || (field.choices || []).map((choice) => ({
        value: choice,
        label: choice,
      }));
      if (settings.placeholder) {
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = settings.placeholder;
        placeholder.disabled = settings.placeholderDisabled !== false;
        control.append(placeholder);
      }
      for (const choice of choices) {
        const option = document.createElement("option");
        option.value = choice.value;
        option.textContent = choice.label;
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
    control.disabled = settings.disabled === true;
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
    if (settings.note) {
      const note = document.createElement("small");
      note.className = "control-message";
      if (settings.noteState) {
        note.dataset.state = settings.noteState;
      }
      note.textContent = settings.note;
      wrapper.append(note);
    }
    return wrapper;
  }

  function cloneEditableTarget(target) {
    const clone = {
      ...target,
      selector: { ...target.selector },
    };
    targetIdentity.set(clone, target.alias);
    return clone;
  }

  function adoptCommittedCatalogue(payload) {
    committedCatalogue = payload;
    editableCatalogue = {
      ...payload,
      targets: payload.targets.map(cloneEditableTarget),
    };
    newDestinationDraft = null;
    managerRevision.textContent = String(editableCatalogue.revision);
  }

  function targetOptionLabel(target, field) {
    const value = target.selector[field.name];
    if (value === "" || value === null || value === undefined) {
      return null;
    }
    if (field.field_type === "choice" && field.option_source === "provider") {
      const state = discoveryState.get(target)?.get(field.name);
      if (state?.status !== "ready") {
        return null;
      }
      const option = state.options.find(
        (item) => String(item.value) === String(value),
      );
      return option?.label || null;
    }
    return String(value);
  }

  function dependencyDepth(field, fieldsByName, visiting = new Set()) {
    if (visiting.has(field.name)) {
      return 0;
    }
    visiting.add(field.name);
    const dependencies = (field.depends_on || [])
      .map((name) => fieldsByName.get(name))
      .filter(Boolean);
    const depth = dependencies.length
      ? 1 + Math.max(
        ...dependencies.map((item) => dependencyDepth(item, fieldsByName, visiting)),
      )
      : 0;
    visiting.delete(field.name);
    return depth;
  }

  function suggestedTargetLabel(target, kindSchema) {
    const fieldsByName = new Map(
      (kindSchema.fields || []).map((field) => [field.name, field]),
    );
    const selections = (kindSchema.fields || [])
      .map((field, index) => ({
        index,
        depth: dependencyDepth(field, fieldsByName),
        label: targetOptionLabel(target, field),
      }))
      .filter((item) => item.label);
    selections.sort((left, right) => right.depth - left.depth || left.index - right.index);
    if (selections.length) {
      return selections.map((item) => item.label).join(", ");
    }
    return (kindSchema.fields || []).length === 0 ? kindSchema.label : "";
  }

  function updateAutoLabel(target, kindSchema) {
    if (!autoLabelTargets.has(target)) {
      return;
    }
    target.label = suggestedTargetLabel(target, kindSchema).slice(0, 100);
  }

  function normalizedAlias(value) {
    const ascii = value
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "");
    let alias = ascii
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    if (!alias) {
      alias = "target";
    }
    if (!/^[a-z]/.test(alias)) {
      alias = `target_${alias}`;
    }
    alias = alias.slice(0, 32).replace(/_+$/g, "");
    return alias || "target";
  }

  function uniqueAlias(target, label) {
    const used = new Set(["recommended"]);
    for (const item of editableCatalogue?.targets || []) {
      if (item !== target && item.alias) {
        used.add(item.alias);
      }
    }

    const base = normalizedAlias(label);
    if (!used.has(base)) {
      return base;
    }

    let sequence = 2;
    while (true) {
      const suffix = `_${sequence}`;
      const stem = base
        .slice(0, 32 - suffix.length)
        .replace(/_+$/g, "");
      const candidate = `${stem}${suffix}`;
      if (!used.has(candidate)) {
        return candidate;
      }
      sequence += 1;
    }
  }

  function updateAutoAlias(target, kindSchema) {
    if (!autoAliasTargets.has(target)) {
      return;
    }
    const label = suggestedTargetLabel(target, kindSchema);
    target.alias = label ? uniqueAlias(target, label) : "";
  }

  function updateAutoMetadata(target, kindSchema) {
    updateAutoLabel(target, kindSchema);
    updateAutoAlias(target, kindSchema);
  }

  function populateTargetSelect(targets) {
    targetSelect.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select a target…";
    placeholder.disabled = true;
    placeholder.selected = true;
    targetSelect.append(placeholder);
    for (const target of targets || []) {
      const option = document.createElement("option");
      option.value = target.alias;
      option.textContent = target.label;
      targetSelect.append(option);
    }
    if (currentTarget && targetSelect.querySelector(`option[value="${currentTarget}"]`)) {
      targetSelect.value = currentTarget;
    }
  }

  function catalogueTargetsForRequest(targets) {
    return targets.map((target, position) => ({
      alias: target.alias,
      label: target.label,
      position,
      selector: target.selector,
    }));
  }

  async function replaceCatalogueTargets(targets) {
    const response = await managerRequest("/api/v3/admin/vpn/targets", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-SnarkyCtl-Request": "1",
      },
      body: JSON.stringify({
        provider: committedCatalogue.provider,
        expected_revision: committedCatalogue.revision,
        targets: catalogueTargetsForRequest(targets),
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
    return payload;
  }

  function queueUnavailableTarget(target) {
    if (!editableCatalogue?.targets.includes(target) || target === newDestinationDraft) {
      return;
    }
    unavailableTargets.add(target);
    void cleanupUnavailableTargets();
  }

  async function cleanupUnavailableTargets() {
    if (
      cleanupInProgress ||
      managerBusy ||
      !managerLoaded ||
      !committedCatalogue ||
      unavailableTargets.size === 0
    ) {
      return;
    }

    const removing = new Set(
      [...unavailableTargets].filter((target) => editableCatalogue.targets.includes(target)),
    );
    unavailableTargets.clear();
    if (removing.size === 0) {
      return;
    }

    const removedAliases = new Set(
      [...removing].map((target) => targetIdentity.get(target) || target.alias),
    );
    const committedTargets = committedCatalogue.targets.filter(
      (target) => !removedAliases.has(target.alias),
    );
    if (committedTargets.length === 0) {
      setManagerMessage(
        "The only saved destination is no longer available and cannot be removed automatically.",
        "error",
      );
      return;
    }

    const editableTargets = editableCatalogue.targets.filter(
      (target) => !removing.has(target),
    );
    cleanupInProgress = true;
    managerBusy = true;
    setManagerMessage(
      `Removing ${removing.size} unavailable destination(s)…`,
    );
    renderEditor();
    try {
      const payload = await replaceCatalogueTargets(committedTargets);
      committedCatalogue = payload;
      editableCatalogue = {
        ...payload,
        targets: editableTargets,
      };
      managerRevision.textContent = String(payload.revision);
      await loadTargets();
      setManagerMessage(
        `Removed ${removing.size} unavailable destination(s).`,
        "success",
      );
      syncControls();
    } catch (error) {
      setManagerMessage(
        error instanceof Error ? error.message : "Unavailable destination cleanup failed.",
        "error",
      );
    } finally {
      managerBusy = false;
      cleanupInProgress = false;
      renderEditor();
      if (unavailableTargets.size) {
        void cleanupUnavailableTargets();
      }
    }
  }

  function targetDiscovery(target) {
    let state = discoveryState.get(target);
    if (!state) {
      state = new Map();
      discoveryState.set(target, state);
    }
    return state;
  }

  function dependenciesHaveValues(target, field) {
    return (field.depends_on || []).every((name) => {
      const value = target.selector[name];
      return value !== "" && value !== null && value !== undefined;
    });
  }

  function discoveryContext(target, field) {
    const context = {};
    for (const name of field.depends_on || []) {
      context[name] = target.selector[name];
    }
    return context;
  }

  function discoveryContextKey(context) {
    return JSON.stringify(Object.entries(context));
  }

  function clearDependentFields(target, kindSchema, changedField) {
    const states = discoveryState.get(target);
    for (const field of kindSchema.fields || []) {
      if (!(field.depends_on || []).includes(changedField)) {
        continue;
      }
      target.selector[field.name] = fieldDefault(field);
      states?.delete(field.name);
      clearDependentFields(target, kindSchema, field.name);
    }
  }

  async function loadProviderOptions(target, kindSchema, field, state, context) {
    const params = new URLSearchParams({
      kind: kindSchema.kind,
      field: field.name,
    });
    for (const [name, value] of Object.entries(context)) {
      params.append(name, String(value));
    }
    try {
      const response = await managerRequest(
        `/api/v3/admin/vpn/target-options?${params.toString()}`,
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error?.message || `Option discovery failed (${response.status}).`);
      }
      const current = discoveryState.get(target)?.get(field.name);
      if (current !== state) {
        return;
      }
      if (
        payload.kind !== kindSchema.kind ||
        payload.field !== field.name ||
        !Array.isArray(payload.options)
      ) {
        throw new Error("Target option response does not match the requested field.");
      }
      state.status = "ready";
      state.options = payload.options;
      state.message = "";
      updateAutoMetadata(target, kindSchema);
      const value = target.selector[field.name];
      if (
        value !== "" &&
        value !== null &&
        value !== undefined &&
        !state.options.some((option) => String(option.value) === String(value))
      ) {
        state.status = "removing";
        state.message = "Saved value is no longer available; removing this destination.";
        queueUnavailableTarget(target);
      }
    } catch (error) {
      const current = discoveryState.get(target)?.get(field.name);
      if (current !== state) {
        return;
      }
      state.status = "error";
      state.options = [];
      state.message = error instanceof Error ? error.message : "Target option discovery failed.";
    } finally {
      if (discoveryState.get(target)?.get(field.name) === state) {
        renderEditor();
      }
    }
  }

  function ensureProviderOptions(target, kindSchema, field) {
    if (field.option_source !== "provider" || !dependenciesHaveValues(target, field)) {
      return null;
    }
    const context = discoveryContext(target, field);
    const contextKey = discoveryContextKey(context);
    const states = targetDiscovery(target);
    const existing = states.get(field.name);
    if (existing?.contextKey === contextKey) {
      return existing;
    }
    const state = {
      contextKey,
      status: "loading",
      options: [],
      message: "",
    };
    states.set(field.name, state);
    void loadProviderOptions(target, kindSchema, field, state, context);
    return state;
  }

  function providerFieldControl(target, kindSchema, field) {
    const value = target.selector[field.name];
    if (!dependenciesHaveValues(target, field)) {
      return fieldControl(
        field,
        value,
        () => {},
        {
          disabled: true,
          placeholder: "Choose required fields first…",
          note: "This field becomes available after its dependencies are selected.",
        },
      );
    }

    const state = ensureProviderOptions(target, kindSchema, field);
    if (!state || state.status === "loading") {
      const choices = value
        ? [{ value: String(value), label: `${value} (checking…)` }]
        : [];
      return fieldControl(
        field,
        value,
        () => {},
        {
          choices,
          disabled: true,
          placeholder: value ? "" : "Loading options…",
          note: "Loading current options from the VPN provider…",
        },
      );
    }

    if (state.status === "removing") {
      const choices = value
        ? [{ value: String(value), label: String(value) }]
        : [];
      return fieldControl(
        field,
        value,
        () => {},
        {
          choices,
          disabled: true,
          placeholder: value ? "" : "Removing unavailable destination…",
          note: state.message,
        },
      );
    }

    if (state.status === "error") {
      const choices = value
        ? [{ value: String(value), label: `${value} (options unavailable)` }]
        : [];
      return fieldControl(
        field,
        value,
        () => {},
        {
          choices,
          disabled: true,
          placeholder: value ? "" : "Options unavailable",
          note: state.message,
          noteState: "error",
        },
      );
    }

    return fieldControl(
      field,
      value,
      (nextValue) => {
        target.selector[field.name] = nextValue;
        clearDependentFields(target, kindSchema, field.name);
        updateAutoMetadata(target, kindSchema);
        renderEditor();
      },
      {
        choices: state.options,
        placeholder: "Select an option…",
        disabled: managerBusy,
      },
    );
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
            autoAliasTargets.delete(target);
            target.alias = value;
            syncManagerActions();
          },
          { disabled: managerBusy },
        ),
        fieldControl(
          { label: "Label", field_type: "text", required: true, max_length: 100 },
          target.label,
          (value) => {
            autoLabelTargets.delete(target);
            target.label = value;
            syncManagerActions();
          },
          { disabled: managerBusy },
        ),
      );
      const kindLabel = document.createElement("label");
      kindLabel.className = "editor-field";
      const kindCaption = document.createElement("span");
      kindCaption.textContent = "Target type";
      const kindSelect = document.createElement("select");
      if (!target.selector.kind) {
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Select target type…";
        placeholder.disabled = true;
        kindSelect.append(placeholder);
      }
      for (const kind of targetSchema.selector_kinds) {
        if (kind.kind === "recommended") {
          continue;
        }
        const option = document.createElement("option");
        option.value = kind.kind;
        option.textContent = kind.label;
        kindSelect.append(option);
      }
      kindSelect.value = target.selector.kind;
      kindSelect.disabled = managerBusy;
      kindSelect.addEventListener("change", () => {
        const kind = targetSchema.selector_kinds.find((item) => item.kind === kindSelect.value);
        target.selector = selectorDefaults(kind);
        discoveryState.delete(target);
        updateAutoMetadata(target, kind);
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
        if (field.field_type === "choice" && field.option_source === "provider") {
          selectorFields.append(providerFieldControl(target, selectedKind, field));
          continue;
        }
        selectorFields.append(
          fieldControl(
            field,
            target.selector[field.name],
            (value) => {
              target.selector[field.name] = value;
              clearDependentFields(target, selectedKind, field.name);
              updateAutoMetadata(target, selectedKind);
              if ((selectedKind.fields || []).some(
                (item) => (item.depends_on || []).includes(field.name),
              )) {
                renderEditor();
              } else {
                syncManagerActions();
              }
            },
            { disabled: managerBusy },
          ),
        );
      }
      card.append(selectorFields);
      editorList.append(card);
    });
    syncManagerActions();
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
      adoptCommittedCatalogue(cataloguePayload);
      managerProvider.textContent = editableCatalogue.provider;
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
    newDestinationDraft = {
      alias: "",
      label: "",
      selector: { kind: "" },
    };
    autoLabelTargets.add(newDestinationDraft);
    autoAliasTargets.add(newDestinationDraft);
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
        const value = target.selector[field.name];
        if (field.required && (value === "" || value == null)) {
          return `Destination ${target.alias} requires ${field.label}.`;
        }
        if (
          field.field_type === "choice" &&
          field.option_source !== "provider" &&
          value !== "" &&
          !(field.choices || []).includes(value)
        ) {
          return `Destination ${target.alias} has an invalid ${field.label} value.`;
        }
        if (field.field_type !== "choice" || field.option_source !== "provider") {
          continue;
        }
        if (!dependenciesHaveValues(target, field)) {
          return `Destination ${target.alias} requires dependencies for ${field.label}.`;
        }
        const state = discoveryState.get(target)?.get(field.name);
        if (!state || state.status === "loading") {
          return `Destination ${target.alias} is still loading ${field.label} options.`;
        }
        if (state.status === "error") {
          return `Destination ${target.alias} cannot load ${field.label} options.`;
        }
        if (
          value !== "" &&
          !state.options.some((option) => String(option.value) === String(value))
        ) {
          return `Destination ${target.alias} has a stale ${field.label} value.`;
        }
      }
    }
    return null;
  }

  function syncManagerActions() {
    if (!editableCatalogue) {
      return;
    }
    addTargetButton.disabled =
      managerBusy ||
      editableCatalogue.targets.length >= 100 ||
      newDestinationDraft !== null ||
      hasUnfinishedDestination();
    reloadTargetsButton.disabled = managerBusy;
    saveTargetsButton.disabled =
      managerBusy || !managerLoaded || validateEditor() !== null;
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
    try {
      const payload = await replaceCatalogueTargets(editableCatalogue.targets);
      adoptCommittedCatalogue(payload);
      await loadTargets();
      setManagerMessage("Catalogue saved.", "success");
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
    fields.lastRefreshed.textContent = new Date(payload.checked_at).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    });
    currentTarget = status?.target || null;
    if (
      !targetSelect.value &&
      currentTarget &&
      targetSelect.querySelector(`option[value="${currentTarget}"]`)
    ) {
      targetSelect.value = currentTarget;
    }
    syncControls();

    fields.dnsService.textContent = display(payload.dns?.service);
    fields.dnsState.textContent = payload.dns
      ? payload.dns.healthy ? "Healthy" : "Unavailable"
      : "Unknown";

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
    fields.lastRefreshed.textContent = new Date().toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    });
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

      populateTargetSelect(payload.targets || []);

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