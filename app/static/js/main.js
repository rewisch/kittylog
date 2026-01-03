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
});
