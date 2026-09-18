// Preserve shared section links from before the URL migration.
(() => {
  const aliases = {story:'design-process', services:'architecture-services', approach:'our-approach', gallery:'project-story'};
  function restoreAnchor() {
    const old = location.hash.slice(1), id = aliases[old] || old;
    if (!id) return;
    const target = document.getElementById(id);
    if (!target) return;
    if (old !== id) history.replaceState(null, '', location.pathname + location.search + '#' + id);
    target.scrollIntoView({behavior:'instant'});
  }
  addEventListener('load', restoreAnchor);
  addEventListener('hashchange', restoreAnchor);
})();
