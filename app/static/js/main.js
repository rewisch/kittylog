document.addEventListener("DOMContentLoaded", () => {
  document.body.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-confirm]");
    if (!button) return;
    const message = button.getAttribute("data-confirm") || "Are you sure?";
    if (!window.confirm(message)) {
      event.preventDefault();
    }
  });

  // Provide translated required messages for select fields
  document.querySelectorAll("select[data-required-label]").forEach((select) => {
    const label = select.getAttribute("data-required-label");
    if (!label) return;
    const applyMessage = (el) => {
      if (!el.value) {
        el.setCustomValidity(label);
      } else {
        el.setCustomValidity("");
      }
    };
    select.addEventListener("invalid", (e) => applyMessage(e.target));
    select.addEventListener("change", (e) => applyMessage(e.target));
    select.addEventListener("input", (e) => applyMessage(e.target));
  });

  // Ensure forms apply the custom select validity before submission
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const selects = form.querySelectorAll("select[data-required-label]");
      selects.forEach((sel) => {
        const label = sel.getAttribute("data-required-label");
        if (!sel.value && label) {
          sel.setCustomValidity(label);
        } else {
          sel.setCustomValidity("");
        }
      });
      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
      }
    });
  });

  // Toggle cat edit panels
  document.body.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-cat-toggle-target]");
    if (!toggle) return;
    const targetId = toggle.getAttribute("data-cat-toggle-target");
    if (!targetId) return;
    const panel = document.getElementById(targetId);
    if (!panel) return;
    panel.classList.toggle("hidden");
    const openText = toggle.getAttribute("data-cat-toggle-open") || toggle.textContent;
    const closeText = toggle.getAttribute("data-cat-toggle-close") || toggle.textContent;
    const isOpen = !panel.classList.contains("hidden");
    toggle.textContent = isOpen ? closeText : openText;
  });

  // Toggle history timestamp editors
  document.body.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-time-toggle-target]");
    if (!toggle) return;
    const targetId = toggle.getAttribute("data-time-toggle-target");
    if (!targetId) return;
    const panel = document.getElementById(targetId);
    if (!panel) return;
    panel.classList.toggle("hidden");
    const openText = toggle.getAttribute("data-time-toggle-open") || toggle.textContent;
    const closeText = toggle.getAttribute("data-time-toggle-close") || toggle.textContent;
    const isOpen = !panel.classList.contains("hidden");
    toggle.textContent = isOpen ? closeText : openText;
  });

  // Normalize date + 24h time inputs into ISO-like timestamp before submit
  document.querySelectorAll("[data-datetime-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const dateField = form.querySelector("[data-date-field]");
      const timeField = form.querySelector("[data-time-field]");
      const target = form.querySelector("input[name='timestamp']");
      if (!dateField || !timeField || !target) return;
      const dateVal = dateField.value?.trim();
      const timeVal = timeField.value?.trim();
      if (!dateVal || !timeVal) return;
      const timePattern = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
      if (!timePattern.test(timeVal)) {
        event.preventDefault();
        timeField.setCustomValidity(timeField.getAttribute("placeholder") || "Use HH:MM (24h)");
        timeField.reportValidity();
        return;
      }
      timeField.setCustomValidity("");
      target.value = `${dateVal}T${timeVal}`;
    });
  });

  // Toggle history filters on small screens
  document.body.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-filter-toggle-target]");
    if (!toggle) return;
    const targetId = toggle.getAttribute("data-filter-toggle-target");
    if (!targetId) return;
    const panel = document.getElementById(targetId);
    if (!panel) return;
    panel.classList.toggle("hidden");
    const isOpen = !panel.classList.contains("hidden");
    toggle.setAttribute("aria-expanded", String(isOpen));
  });

  // Toggle mobile nav overflow
  document.body.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-nav-toggle-target]");
    if (!toggle) return;
    const targetId = toggle.getAttribute("data-nav-toggle-target");
    if (!targetId) return;
    const panel = document.getElementById(targetId);
    if (!panel) return;
    panel.classList.toggle("hidden");
  });

  // Toggle tooltip visibility on touch/click
  document.body.addEventListener("click", (event) => {
    const bar = event.target.closest(".tooltip-bar");
    if (!bar) {
      document.querySelectorAll(".tooltip-bar.tooltip-open").forEach((open) => {
        open.classList.remove("tooltip-open");
      });
      return;
    }
    if (bar.classList.contains("tooltip-open")) {
      bar.classList.remove("tooltip-open");
      return;
    }
    document.querySelectorAll(".tooltip-bar.tooltip-open").forEach((open) => {
      open.classList.remove("tooltip-open");
    });
    bar.classList.add("tooltip-open");
  });

});
