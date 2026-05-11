/* ── Scalpy Common JS ── */

const fmt = n => { const v = Number(n); return isNaN(v) ? n : v.toLocaleString('ko-KR'); };
const pnlSign = n => n >= 0 ? '+' + fmt(n) : fmt(n);

function toast(msg, type) {
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}
