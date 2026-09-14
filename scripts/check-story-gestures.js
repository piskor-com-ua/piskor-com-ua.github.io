async page => {
 const results=[];
 const assert=(ok,message)=>{if(!ok)throw Error(message);results.push(message);};
 await page.setViewportSize({width:1440,height:900});
 await page.goto("http://127.0.0.1:4173/index.html");
 const reset=async index=>page.evaluate(index=>{
  finishStoryExit();touchAnchor=null;nativeTouchUntil=0;wheelLast=0;wheelDirection=0;wheelLatched=false;wheelTotal=0;wheelPeak=0;wheelTrough=Infinity;jumpFrame(index);
 },index);
 const wheel=async delta=>page.evaluate(delta=>document.querySelector(".story").dispatchEvent(new WheelEvent("wheel",{deltaY:delta,bubbles:true,cancelable:true})),delta);
 const state=()=>page.evaluate(()=>({frame:activeFrame,y:scrollY,services:document.querySelector("#services").getBoundingClientRect().top}));
 await reset(3);await wheel(100);await wheel(70);await wheel(30);await wheel(8);
 assert((await state()).frame===4,"One wheel burst advances one scene");
 await page.waitForTimeout(90);await wheel(5);await page.waitForTimeout(80);await wheel(60);
 assert((await state()).frame===5,"Renewed impulse during inertia advances without a multi-second wait");
 for(const d of [40,25,12,6,3])await wheel(d);
 assert((await state()).frame===5,"Decaying tail does not advance again");
 await page.waitForTimeout(150);await wheel(80);
 assert((await state()).frame===6,"New gesture after 150ms advances");
 await wheel(-80);assert((await state()).frame===5,"Direction reversal works immediately");
 await reset(19);await wheel(90);for(const d of [70,40,20,10])await wheel(d);
 await page.waitForTimeout(420);
 assert(Math.abs((await state()).services)<2,"Exit aligns services heading without momentum overshoot");
 await page.waitForTimeout(150);await wheel(-4000);
 assert((await state()).frame===19,"Entry from services stops at Integration");
 await wheel(-200);assert((await state()).frame===19,"Entry consumes the entire burst");
 await reset(0);
 await page.evaluate(()=>{wheelLatched=false;wheelLast=0;window.scrollTo({top:document.querySelector("#portfolio").offsetTop,behavior:"instant"});});
 await wheel(-20000);assert((await state()).frame===19,"Large upward wheel from portfolio stops at Integration");
 await reset(0);await page.evaluate(()=>{wheelLatched=false;wheelLast=0;window.scrollTo({top:0,behavior:"instant"});});
 await wheel(20000);assert((await state()).frame===0,"Large downward wheel from top stops at first scene");
 await wheel(300);assert((await state()).frame===0,"Top-entry tail cannot skip scenes");
 // The compositor can move farther than the delta in the preceding wheel
 // callback. Test actual position changes independently of delta prediction.
 for(const direction of [1,-1]){
  await reset(0);
  await page.evaluate(direction=>{window.scrollTo({top:direction>0?0:document.documentElement.scrollHeight,behavior:"instant"});lastStoryScrollY=scrollY;},direction);
  await wheel(direction*10);
  await page.evaluate(()=>{window.scrollTo({top:document.querySelector(".story").offsetTop+4000,behavior:"instant"});updateScroll();});
  const entry=direction>0?0:19;
  assert((await state()).frame===entry,"Native wheel crossing captures boundary: "+direction);
  const anchor=(await state()).y;
  await page.evaluate(direction=>{window.scrollBy({top:direction*2000,behavior:"instant"});updateScroll();},direction);
  await wheel(direction*8);
  assert((await state()).frame===entry&&Math.abs((await state()).y-anchor)<2,"Native momentum stays anchored: "+direction);
  await page.waitForTimeout(150);await wheel(direction*60);
  assert((await state()).frame===entry+direction,"Fresh wheel releases entry anchor: "+direction);
 }
 const touch=async(type,y)=>page.evaluate(({type,y})=>{
  const event=new Event(type,{bubbles:true,cancelable:true});Object.defineProperty(event,"touches",{value:type==="touchend"?[]:[{clientX:100,clientY:y}]});document.querySelector(".story").dispatchEvent(event);
 },{type,y});
 await page.setViewportSize({width:390,height:844});await reset(5);
 await touch("touchstart",700);await touch("touchmove",600);await touch("touchmove",400);await touch("touchend",400);
 assert((await state()).frame===6,"One touch advances only one scene");
 await touch("touchstart",700);await touch("touchmove",600);await touch("touchend",600);
 assert((await state()).frame===7,"Next touch advances immediately");
 await reset(19);await touch("touchstart",700);await touch("touchmove",500);await touch("touchend",500);await page.waitForTimeout(420);
 assert(Math.abs((await state()).services)<2,"Touch exit aligns services");
 await touch("touchstart",200);await touch("touchmove",400);await touch("touchmove",600);await touch("touchend",600);
 assert((await state()).frame===19,"Touch re-entry stops on Integration");
 // Simulate native momentum arriving after a swipe outside the section.
 await reset(19);await page.evaluate(()=>{window.scrollTo({top:document.querySelector("#portfolio").offsetTop,behavior:"instant"});lastStoryScrollY=scrollY;});
 await touch("touchstart",100);await touch("touchmove",110);await touch("touchend",110);
 await page.evaluate(()=>{window.scrollTo({top:document.querySelector(".story").offsetTop+100,behavior:"instant"});updateScroll();});
 assert((await state()).frame===19,"Native upward overshoot catches last scene");
 await page.evaluate(()=>{window.scrollBy({top:-900,behavior:"instant"});updateScroll();});
 assert((await state()).frame===19,"Native inertia remains at captured scene");
 await touch("touchstart",100);await touch("touchmove",220);await touch("touchend",220);
 assert((await state()).frame===18,"Fresh touch releases inertia guard immediately");
 assert(await page.locator(".hero-caption").count()===0,"Hero demonstration caption removed");
 await page.emulateMedia({reducedMotion:"reduce"});await page.waitForTimeout(50);
 await page.evaluate(()=>window.scrollTo({top:0,behavior:"instant"}));
 assert(await wheel(100),"Reduced-motion wheel remains native");
 await page.emulateMedia({reducedMotion:"no-preference"});
 return results;
}
