/* ── Scalpy Common JS ── */

const fmt = n => { const v = Number(n); return isNaN(v) ? n : v.toLocaleString('ko-KR'); };
const pnlSign = n => n >= 0 ? '+' + fmt(n) : fmt(n);

const _toasts = [];
function _repositionToasts() {
  let y = 28;
  for (const t of _toasts) {
    t.style.bottom = y + 'px';
    y += t.offsetHeight + 8;
  }
}
function toast(msg, type) {
  const el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = msg;
  document.body.appendChild(el);
  _toasts.push(el);
  requestAnimationFrame(() => _repositionToasts());
  setTimeout(() => {
    el.classList.add('toast-out');
    setTimeout(() => {
      el.remove();
      const idx = _toasts.indexOf(el);
      if (idx !== -1) _toasts.splice(idx, 1);
      _repositionToasts();
    }, 300);
  }, 2700);
}
