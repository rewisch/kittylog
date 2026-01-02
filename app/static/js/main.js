document.addEventListener("DOMContentLoaded", () => {
  document.body.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-confirm]");
    if (!button) return;
    const message = button.getAttribute("data-confirm") || "Are you sure?";
    if (!window.confirm(message)) {
      event.preventDefault();
    }
  });
});
