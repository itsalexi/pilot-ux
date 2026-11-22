// Minimal stand-in for support.js: expands {{holes}}, <sc-for>, <sc-if>, moves <helmet> into head.
(function () {
  class DCLogic { constructor() { this.state = {}; } setState(s) { Object.assign(this.state, s); } }
  window.DCLogic = DCLogic;
  const HOLE = /\{\{\s*([\w.$]+)\s*\}\}/g;
  function lookup(path, scopes) {
    if (path === 'true') return true;
    if (path === 'false') return false;
    const parts = path.split('.');
    for (const s of scopes) {
      if (s && Object.prototype.hasOwnProperty.call(s, parts[0])) {
        let v = s;
        for (const p of parts) v = v == null ? undefined : v[p];
        return v;
      }
    }
    return undefined;
  }
  function holeOf(str) { const m = /^\s*\{\{\s*([\w.$]+)\s*\}\}\s*$/.exec(str || ''); return m ? m[1] : null; }
  function sub(str, scopes) { return str.replace(HOLE, (_, p) => { const v = lookup(p, scopes); return v == null ? '' : String(v); }); }
  function processChildren(el, scopes) { Array.from(el.childNodes).forEach((n) => processNode(n, scopes)); }
  function unwrap(el) { const parent = el.parentNode; while (el.firstChild) parent.insertBefore(el.firstChild, el); parent.removeChild(el); }
  function processNode(node, scopes) {
    if (node.nodeType === 3) { if (node.nodeValue.indexOf('{{') !== -1) node.nodeValue = sub(node.nodeValue, scopes); return; }
    if (node.nodeType !== 1) return;
    const tag = node.tagName.toLowerCase();
    if (tag === 'template') { processChildren(node.content, scopes); return; }
    if (tag === 'sc-for') {
      const list = lookup(holeOf(node.getAttribute('list')), scopes) || [];
      const as = node.getAttribute('as') || 'item';
      const frag = document.createDocumentFragment();
      list.forEach((item, idx) => {
        const scope = { [as]: item, index: idx };
        Array.from(node.childNodes).forEach((c) => { const k = c.cloneNode(true); frag.appendChild(k); processNode(k, [scope].concat(scopes)); });
      });
      node.parentNode.replaceChild(frag, node);
      return;
    }
    if (tag === 'sc-if') {
      const v = lookup(holeOf(node.getAttribute('value')), scopes);
      if (v) { processChildren(node, scopes); unwrap(node); } else node.parentNode.removeChild(node);
      return;
    }
    Array.from(node.attributes).forEach((a) => {
      if (a.name.indexOf('hint-') === 0) { node.removeAttribute(a.name); return; }
      if (a.value.indexOf('{{') === -1) return;
      if (/^on/i.test(a.name)) { node.removeAttribute(a.name); return; }
      node.setAttribute(a.name, sub(a.value, scopes));
    });
    processChildren(node, scopes);
  }
  document.addEventListener('DOMContentLoaded', () => {
    let state = {};
    try { const h = decodeURIComponent(location.hash.slice(1)); if (h) state = JSON.parse(h); } catch (e) {}
    const sc = document.querySelector('script[data-dc-script]');
    let vals = {};
    if (sc) {
      const C = new Function('DCLogic', sc.textContent + '\nreturn Component;')(DCLogic);
      const c = new C(); c.state = state; vals = c.renderVals() || {};
    }
    const x = document.querySelector('x-dc');
    const helmet = x.querySelector('helmet');
    if (helmet) { Array.from(helmet.childNodes).forEach((n) => document.head.appendChild(n)); helmet.remove(); }
    processChildren(x, [vals]);
    unwrap(x);
    document.documentElement.setAttribute('data-dc-ready', '1');
  });
})();
