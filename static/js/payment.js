// ...new file...
document.addEventListener('DOMContentLoaded', function () {
  const openBtn = document.getElementById('support-btn');
  const modal = document.getElementById('micro-pay-modal');
  const form = document.getElementById('micro-pay-form');
  const processing = document.getElementById('micro-pay-processing');
  const errEl = document.getElementById('micro-pay-error');
  const successEl = document.getElementById('micro-pay-success');

  if (!openBtn || !modal || !form) return;

  function openModal() {
    errEl.style.display = 'none';
    successEl.style.display = 'none';
    processing.classList.remove('visible');
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeModal() {
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
    form.reset();
  }

  openBtn.addEventListener('click', openModal);
  modal.querySelectorAll('.modal-close').forEach(b => b.addEventListener('click', closeModal));

  // close on ESC
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal.classList.contains('show')) closeModal();
  });

  function showError(msg) {
    errEl.textContent = msg;
    errEl.style.display = 'block';
    successEl.style.display = 'none';
  }

  function showSuccess(msg) {
    successEl.textContent = msg;
    successEl.style.display = 'block';
    errEl.style.display = 'none';
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    // simple client-side validation (demo only)
    const data = new FormData(form);
    const card = (data.get('card') || '').replace(/\D/g, '');
    const exp = (data.get('exp') || '').trim();
    const cvc = (data.get('cvc') || '').trim();
    if (!/^\d{13,19}$/.test(card)) return showError('Please enter a valid card number (demo).');
    if (!/^\d{3,4}$/.test(cvc)) return showError('Please enter a valid CVC.');
    if (!/^\d{2}\/\d{2}$/.test(exp)) return showError('Expiry must be MM/YY.');

    // simulate processing
    processing.classList.add('visible');
    errEl.style.display = 'none';
    successEl.style.display = 'none';
    // disable inputs while "processing"
    Array.from(form.elements).forEach(el => el.disabled = true);

    setTimeout(function () {
      processing.classList.remove('visible');
      Array.from(form.elements).forEach(el => el.disabled = false);
      showSuccess('Payment simulated — thank you for supporting MachZero.');
      // auto close after brief delay
      setTimeout(closeModal, 1800);
    }, 1500);
  }, { passive: false });
});