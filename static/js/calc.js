// Calculator for the Amount field. evaluate() is a small safe parser (no eval): + - * / ( ) and decimals.
function evaluate(text) {
  if (/[\d.]\s+[\d.]/.test(text)) return NaN;  // "2 3" must not silently become 23
  const s = text.replace(/×/g, "*").replace(/÷/g, "/").replace(/−/g, "-").replace(/\s+/g, "");  // a comma is rejected: 1,500 is ambiguous
  if (!s) return null;
  let i = 0;
  const fail = () => { throw new Error("bad"); };
  function number() {
    const m = /^(\d+\.?\d*|\.\d+)/.exec(s.slice(i));
    if (!m) fail();
    i += m[0].length;
    return parseFloat(m[0]);
  }
  function factor() {
    if (s[i] === "-") { i++; return -factor(); }
    if (s[i] === "+") { i++; return factor(); }
    if (s[i] === "(") { i++; const v = expr(); if (s[i] !== ")") fail(); i++; return v; }
    return number();
  }
  function term() {
    let v = factor();
    while (s[i] === "*" || s[i] === "/") {
      const op = s[i++], r = factor();
      if (op === "/" && r === 0) fail();
      v = op === "*" ? v * r : v / r;
    }
    return v;
  }
  function expr() {
    let v = term();
    while (s[i] === "+" || s[i] === "-") { const op = s[i++], r = term(); v = op === "+" ? v + r : v - r; }
    return v;
  }
  try {
    const v = expr();
    return i === s.length && Number.isFinite(v) ? v : NaN;
  } catch (e) { return NaN; }
}

if (typeof module !== "undefined") module.exports = { evaluate };

if (typeof document !== "undefined") {
  const KEYS = [["C", "clear"], ["(", "("], [")", ")"], ["÷", "/"], ["7"], ["8"], ["9"], ["×", "*"],
                ["4"], ["5"], ["6"], ["−", "-"], ["1"], ["2"], ["3"], ["+", "+"],
                ["0"], ["."], ["⌫", "back"], ["=", "="]];
  const round2 = v => Math.round(v * 100) / 100;
  const coarse = matchMedia("(pointer: coarse)").matches;

  document.querySelectorAll(".amount").forEach(wrap => {
    const amount = wrap.querySelector('input[name="amount"]');
    const panel = wrap.querySelector(".calc");
    const toggle = wrap.querySelector(".calc-toggle");
    const expr = panel.querySelector(".calc-expr");
    const out = panel.querySelector(".calc-result");
    const keys = panel.querySelector(".calc-keys");
    if (coarse) expr.setAttribute("inputmode", "none");  // phones: use the on-screen keypad, no keyboard pop-up

    const show = () => {
      const v = evaluate(expr.value);
      out.classList.toggle("bad", Number.isNaN(v));
      out.textContent = v === null ? "Type or tap a calculation"
        : Number.isNaN(v) ? "Check the calculation" : "= " + round2(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
      return v;
    };
    const setOpen = open => {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) { expr.value = amount.value || ""; show(); if (!coarse) expr.focus(); }
    };
    const equals = () => { const v = evaluate(expr.value); if (typeof v === "number" && !Number.isNaN(v)) expr.value = String(round2(v)); show(); };

    KEYS.forEach(([label, val]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; b.dataset.k = val || label;
      b.className = "calc-key" + (/^[\d.]$/.test(label) ? "" : " op");
      keys.append(b);
    });
    keys.addEventListener("click", e => {
      const k = e.target.dataset && e.target.dataset.k;
      if (!k) return;
      if (k === "clear") expr.value = "";
      else if (k === "back") expr.value = expr.value.slice(0, -1);
      else if (k === "=") return equals();
      else expr.value += k;
      show();
    });
    expr.addEventListener("input", show);
    expr.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); equals(); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); toggle.focus(); }
    });
    toggle.addEventListener("click", () => setOpen(panel.hidden));
    panel.querySelector("[data-calc-close]").addEventListener("click", () => setOpen(false));
    panel.querySelector("[data-calc-use]").addEventListener("click", () => {
      const v = evaluate(expr.value);
      if (typeof v !== "number" || Number.isNaN(v) || round2(v) <= 0) {
        out.classList.add("bad"); out.textContent = "The result must be greater than 0"; return;
      }
      amount.value = round2(v).toFixed(2);
      amount.dispatchEvent(new Event("input", { bubbles: true }));
      setOpen(false); amount.focus();
    });
    const dialog = wrap.closest("dialog");
    if (dialog) dialog.addEventListener("close", () => setOpen(false));
  });
}
