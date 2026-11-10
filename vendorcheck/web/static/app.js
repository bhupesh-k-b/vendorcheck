// Document viewer (side panel) and email composer. Plain Alpine components; no build step.
function docViewer() {
  return {
    open: null,
    map() { const el = document.getElementById('docmap'); return el ? JSON.parse(el.textContent) : []; },
    show(sha, page) { this.open = { sha, page }; },
    file() { return this.map().find(f => f.sha === (this.open || {}).sha); },
    info() { const f = this.file(); return f ? f.pages.find(p => p.page === this.open.page) : null; },
    step(d) { const f = this.file(); if (!f) return; const n = this.open.page + d; if (n >= 1 && n <= f.pages.length) this.open.page = n; },
    pretty(t) { return (t || '').replace(/_/g, ' '); },
  };
}

function emailComposer() {
  return {
    to: '', subject: '', body: '', copied: false,
    init() {
      const d = JSON.parse(document.getElementById('email-data').textContent);
      this.to = d.to; this.subject = d.subject;
      this.body = d.body.replace('{LINK}', location.origin + '/v/' + d.token);
    },
    get mailto() { return 'mailto:' + encodeURIComponent(this.to) + '?subject=' + encodeURIComponent(this.subject) + '&body=' + encodeURIComponent(this.body); },
    copy() { navigator.clipboard.writeText('To: ' + this.to + '\nSubject: ' + this.subject + '\n\n' + this.body).then(() => { this.copied = true; setTimeout(() => this.copied = false, 2000); }); },
  };
}
