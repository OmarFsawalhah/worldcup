// Live countdown to each match. Elements with [data-countdown="<iso>"] are updated.
(function () {
  const labels = {
    en: { d: 'd', h: 'h', m: 'm', s: 's', live: 'LIVE', finished: 'FINISHED' },
    ar: { d: 'ي', h: 'س', m: 'د', s: 'ث', live: 'جارية', finished: 'انتهت' },
  };
  const lang = document.documentElement.lang === 'ar' ? 'ar' : 'en';
  const L = labels[lang];

  function pad(n) { return String(n).padStart(2, '0'); }

  function fmt(diff) {
    const totalSec = Math.floor(diff / 1000);
    const days = Math.floor(totalSec / 86400);
    const hours = Math.floor((totalSec % 86400) / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    const secs = totalSec % 60;
    if (days > 0) return `${days}${L.d} ${pad(hours)}${L.h} ${pad(mins)}${L.m}`;
    return `${pad(hours)}${L.h} ${pad(mins)}${L.m} ${pad(secs)}${L.s}`;
  }

  function tick() {
    const now = Date.now();
    document.querySelectorAll('[data-countdown]').forEach((el) => {
      const iso = el.getAttribute('data-countdown');
      const ts = Date.parse(iso);
      if (Number.isNaN(ts)) return;
      const diff = ts - now;
      if (diff <= 0) {
        // show local kickoff time once past
        const d = new Date(ts);
        el.textContent = d.toLocaleString();
      } else {
        el.textContent = fmt(diff);
      }
    });
  }

  tick();
  setInterval(tick, 1000);
})();
