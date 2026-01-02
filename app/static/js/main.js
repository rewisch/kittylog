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
});
