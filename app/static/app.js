(() => {
  const toast = document.getElementById('toast');
  let toastTimer;
  function notify(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
  }
  const dirtyEditors = new Set();
  document.querySelectorAll('[data-editor]').forEach(form => {
    form.addEventListener('input', () => {
      dirtyEditors.add(form);
      const count = form.querySelector('[data-char-count]');
      if (count) count.textContent = form.elements.draft_text.value.length;
    });
  });
  window.addEventListener('beforeunload', event => {
    if (dirtyEditors.size) { event.preventDefault(); event.returnValue = ''; }
  });
  const menu = document.querySelector('.mobile-menu');
  menu?.addEventListener('click', () => {
    const open = document.getElementById('sidebar').classList.toggle('open');
    menu.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      document.getElementById('sidebar').classList.remove('open');
      menu?.setAttribute('aria-expanded', 'false');
    }
  });
  document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => {
    document.getElementById(button.dataset.open).showModal();
  }));
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  }));
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    const field = document.getElementById(button.dataset.copy);
    try { await navigator.clipboard.writeText(field.value); notify('Message copied. Ready to paste.'); }
    catch { field.focus(); field.select(); notify('Select and copy this message with Ctrl+C.'); }
  }));
  const search = document.getElementById('contact-search');
  let contactFilter = 'all';
  function filterContacts() {
    const query = search?.value.trim().toLowerCase() || '';
    let visible = 0;
    document.querySelectorAll('[data-contact]').forEach(row => {
      const match = row.dataset.search.toLowerCase().includes(query) && (contactFilter === 'all' || row.dataset[contactFilter] === 'yes');
      row.hidden = !match;
      if (match) visible++;
    });
    const count = document.getElementById('contact-count');
    if (count) count.textContent = `Showing ${visible} contact${visible === 1 ? '' : 's'}`;
    const empty = document.getElementById('no-results');
    if (empty) empty.hidden = visible > 0;
  }
  search?.addEventListener('input', filterContacts);
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    contactFilter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(chip => {
      const selected = chip === button;
      chip.classList.toggle('selected', selected);
      chip.setAttribute('aria-pressed', String(selected));
    });
    filterContacts();
  }));
  document.getElementById('clear-filters')?.addEventListener('click', () => {
    search.value = '';
    document.querySelector('[data-filter="all"]').click();
    search.focus();
  });
  document.getElementById('cv_file')?.addEventListener('change', event => {
    document.getElementById('upload-label').textContent = event.target.files[0]?.name || 'Choose a CV to upload';
  });
  function updateSectionTabs() {
    const activeHash = location.hash || '#drafts';
    document.querySelectorAll('.section-tabs a').forEach(link => {
      link.classList.toggle('selected', link.hash === activeHash);
      if (link.hash === activeHash) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }
  window.addEventListener('hashchange', updateSectionTabs);
  updateSectionTabs();
  const confirmDialog = document.getElementById('send-confirm');
  let pendingSend = null;
  document.getElementById('confirm-send').addEventListener('click', () => {
    const pending = pendingSend;
    confirmDialog.close();
    if (pending) submitForm(pending.form, pending.button);
  });
  confirmDialog.addEventListener('close', () => { pendingSend = null; });
  async function submitForm(form, button) {
    if (form.classList.contains('is-loading')) return;
    const action = button?.getAttribute('formaction') || form.action;
    const data = new FormData(form);
    form.querySelector('.form-error')?.remove();
    const buttons = [...form.querySelectorAll('button')];
    const original = button?.innerHTML;
    const label = button?.dataset.loading || form.dataset.loading || 'Updating…';
    form.classList.add('is-loading');
    form.setAttribute('aria-busy', 'true');
    buttons.forEach(item => { item.disabled = true; });
    if (button) button.textContent = label;
    try {
      const response = await fetch(action, { method: 'POST', body: data });
      if (!response.ok) {
        let detail = 'Something went wrong. Please try again.';
        try {
          const body = await response.json();
          if (typeof body.detail === 'string') detail = body.detail;
          else if (Array.isArray(body.detail)) detail = 'Please check that all required fields are filled in correctly.';
        } catch {}
        throw new Error(detail);
      }
      if (new URL(action, location.href).pathname.endsWith('/edit')) {
        dirtyEditors.delete(form);
        notify('Draft saved. Your changes are ready.');
      } else {
        dirtyEditors.delete(form);
        location.assign(response.redirected ? response.url : location.href);
      }
    } catch (error) {
      const alert = document.createElement('div');
      alert.className = 'form-error';
      alert.setAttribute('role', 'alert');
      alert.setAttribute('tabindex', '-1');
      alert.textContent = error instanceof TypeError ? 'Connection interrupted. Check the outreach queue before retrying a send.' : error.message;
      form.append(alert);
      alert.focus();
    } finally {
      form.classList.remove('is-loading');
      form.removeAttribute('aria-busy');
      buttons.forEach(item => { item.disabled = false; });
      if (button) button.innerHTML = original;
    }
  }
  document.querySelectorAll('form[data-async]').forEach(form => form.addEventListener('submit', event => {
    event.preventDefault();
    const button = event.submitter;
    if (button?.hasAttribute('data-send')) {
      pendingSend = { form, button };
      document.getElementById('confirm-recipient').textContent = button.dataset.send;
      confirmDialog.showModal();
    } else submitForm(form, button);
  }));
  if (new URLSearchParams(location.search).get('saved') === '1') notify('Draft saved. Your changes are ready.');
})();
