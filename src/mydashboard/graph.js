/* The graph canvas.

   Layout is computed here rather than server-side, from the depth the server
   already assigned each node (graph._layers). The server owns the traversal;
   the client owns the arithmetic. That split is what makes filtering work:
   hide the closed two-thirds and the columns re-pack, where a server-rendered
   SVG would leave the gaps behind. It also puts depth on the x axis, which is
   bounded by the longest dependency chain, instead of node count, which is
   not -- the previous version grew to 9720px wide and squeezed every node to
   8px.

   Colours are read from the CSS custom properties so the canvas follows
   dashboard.css's light/dark switch instead of hardcoding a second palette. */

(function () {
  var COL = 250, ROW = 34, NW = 200, NH = 24, PAD = 46;

  var svg = document.getElementById('canvas');
  if (!svg) return;
  var wrap = document.getElementById('graph-wrap');
  var detail = document.getElementById('detail');
  var data = { nodes: [], edges: [], cycles: [] };
  var pos = {}, selected = null, colors = {};
  var view = { x: 0, y: 0, w: 1200, h: 700, set: false };

  var els = {
    closed: document.getElementById('f-closed'),
    workflow: document.getElementById('f-workflow'),
    repo: document.getElementById('f-repo'),
    goal: document.getElementById('f-goal'),
    search: document.getElementById('f-search')
  };
  var stats = document.getElementById('g-stats');

  function readColors() {
    var s = getComputedStyle(document.body);
    var v = function (n, f) { return (s.getPropertyValue(n) || f).trim(); };
    colors = {
      blocked: v('--crit', '#CF222E'),
      ready: v('--good', '#1A7F37'),
      closed: v('--muted', '#5C6663'),
      workflow: v('--accent', '#0F766E'),
      ink: v('--ink', '#1C2321')
    };
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function trim(s, n) {
    s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  function visible() {
    var q = (els.search.value || '').toLowerCase();
    return data.nodes.filter(function (n) {
      if (!els.closed.checked && n.state === 'closed') return false;
      if (!els.workflow.checked && n.kind === 'workflow') return false;
      if (els.repo.value && n.repo !== els.repo.value) return false;
      if (els.goal.value && (n.goal || '') !== els.goal.value) return false;
      if (q && (n.label + ' ' + n.id).toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
  }

  function layout(nodes) {
    var byLayer = {};
    nodes.forEach(function (n) { (byLayer[n.layer] = byLayer[n.layer] || []).push(n); });
    var layers = Object.keys(byLayer).map(Number).sort(function (a, b) { return a - b; });
    pos = {};
    var tallest = 1;
    layers.forEach(function (l, col) {
      byLayer[l].forEach(function (n, i) {
        pos[n.id] = { x: PAD + col * COL, y: PAD + i * ROW };
      });
      tallest = Math.max(tallest, byLayer[l].length);
    });
    return {
      width: PAD * 2 + Math.max(layers.length, 1) * COL,
      height: PAD * 2 + tallest * ROW,
      layers: layers, byLayer: byLayer
    };
  }

  function draw() {
    var nodes = visible();
    var keep = {};
    nodes.forEach(function (n) { keep[n.id] = n; });
    var edges = data.edges.filter(function (e) { return keep[e.src] && keep[e.dst]; });
    var box = layout(nodes);

    stats.textContent = nodes.length + ' of ' + data.nodes.length + ' nodes · ' +
      edges.length + ' edges · ' + box.layers.length + ' depths' +
      (data.cycles.length ? ' · ' + data.cycles.length + ' cycle(s)' : '');

    if (!nodes.length) {
      svg.innerHTML = '';
      return;
    }

    var p = ['<defs><marker id="ar" markerWidth="7" markerHeight="7" refX="6.5" refY="2.5"' +
      ' orient="auto"><path d="M0,0 L7,2.5 L0,5 z" fill="' + colors.closed + '"/></marker></defs>'];

    box.layers.forEach(function (l, col) {
      p.push('<text class="depth" x="' + (PAD + col * COL) + '" y="' + (PAD - 14) +
        '">depth ' + l + ' · ' + box.byLayer[l].length + '</text>');
    });

    edges.forEach(function (e) {
      var a = pos[e.src], b = pos[e.dst];
      // src waits on dst, so the curve leaves src's left edge and arrives at
      // dst's right edge: arrows point back down the chain, at the thing that
      // has to happen first.
      var x1 = a.x, y1 = a.y + NH / 2, x2 = b.x + NW, y2 = b.y + NH / 2;
      var mx = (x1 + x2) / 2;
      p.push('<path class="edge" data-src="' + esc(e.src) + '" data-dst="' + esc(e.dst) +
        '" d="M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 + ' ' +
        x2 + ',' + y2 + '" marker-end="url(#ar)"/>');
    });

    nodes.forEach(function (n) {
      var xy = pos[n.id];
      var c = colors[n.state] || colors.closed;
      p.push('<g class="node" data-id="' + esc(n.id) + '" transform="translate(' +
        xy.x + ',' + xy.y + ')">' +
        '<rect class="body" width="' + NW + '" height="' + NH + '" rx="4" fill="' + c +
        '1f" stroke="' + c + '" stroke-dasharray="' + (n.cyclic ? '3 2' : 'none') + '"/>' +
        (n.goal ? '<rect width="2.5" height="' + NH + '" fill="' + colors.workflow + '"/>' : '') +
        '<text x="8" y="16">' + esc(trim(n.id, 15)) + '</text>' +
        '<text x="' + (NW - 8) + '" y="16" text-anchor="end" opacity=".65">' +
        esc(trim(n.label, 20)) + '</text></g>');
    });

    svg.innerHTML = p.join('');
    if (!view.set) {
      view = { x: 0, y: 0, w: box.width, h: box.height, set: true };
    }
    applyView();
    svg.querySelectorAll('.node').forEach(function (g) {
      g.addEventListener('click', function (ev) { ev.stopPropagation(); select(g.dataset.id); });
    });
    if (selected && keep[selected]) highlight(selected);
    else if (selected) { selected = null; closeDetail(); }
  }

  function applyView() {
    svg.setAttribute('viewBox', view.x + ' ' + view.y + ' ' + view.w + ' ' + view.h);
  }

  function highlight(id) {
    var near = {};
    near[id] = 1;
    data.edges.forEach(function (e) {
      if (e.src === id) near[e.dst] = 1;
      if (e.dst === id) near[e.src] = 1;
    });
    svg.querySelectorAll('.node').forEach(function (g) {
      g.classList.toggle('dim', !near[g.dataset.id]);
    });
    svg.querySelectorAll('.edge').forEach(function (path) {
      var hot = path.dataset.src === id || path.dataset.dst === id;
      path.classList.toggle('hot', hot);
      path.classList.toggle('dim', !hot);
    });
  }

  function clearHighlight() {
    svg.querySelectorAll('.dim').forEach(function (e) { e.classList.remove('dim'); });
    svg.querySelectorAll('.hot').forEach(function (e) { e.classList.remove('hot'); });
  }

  function closeDetail() { wrap.classList.remove('open'); }

  function byId(id) {
    for (var i = 0; i < data.nodes.length; i++) {
      if (data.nodes[i].id === id) return data.nodes[i];
    }
    return null;
  }

  function edgeList(edges, otherEnd, withClause) {
    if (!edges.length) return '<p class="empty">nothing</p>';
    return '<ul>' + edges.map(function (e) {
      var id = otherEnd(e), t = byId(id);
      return '<li><a href="#" data-goto="' + esc(id) + '">' + esc(id) + '</a>' +
        (t ? ' — ' + esc(trim(t.label, 38)) : ' <em>(not fetched)</em>') +
        (withClause ? '<span class="clause">' + esc(e.kind) + ': ' + esc(e.text) + '</span>' : '') +
        '</li>';
    }).join('') + '</ul>';
  }

  function select(id) {
    var n = byId(id);
    if (!n) return;
    selected = id;
    var waits = data.edges.filter(function (e) { return e.src === id; });
    var holds = data.edges.filter(function (e) { return e.dst === id; });
    var dash = '—';
    var rows = [
      ['id', esc(n.id)],
      ['repo', esc(n.repo || dash)],
      ['state', esc(n.state)],
      ['depth', n.layer],
      ['prio', esc(n.prio || dash)],
      ['lane', esc(n.lane || dash)],
      ['goal', n.goal ? '<a href="/goals">' + esc(n.goal) + '</a>' : dash]
    ];
    detail.innerHTML = '<button class="btn close" id="detail-close">close</button>' +
      '<h3>' + esc(n.label) + '</h3>' +
      (n.url ? '<p><a href="' + esc(n.url) + '" target="_blank" rel="noopener">' +
        'open on GitHub ↗</a></p>' : '') +
      (n.cyclic ? '<p class="callout">in a dependency cycle — flagged, never ' +
        'auto-resolved</p>' : '') +
      '<dl>' + rows.map(function (r) {
        return '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>';
      }).join('') + '</dl>' +
      '<h4>Waits on (' + waits.length + ')</h4>' +
      edgeList(waits, function (e) { return e.dst; }, true) +
      '<h4>Blocks (' + holds.length + ')</h4>' +
      edgeList(holds, function (e) { return e.src; }, false);

    wrap.classList.add('open');
    document.getElementById('detail-close').addEventListener('click', function () {
      selected = null; clearHighlight(); closeDetail();
    });
    detail.querySelectorAll('[data-goto]').forEach(function (a) {
      a.addEventListener('click', function (ev) { ev.preventDefault(); select(a.dataset.goto); });
    });
    highlight(id);
  }

  // ---- pan / zoom ----
  var drag = null;
  svg.addEventListener('mousedown', function (e) {
    drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
    svg.classList.add('dragging');
  });
  window.addEventListener('mouseup', function () {
    svg.classList.remove('dragging');
    setTimeout(function () { drag = null; }, 0);
  });
  window.addEventListener('mousemove', function (e) {
    if (!drag) return;
    var k = view.w / svg.clientWidth;
    drag.moved = true;
    view.x = drag.vx - (e.clientX - drag.x) * k;
    view.y = drag.vy - (e.clientY - drag.y) * k;
    applyView();
  });
  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    var k = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    var r = svg.getBoundingClientRect();
    view.x += view.w * ((e.clientX - r.left) / r.width) * (1 - k);
    view.y += view.h * ((e.clientY - r.top) / r.height) * (1 - k);
    view.w *= k; view.h *= k;
    applyView();
  }, { passive: false });
  svg.addEventListener('click', function () {
    if (drag && drag.moved) return;  // a pan is not a deselect
    selected = null; clearHighlight(); closeDetail();
  });

  document.getElementById('g-reset').addEventListener('click', function () {
    view.set = false;
    draw();
  });
  Object.keys(els).forEach(function (k) {
    els[k].addEventListener(els[k].type === 'search' ? 'input' : 'change', function () { draw(); });
  });

  readColors();
  fetch('/api/graph').then(function (r) { return r.json(); }).then(function (d) {
    data = d;
    var repos = {}, goals = {};
    d.nodes.forEach(function (n) {
      if (n.repo) repos[n.repo] = 1;
      if (n.goal) goals[n.goal] = 1;
    });
    Object.keys(repos).sort().forEach(function (r) {
      els.repo.insertAdjacentHTML('beforeend', '<option>' + esc(r) + '</option>');
    });
    Object.keys(goals).sort().forEach(function (g) {
      els.goal.insertAdjacentHTML('beforeend', '<option>' + esc(g) + '</option>');
    });
    if (!d.nodes.length) {
      stats.textContent = 'still building the first snapshot — reload in a moment';
      return;
    }
    draw();
  }).catch(function (err) {
    stats.textContent = 'could not load the graph: ' + err;
  });
})();
