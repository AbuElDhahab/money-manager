// Theme switcher
document.getElementById("themeBtn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
  window.dispatchEvent(new Event("themechange"));
});

// Add / edit dialog: [data-new] opens empty, [data-edit] prefills from JSON
const modal = document.getElementById("modal");
if (modal) {
  const form = document.getElementById("modalForm");
  const title = document.getElementById("modalTitle");
  const open = (label, values = {}) => {
    form.reset();
    form.elements.id.value = values.id || "";
    for (const [k, v] of Object.entries(values)) {
      if (form.elements[k] && k !== "id") form.elements[k].value = v ?? "";
    }
    if (!values.id && form.elements.record_date) form.elements.record_date.value = new Date().toISOString().slice(0, 10);
    title.textContent = label;
    modal.showModal();
  };
  document.querySelectorAll("[data-new]").forEach(b => b.addEventListener("click", () => open("Add " + form.dataset.title.toLowerCase())));
  document.querySelectorAll("[data-edit]").forEach(b => b.addEventListener("click", () => open("Edit " + form.dataset.title.toLowerCase(), JSON.parse(b.dataset.edit))));
  modal.addEventListener("click", e => { if (e.target === modal) modal.close(); });
  modal.querySelector("[data-close]").addEventListener("click", () => modal.close());
}

// Confirm before delete
document.querySelectorAll("form[data-confirm]").forEach(f =>
  f.addEventListener("submit", e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));
