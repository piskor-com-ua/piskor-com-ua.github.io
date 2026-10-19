(() => {
  function start() {
    const pictures = [...document.querySelectorAll('picture[data-zabava-gallery]')];
    let observer;
    function activate(picture) {
      if (!picture.hasAttribute('data-zabava-gallery')) return;
      for (const node of picture.querySelectorAll('[data-zabava-srcset]')) {
        node.setAttribute('srcset', node.getAttribute('data-zabava-srcset'));
        node.removeAttribute('data-zabava-srcset');
      }
      const image = picture.querySelector('img');
      image.setAttribute('src', image.getAttribute('data-zabava-src'));
      image.removeAttribute('data-zabava-src');
      picture.removeAttribute('data-zabava-gallery');
      observer?.unobserve(image);
    }
    for (const picture of pictures) {
      const target = picture.closest('[data-gallery]') || picture;
      target.addEventListener('focusin', () => activate(picture));
      target.addEventListener('click', () => activate(picture), {capture: true});
    }
    if (!('IntersectionObserver' in window)) {
      pictures.forEach(activate);
      return;
    }
    try {
      observer = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) activate(entry.target.closest('picture'));
      }, {rootMargin: '750px 0px', threshold: 0});
      for (const picture of pictures) observer.observe(picture.querySelector('img'));
    } catch {
      observer?.disconnect();
      pictures.forEach(activate);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
