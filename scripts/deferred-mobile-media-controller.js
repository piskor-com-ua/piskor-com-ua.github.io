(() => {
  function start() {
    const pictures = [...document.querySelectorAll('picture[data-piskor-deferred-media]')];
    let observer;
    function activate(picture) {
      if (!picture.hasAttribute('data-piskor-deferred-media')) return;
      for (const node of picture.querySelectorAll('[data-piskor-srcset]')) {
        node.setAttribute('srcset', node.getAttribute('data-piskor-srcset'));
        node.removeAttribute('data-piskor-srcset');
      }
      const image = picture.querySelector('img');
      image.setAttribute('src', image.getAttribute('data-piskor-src'));
      image.removeAttribute('data-piskor-src');
      picture.removeAttribute('data-piskor-deferred-media');
      observer?.unobserve(image);
    }
    for (const picture of pictures) {
      const target = picture.closest('[data-gallery]') || picture.closest('a') || picture;
      target.addEventListener('focusin', () => activate(picture));
      target.addEventListener('click', () => activate(picture), {capture: true});
    }
    if (!('IntersectionObserver' in window)) {
      pictures.forEach(activate);
      return;
    }
    try {
      observer = new IntersectionObserver(entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) activate(entry.target.closest('picture'));
        }
      }, {rootMargin: '250px 0px', threshold: 0});
      for (const picture of pictures) observer.observe(picture.querySelector('img'));
    } catch {
      observer?.disconnect();
      pictures.forEach(activate);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
