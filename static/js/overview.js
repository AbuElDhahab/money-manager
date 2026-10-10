const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const palette = () => [css("--accent"), "#e0a43a", "#7a6bd6", "#d9667a", "#3f9bd8", "#8fb55a", "#c27e4a"];
let charts = [];

function draw() {
  charts.forEach(c => c.destroy());
  charts = [];
  const D = window.DATA, ink = css("--muted"), grid = css("--line");
  Chart.defaults.color = ink;
  Chart.defaults.font.family = "Figtree, system-ui, sans-serif";
  const scales = { x: { grid: { display: false } }, y: { grid: { color: grid }, beginAtZero: true } };

  charts.push(new Chart(document.getElementById("monthly"), {
    type: "bar",
    data: { labels: D.months, datasets: [
      { label: "Income", data: D.income, backgroundColor: css("--pos"), borderRadius: 4 },
      { label: "Expenses", data: D.expenses, backgroundColor: css("--neg"), borderRadius: 4 }] },
    options: { responsive: true, maintainAspectRatio: false, scales },
  }));

  const cats = document.getElementById("cats");
  if (cats) charts.push(new Chart(cats, {
    type: "doughnut",
    data: { labels: D.cats, datasets: [{ data: D.catTotals, backgroundColor: palette(), borderColor: css("--surface") }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right" } } },
  }));
}
draw();
window.addEventListener("themechange", draw);
