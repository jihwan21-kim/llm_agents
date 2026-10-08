(() => {
  'use strict';
  const quotaTarget = 'https://v0-renato.vercel.app/';
  let session = sessionStorage.getItem('mock-session');
  if (!session) {
    session = crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
    sessionStorage.setItem('mock-session', session);
  }
  let stage = 'registration';
  let busy = false;
  async function record(type, detail = {}) {
    const response = await fetch('/__mock/events', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session, time: new Date().toISOString(), stage, type, ...detail, external_sent: false})
    });
    if (!response.ok) throw new Error('Local recording failed');
  }
  function showError(message) {
    const el = document.querySelector('#mock-error');
    if (el) { el.hidden = false; el.textContent = message; }
  }
  function digits(value) { return value.replace(/\D/g, ''); }
  document.addEventListener('input', event => {
    const el = event.target;
    if (!(el instanceof HTMLInputElement)) return;
    el.setCustomValidity('');
    if (el.name === 'cpf') {
      const n = digits(el.value).slice(0, 11);
      el.value = n.replace(/^(\d{3})(\d)/, '$1.$2').replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3').replace(/(\d{3})\.(\d{3})\.(\d{3})(\d)/, '$1.$2.$3-$4');
    }
    if (el.name === 'phone') {
      const n = digits(el.value).slice(0, 11);
      el.value = n.length <= 2 ? n : '(' + n.slice(0, 2) + ') ' + n.slice(2, n.length > 10 ? 7 : 6) + (n.length > 6 ? '-' + n.slice(n.length > 10 ? 7 : 6) : '');
    }
  });
  document.addEventListener('submit', async event => {
    event.preventDefault();
    if (stage !== 'registration' || busy) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const name = form.elements.namedItem('full_name');
    const cpf = form.elements.namedItem('cpf');
    const phone = form.elements.namedItem('phone');
    name.setCustomValidity(name.value.trim() ? '' : 'Digite seu nome completo.');
    cpf.setCustomValidity(digits(cpf.value).length === 11 ? '' : 'Digite 11 números para o CPF.');
    phone.setCustomValidity([10, 11].includes(digits(phone.value).length) ? '' : 'Digite seu telefone com DDD.');
    if (!form.reportValidity()) return;
    if (form.elements.namedItem('website').value) {
      showError('Não preencha o campo oculto.');
      return;
    }
    busy = true;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      await record('submit_click');
      await record('simulated_request', {
        method: 'POST', target: 'mock://registration-original-destination-unverified',
        destination_verified: false,
        payload: {full_name: name.value.trim(), cpf: cpf.value, phone: phone.value,
                  consent: form.elements.namedItem('consent').checked},
        fidelity: 'Local replay of visible form fields. Saved original scripts are empty; original endpoint, method, payload names, validation, and server receipt are unverified.'
      });
      const firstName = name.value.trim().split(/\s+/)[0];
      const content = document.querySelector('#mock-confirmation').content.cloneNode(true);
      content.querySelector('.successText h2').textContent = 'Parabéns, ' + firstName + '!';
      document.querySelectorAll('style[data-registration-style]').forEach(el => el.remove());
      document.head.append(document.querySelector('#mock-confirmation-styles').content.cloneNode(true));
      document.querySelector('#mock-stage').replaceChildren(content);
      stage = 'confirmation';
      document.querySelector('#resultado').scrollIntoView({behavior: 'auto', block: 'start'});
      await record('page_loaded', {fidelity: 'Second saved snapshot; same URL; locally simulated confirmation, not original server acceptance.'});
    } catch {
      showError('Falha no registro local. A participação não foi enviada. Tente novamente.');
    } finally {
      busy = false;
      button.disabled = false;
    }
  });
  document.addEventListener('click', async event => {
    const link = event.target.closest('a');
    if (!link) return;
    event.preventDefault();
    if (!link.hasAttribute('data-mock-quota') || busy) return;
    busy = true;
    const status = document.querySelector('#mock-quota-status');
    try {
      await record('blocked_navigation', {target: quotaTarget, payload: {},
        fidelity: 'External link observed in the saved confirmation page. Navigation blocked locally; destination page was not supplied.'});
      status.textContent = 'Clique registrado localmente. Nenhum site externo foi aberto.';
    } catch {
      status.textContent = 'Falha no registro local. Nenhum site externo foi aberto.';
    } finally {status.hidden = false; busy = false;}
  });
  record('page_loaded', {fidelity: 'First saved snapshot; original scripts removed; replacement form handler.'})
    .catch(() => showError('Falha na conexão com o registro local.'));
})();
