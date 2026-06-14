// Di-nasty — KG view: lightweight live graph overlay for scouting/KG events.
window.DN = window.DN || {};

DN.kgview = (function () {
  const K = {};
  let root = null;
  let svg = null;
  let statusEl = null;
  let detailEl = null;
  let nodes = new Map();
  let edges = [];
  const colors = {
    match: '#3FA89F',
    team: '#E8A23D',
    scout: '#8E79C4',
    finding: '#D96E54',
    evidence_claim: '#4E7E2A',
    source: '#5E5440',
    player: '#B07E1C',
    default: '#2C2820',
  };

  function ensure() {
    if (root) return;
    root = document.createElement('div');
    root.id = 'kg-overlay';
    root.className = 'panel';
    root.innerHTML =
      '<div class="kg-head">' +
        '<div><div class="kg-k">Knowledge Graph</div><div class="kg-title" id="kg-title">KG stream</div></div>' +
        '<button class="kg-close" id="kg-close">×</button>' +
      '</div>' +
      '<div class="kg-status" id="kg-status">Waiting for graph events...</div>' +
      '<svg id="kg-svg" viewBox="0 0 720 360" preserveAspectRatio="xMidYMid meet"></svg>' +
      '<div class="kg-detail" id="kg-detail">Click a node for details.</div>';
    document.body.appendChild(root);
    svg = root.querySelector('#kg-svg');
    statusEl = root.querySelector('#kg-status');
    detailEl = root.querySelector('#kg-detail');
    root.querySelector('#kg-close').addEventListener('click', () => root.classList.remove('show'));
  }

  function labelFor(entity) {
    return entity.name || entity.entity_id || entity.id || 'node';
  }

  function typeFor(entity) {
    return entity.entity_type || entity.type || 'default';
  }

  function shortLabel(value) {
    const label = String(value || '');
    return label.length > 24 ? label.slice(0, 22) + '...' : label;
  }

  function addNode(entity) {
    if (!entity) return;
    const id = entity.entity_id || entity.id;
    if (!id) return;
    nodes.set(id, entity);
    render();
  }

  function addEdge(relationship) {
    if (!relationship) return;
    edges.push(relationship);
    render();
  }

  function positionedNodes() {
    const values = Array.from(nodes.values());
    const count = Math.max(values.length, 1);
    return values.map((node, index) => {
      const angle = index * 2.399963229728653;
      const radius = 18 + Math.sqrt(index / count) * 155;
      return {
        node,
        x: 360 + Math.cos(angle) * radius,
        y: 180 + Math.sin(angle) * radius,
      };
    });
  }

  function render() {
    if (!svg) return;
    const placed = positionedNodes();
    const byId = new Map(placed.map((item) => [item.node.entity_id || item.node.id, item]));
    const edgeMarkup = edges.slice(-220).map((edge) => {
      const a = byId.get(edge.source_id || edge.source);
      const b = byId.get(edge.target_id || edge.target);
      if (!a || !b) return '';
      return '<line class="kg-edge" x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '" />';
    }).join('');
    const nodeMarkup = placed.map((item) => {
      const node = item.node;
      const id = node.entity_id || node.id;
      const type = typeFor(node);
      const color = colors[type] || colors.default;
      return '<g class="kg-node" data-node="' + encodeURIComponent(id) + '" transform="translate(' + item.x + ' ' + item.y + ')">' +
        '<circle r="9" fill="' + color + '"></circle>' +
        '<text y="23">' + shortLabel(labelFor(node)) + '</text>' +
      '</g>';
    }).join('');
    svg.innerHTML = edgeMarkup + nodeMarkup;
    svg.querySelectorAll('.kg-node').forEach((el) => {
      el.addEventListener('click', () => {
        const id = decodeURIComponent(el.getAttribute('data-node'));
        const node = nodes.get(id);
        if (node) detailEl.textContent = typeFor(node) + ' · ' + labelFor(node) + ' · ' + id;
      });
    });
  }

  K.reset = function (title) {
    ensure();
    nodes = new Map();
    edges = [];
    root.querySelector('#kg-title').textContent = title || 'KG stream';
    statusEl.textContent = 'Waiting for graph events...';
    detailEl.textContent = 'Click a node for details.';
    svg.innerHTML = '';
    root.classList.add('show');
  };

  K.status = function (text) {
    ensure();
    statusEl.textContent = text;
    root.classList.add('show');
  };

  K.ingest = function (event) {
    ensure();
    if (!event || !event.event_type) return;
    if (event.event_type === 'kg_stage') {
      const entities = event.entity_count != null ? ' · ' + event.entity_count + ' entities' : '';
      const links = event.relationship_count != null ? ' · ' + event.relationship_count + ' links' : '';
      K.status(String(event.stage || 'kg_stage').replace(/_/g, ' ') + entities + links);
    } else if (event.event_type === 'kg_entity') {
      addNode(event.entity);
      K.status(nodes.size + ' entities streamed · ' + edges.length + ' links');
    } else if (event.event_type === 'kg_relationship') {
      addEdge(event.relationship);
      K.status(nodes.size + ' entities streamed · ' + edges.length + ' links');
    } else if (event.event_type === 'kg_manifest') {
      const manifest = event.manifest || {};
      K.status('Manifest ready · ' + (manifest.entity_count || nodes.size) + ' entities · ' + (manifest.relationship_count || edges.length) + ' links');
    } else if (event.event_type === 'scouting_audit') {
      K.status('Scouting audit ready · backlog ' + (event.backlog_count == null ? 'n/a' : event.backlog_count));
    }
  };

  K.showGraph = function (graph, title) {
    K.reset(title || 'World Cup KG');
    (graph.entities || []).forEach(addNode);
    (graph.relationships || []).forEach(addEdge);
    K.status((graph.entity_count || nodes.size) + ' KG entities · ' + (graph.relationship_count || edges.length) + ' links');
  };

  return K;
})();
