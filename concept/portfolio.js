(() => {
  const dialog = document.querySelector('.project-lightbox');
  if (!dialog) return;
  const items = [...document.querySelectorAll('[data-gallery]')];
  let active = 0, opener, startX = null;
  function show(index) {
    active = (index + items.length) % items.length;
    const item = items[active], image = item.querySelector('img');
    dialog.querySelector('img').src = item.dataset.full;
    dialog.querySelector('img').alt = image.alt;
    dialog.querySelector('.lightbox-caption').textContent =
      (active + 1) + ' / ' + items.length + ' · ' + item.parentElement.querySelector('figcaption').textContent.replace(/^\d+/, '').trim();
  }
  items.forEach((item, index) => item.addEventListener('click', () => {
    opener = item; show(index); dialog.showModal();
  }));
  dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
  dialog.querySelector('[data-prev]').addEventListener('click', () => show(active - 1));
  dialog.querySelector('[data-next]').addEventListener('click', () => show(active + 1));
  dialog.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); show(active + (event.key === 'ArrowRight' ? 1 : -1));
    }
  });
  dialog.addEventListener('close', () => opener?.focus({preventScroll:true}));
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  const image = dialog.querySelector('img');
  image.addEventListener('touchstart', event => {
    startX = event.touches.length === 1 ? event.touches[0].clientX : null;
  }, {passive:true});
  image.addEventListener('touchend', event => {
    if (startX !== null) {
      const delta = event.changedTouches[0].clientX - startX;
      if (Math.abs(delta) > 60) show(active + (delta < 0 ? 1 : -1));
    }
    startX = null;
  }, {passive:true});
})();
