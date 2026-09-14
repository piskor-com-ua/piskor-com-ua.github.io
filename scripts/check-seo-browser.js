async page => {
  await page.setViewportSize({width:1440,height:900});
  const origin='http://127.0.0.1:4173';
  const routes=[['/','uk'],['/en/','en'],['/portfolio/lviv-apartment/','uk'],['/en/portfolio/lviv-apartment/','en']];
  const titles=new Set(), results=[];
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  for(const [route,lang] of routes){
    await page.goto(origin+route);
    const title=await page.title();
    if(/concept|концепт/i.test(title)||titles.has(title))throw Error('Invalid title '+title);
    titles.add(title);
    if(await page.locator('html').getAttribute('lang')!==lang)throw Error('Wrong language');
    if(await page.locator('link[rel=canonical]').getAttribute('href')!=='https://piskor-com-ua.github.io'+route)throw Error('Wrong canonical');
    if(await page.locator('link[hreflang]').count()!==3)throw Error('Missing alternates');
    if(await page.locator('meta[property="og:title"]').getAttribute('content')!==title)throw Error('Stale OG title');
    await page.evaluate(async()=>Promise.all([...document.images].filter(i=>i.getAttribute('src')).map(i=>{i.loading='eager';return i.decode();})));
    const missing=await page.evaluate(()=>[...document.querySelectorAll('a[href^="#"]')].filter(a=>a.hash&&!document.getElementById(a.hash.slice(1))).map(a=>a.hash));
    if(missing.length)throw Error('Missing anchors '+missing);
    results.push(route+' — '+title);
  }
  await page.goto(origin+'/');
  await page.locator('[data-lang="en"]').click();
  if(page.url().slice(origin.length).split(/[?#]/)[0]!=='/en/'||!await page.title().then(t=>t.includes('Architecture')))throw Error('English switch');
  await page.reload();
  if(await page.locator('html').getAttribute('lang')!=='en')throw Error('English refresh');
  await page.locator('[data-lang="uk"]').click();
  if(page.url().slice(origin.length).split(/[?#]/)[0]!=='/')throw Error('Ukrainian switch');
  for(const old of ['/lviv-apartment.html','/lviv-apartment-en.html']){
    if((await page.request.get(origin+old)).status()!==404)throw Error('Old route still exists: '+old);
  }
  for(const [old,expected] of [['/portfolio/lviv-apartment/#chapter-2','/portfolio/lviv-apartment/#space-planning'],['/en/portfolio/lviv-apartment/#chapter-5','/en/portfolio/lviv-apartment/#design-result'],['/?lang=en#story','/en/#design-process']]){
    await page.goto(origin+old);
    await page.waitForURL(origin+expected);
    await page.waitForFunction(()=>Math.abs(document.getElementById(location.hash.slice(1)).getBoundingClientRect().top)<180);
    results.push('Legacy link works: '+old);
  }
  await page.locator('.nav a[href="#portfolio"]').click();
  await page.locator('.portfolio-card').click();
  await page.locator('[data-gallery]').first().click();
  if(!await page.locator('.project-lightbox').evaluate(d=>d.open))throw Error('Gallery failed');
  await page.keyboard.press('ArrowRight');await page.keyboard.press('Escape');
  if(errors.length)throw Error(errors.join('\n'));
  return results;
}
