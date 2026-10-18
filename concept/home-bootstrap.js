// The document is complete HTML. Load interactive controllers only for intent.
(() => {
  const template=document.getElementById('home-controllers');
  if(!template)return;
  const sources=[...template.content.querySelectorAll('script[src]')];
  let pending=null,loaded=0,ready=false,bypass=false,observer;
  const story=document.querySelector('.story');
  function nearStory(){
    if(!story)return false;
    const box=story.getBoundingClientRect();
    return box.top<innerHeight+600&&box.bottom>-600&&(scrollY>0||box.top<innerHeight);
  }
  function feedback(){
    if(document.getElementById('home-interaction-status'))return;
    const note=document.createElement('p');note.id='home-interaction-status';note.setAttribute('role','status');
    note.textContent=document.documentElement.lang==='uk'?'Інтерактивний перегляд недоступний. Спробуйте ще раз.':'The interactive view is unavailable. Please try again.';
    note.style.cssText='position:fixed;left:20px;right:20px;bottom:20px;z-index:90;padding:18px;background:#16232a;color:#f5f4ef;border:1px solid #94c6b7';
    document.body.append(note);
  }
  function enhance(){
    if(ready)return Promise.resolve();
    if(pending)return pending;
    pending=(async()=>{
      while(loaded<sources.length){
        const source=sources[loaded];
        await new Promise((resolve,reject)=>{
          const script=document.createElement('script');
          script.src=source.src;script.async=false;
          script.onload=()=>{loaded++;resolve();};
          script.onerror=()=>{script.remove();reject(new Error('Homepage controller unavailable'));};
          document.head.append(script);
        });
      }
      if(!document.querySelector('.menu-button').hasAttribute('aria-expanded'))throw new Error('Homepage enhancement unavailable');
      ready=true;document.body.dataset.homeEnhanced='true';
      document.getElementById('home-interaction-status')?.remove();
      observer?.disconnect();removeEventListener('scroll',approach);removeEventListener('resize',approach);removeEventListener('hashchange',hashEntry);document.removeEventListener('click',click,true);
    })().catch(error=>{pending=null;throw error;});
    return pending;
  }
  function approach(){if(nearStory())enhance().catch(feedback);}
  function hashEntry(){if(['#design-process','#story'].includes(location.hash))enhance().catch(feedback);}
  function currentTarget(target){
    if(target.isConnected)return target;
    for(const key of ['lang','service','chapter'])if(target.dataset[key]!==undefined)return document.querySelector('[data-'+key+'="'+CSS.escape(target.dataset[key])+'"]');
    return null;
  }
  function click(event){
    if(ready||bypass||event.defaultPrevented||event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    const target=event.target.closest('#app .menu-button,#app [data-lang],#app [data-service],#app .story button,#app a[href="#design-process"]');
    if(!target)return;
    event.preventDefault();event.stopImmediatePropagation();
    enhance().then(()=>currentTarget(target)?.click()).catch(()=>{
      feedback();
      // Native language links and :target navigation remain useful on failure.
      if(target.matches('a[href]')){bypass=true;target.click();bypass=false;}
    });
  }
  document.addEventListener('click',click,true);
  addEventListener('scroll',approach,{passive:true});
  addEventListener('resize',approach);
  addEventListener('hashchange',hashEntry);
  if(story&&typeof IntersectionObserver==='function'){
    observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))approach();},{rootMargin:'600px 0px'});
    observer.observe(story);
  }
  if(!story)enhance().catch(feedback);
  else{hashEntry();approach();}
})();
