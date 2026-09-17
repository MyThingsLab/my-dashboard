/* Table sort and filter, shared by /repos and /goals.

   Progressive enhancement on purpose: the tables are server-rendered and
   complete without this file running, so a page that fails to load it is
   still readable rather than empty. */

(function () {
  function key(row, i) {
    var td = row.cells[i];
    if (!td) return '';
    var raw = td.dataset.sort !== undefined ? td.dataset.sort : td.textContent.trim();
    var n = parseFloat(raw);
    return isNaN(n) ? raw.toLowerCase() : n;
  }

  document.querySelectorAll('table[data-sortable]').forEach(function (table) {
    table.querySelectorAll('thead th').forEach(function (th, i) {
      th.addEventListener('click', function () {
        var dir = th.classList.contains('asc') ? -1 : 1;
        table.querySelectorAll('thead th').forEach(function (o) {
          o.classList.remove('asc', 'desc');
        });
        th.classList.add(dir === 1 ? 'asc' : 'desc');
        var body = table.tBodies[0];
        Array.prototype.slice.call(body.rows)
          .sort(function (a, b) {
            var x = key(a, i), y = key(b, i);
            return x < y ? -dir : x > y ? dir : 0;
          })
          .forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  document.querySelectorAll('[data-filter-for]').forEach(function (box) {
    var table = document.querySelector(box.dataset.filterFor);
    if (!table) return;
    var out = document.getElementById(box.dataset.filterCount || '');
    var apply = function () {
      var q = box.value.toLowerCase();
      var shown = 0;
      Array.prototype.slice.call(table.tBodies[0].rows).forEach(function (r) {
        var hit = !q || r.textContent.toLowerCase().indexOf(q) !== -1;
        r.hidden = !hit;
        if (hit) shown++;
      });
      if (out) out.textContent = shown + ' shown';
    };
    box.addEventListener('input', apply);
    apply();
  });

  window.openDrawer = function (title, agent, desc, context) {
    var t = document.getElementById('drawer-title');
    var a = document.getElementById('drawer-agent');
    var d = document.getElementById('drawer-desc');
    var c = document.getElementById('drawer-context');
    var backdrop = document.getElementById('drawer-backdrop');
    if (t && title) t.textContent = title;
    if (a && agent) a.textContent = 'Agent: ' + agent;
    if (d && desc) d.textContent = desc;
    if (c && context) c.textContent = context;
    if (backdrop) backdrop.classList.add('open');
  };

  window.closeDrawer = function () {
    var backdrop = document.getElementById('drawer-backdrop');
    if (backdrop) backdrop.classList.remove('open');
  };

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      window.closeDrawer();
    }
  });
})();

