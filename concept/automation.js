const systemState={group:'light',focus:'',presence:false,biodynamic:false,humidity:45,ventilation:false,floor:false,music:false,volume:35,leak:false,smoke:false,gas:false,armed:false,locked:true,gate:false,window:false,irrigation:false,robot:false,tariff:false};
const systemDefaults={...systemState};
const systemCopy={
 uk:{groups:['Світло','Клімат','Медіа','Безпека','Приводи','Побут'],map:'Стан систем',presence:'Імітація присутності',biodynamic:'Біодинамічне світло',humidity:'Вологість',ventilation:'Посилена вентиляція',floor:'Тепла підлога',music:'Мультирум',volume:'Гучність',leak:'Симуляція протікання',smoke:'Симуляція диму',gas:'Симуляція витоку газу',armed:'Охорона периметра',locked:'Замок вхідних дверей',gate:'Ворота',window:'Провітрювання вікном',irrigation:'Автополив',robot:'Робот-пилосос',tariff:'Перенесення споживання на ніч',alloff:'Вимкнути все й увімкнути охорону',on:'Увімкнено',off:'Вимкнено',open:'Відкрито',closed:'Закрито',lockedState:'Замкнено',unlocked:'Відімкнено',valve:'Вода перекрита',gasOff:'Газ перекрито · сповіщення',normal:'Датчики в нормі',alarm:'Виявлено дим · сповіщення',demo:'Демонстрація · без підключення до обладнання',labels:['Світло','Клімат','Медіа','Вода','Доступ','Двір','Прибирання'],status:'Активні системи',idle:'Налаштування застосовано',robotRun:'Прибирання триває',watering:'Полив активний',night:'Побутові задачі заплановано на ніч'},
 en:{groups:['Lighting','Climate','Media','Security','Drives','Home'],map:'System status',presence:'Presence simulation',biodynamic:'Biodynamic lighting',humidity:'Humidity',ventilation:'Boost ventilation',floor:'Underfloor heating',music:'Multiroom audio',volume:'Volume',leak:'Simulate a water leak',smoke:'Simulate smoke',gas:'Simulate a gas leak',armed:'Perimeter security',locked:'Entrance door lock',gate:'Gate',window:'Window ventilation',irrigation:'Lawn irrigation',robot:'Robot vacuum',tariff:'Shift consumption to night',alloff:'All off and arm security',on:'On',off:'Off',open:'Open',closed:'Closed',lockedState:'Locked',unlocked:'Unlocked',valve:'Water shut off',gasOff:'Gas shut off · notification',normal:'Sensors normal',alarm:'Smoke detected · notification',demo:'Demonstration · no connected equipment',labels:['Light','Climate','Media','Water','Access','Garden','Cleaning'],status:'Active systems',idle:'Settings applied',robotRun:'Cleaning in progress',watering:'Irrigation active',night:'Household tasks scheduled for night'}
};
function toggleRow(key){const t=systemCopy[locale];return `<div class="system-toggle-row"><span>${t[key]}</span><button data-system="${key}" aria-label="${t[key]}" aria-pressed="${systemState[key]}"></button></div>`;}
function rangeRow(key,min,max,unit){const t=systemCopy[locale];return `<label class="range-label" for="system-${key}">${t[key]}<output data-system-output="${key}">${systemState[key]}${unit}</output></label><input type="range" id="system-${key}" aria-label="${t[key]}" data-system-range="${key}" min="${min}" max="${max}" value="${systemState[key]}">`;}
function automationPanelHTML(ui){const t=systemCopy[locale],keys=['light','climate','media','security','drives','home'];return `<div class="automation-heading"><div><span class="eyebrow">${ui.preset}</span><h3 class="preset-name"></h3></div><span class="status-dot" aria-hidden="true"></span></div><div class="preset-tabs" role="group" aria-label="${ui.preset}">${ui.presets.map((p,i)=>`<button data-preset="${i}" aria-pressed="false">${p}</button>`).join('')}</div><div class="scene-preview"></div><div class="system-group-tabs" role="group" aria-label="${t.map}">${keys.map((key,i)=>`<button data-system-group="${key}" aria-pressed="${key===systemState.group}">${t.groups[i]}</button>`).join('')}</div>
<section data-system-section="light"><label class="range-label" for="light-control">${ui.light}<output id="light-output" for="light-control"></output></label><input id="light-control" aria-label="${ui.light}" data-control="light" type="range" min="0" max="100" step="5" value="${automation.light}">${toggleRow('presence')}${toggleRow('biodynamic')}</section>
<section data-system-section="climate"><label class="range-label" for="climate-control">${ui.climate}<output id="climate-output" for="climate-control"></output></label><input id="climate-control" aria-label="${ui.climate}" data-control="temp" type="range" min="16" max="28" step="1" value="${automation.temp}">${rangeRow('humidity',30,65,'%')}${toggleRow('ventilation')}${toggleRow('floor')}</section>
<section data-system-section="media">${toggleRow('music')}${rangeRow('volume',0,100,'%')}<p class="system-hint">${t.demo}</p></section>
<section data-system-section="security">${toggleRow('leak')}${toggleRow('smoke')}${toggleRow('gas')}${toggleRow('armed')}${toggleRow('locked')}${toggleRow('gate')}<div class="sensor-status" role="status"></div><div class="security-state"></div></section>
<section data-system-section="drives"><div class="curtain-control"><span>${ui.curtains}</span><button data-curtains aria-pressed="false"></button></div>${toggleRow('window')}<button class="all-off" data-system-group="security">${t.groups[3]} · ${t.gate} ↗</button></section>
<section data-system-section="home">${toggleRow('irrigation')}${toggleRow('robot')}${toggleRow('tariff')}<button class="all-off" data-all-off>${t.alloff} ↗</button></section><div class="system-summary" role="status"></div><div class="automation-foot"><span>${ui.demo}</span><button data-reset>${ui.reset} ↺</button></div>`;}
function updateSystems(){if(activeChapter!==4)return;const p=document.querySelector('.automation-panel'),t=systemCopy[locale];p.querySelectorAll('[data-system-section]').forEach(e=>e.hidden=e.dataset.systemSection!==systemState.group);p.querySelectorAll('[data-system-group]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.systemGroup===systemState.group)));p.querySelectorAll('[data-system]').forEach(b=>{const k=b.dataset.system,on=systemState[k];b.setAttribute('aria-pressed',String(on));b.textContent=k==='locked'?(on?t.lockedState:t.unlocked):['gate','window'].includes(k)?(on?t.open:t.closed):(on?t.on:t.off);});p.querySelectorAll('[data-system-output]').forEach(o=>o.textContent=systemState[o.dataset.systemOutput]+'%');p.querySelectorAll('[data-system-range]').forEach(r=>r.value=systemState[r.dataset.systemRange]);
p.querySelector('.sensor-status').textContent=[systemState.leak?t.valve:'',systemState.smoke?t.alarm:'',systemState.gas?t.gasOff:''].filter(Boolean).join(' · ')||t.normal;
const flags={light:automation.light>0,air:systemState.ventilation,heat:systemState.floor,media:systemState.music,water:systemState.leak,garden:systemState.irrigation,robot:systemState.robot,lock:systemState.locked,gate:systemState.gate,window:systemState.window,alarm:systemState.smoke||systemState.gas||systemState.armed};Object.entries(flags).forEach(([key,on])=>p.classList.toggle('system-'+key,on));
const notes=[systemState.robot?t.robotRun:'',systemState.irrigation?t.watering:'',systemState.tariff?t.night:''];p.querySelector('.system-summary').textContent=notes.filter(Boolean).join(' · ')||t.idle;
const stage=document.querySelector('.story-sticky');Object.entries(systemState).forEach(([key,v])=>{if(typeof v==='boolean')stage.classList.toggle('device-'+key,v);});stage.style.setProperty('--humidity',systemState.humidity/100);stage.style.setProperty('--volume',systemState.volume/100);
let visuals=document.querySelector('.device-effects');if(!visuals){visuals=document.createElement('div');visuals.className='device-effects';document.querySelector('.stage-visual').append(visuals);}visuals.style.display='';updateScenePreview();
}
function systemClick(b){if(b.dataset.preset!==undefined){const i=Number(b.dataset.preset),group=systemState.group;Object.assign(systemState,systemDefaults,{group,armed:i===3,music:i===1||i===2,biodynamic:i===0,locked:true});}if(b.dataset.systemGroup){systemState.group=b.dataset.systemGroup;systemState.focus='';updateAutomation();}if(b.dataset.system){const key=b.dataset.system;systemState.focus=key;systemState[key]=!systemState[key];if(key==='armed')automation.armed=systemState.armed;automation.preset=-1;updateAutomation();}if(b.hasAttribute('data-all-off')){Object.assign(systemState,systemDefaults,{group:'home',armed:true});automation={preset:3,...presets[3]};updateAutomation();}if(b.hasAttribute('data-reset')){Object.assign(systemState,systemDefaults);updateSystems();}}


// A control chooses a real view of the same house, never a generic substitute.
function automationSceneAsset(){
 const {group,focus}=systemState;
 if(group==='security')return ['leak','gas','smoke'].includes(focus)?'kitchen':systemState.gate?'entryOpen':'entry';
 if(group==='drives')return automation.curtains&&focus!=='window'?'privacy':'interior';
 if(group==='climate')return 'climate';
 if(group==='home')return focus==='robot'?'climate':'house';
 return automation.curtains?'privacy':automation.asset||'interior';
}
function automationFeedback(){
 const t=systemCopy[locale],uk=locale==='uk',state=k=>systemState[k]?t.on:t.off;
 const groups={
 light:[`${storyUI[locale].light}: ${automation.light}%`,`${t.presence}: ${state('presence')}`,`${t.biodynamic}: ${state('biodynamic')}`],
 climate:[`${uk?'Задана температура':'Target temperature'}: ${automation.temp} °C`,`${t.humidity}: ${systemState.humidity}%`,`${t.ventilation}: ${state('ventilation')}`,`${t.floor}: ${state('floor')}`],
 media:[`${t.music}: ${state('music')}`,`${t.volume}: ${systemState.volume}%`,uk?'Демонстрація без відтворення звуку':'Demo without audio playback'],
 security:[`${t.gate}: ${systemState.gate?t.open:t.closed}`,`${t.locked}: ${systemState.locked?t.lockedState:t.unlocked}`,systemState.armed?storyUI[locale].armed:storyUI[locale].home,systemState.leak?t.valve:'',systemState.gas?t.gasOff:'',systemState.smoke?t.alarm:''].filter(Boolean),
 drives:[`${storyUI[locale].curtains}: ${automation.curtains?t.closed:t.open}`,`${t.window}: ${systemState.window?t.open:t.closed}`],
 home:[`${t.robot}: ${systemState.robot?t.robotRun:t.off}`,`${t.irrigation}: ${systemState.irrigation?t.watering:t.off}`,`${t.tariff}: ${systemState.tariff?t.night:t.off}`]
 };
 return groups[systemState.group];
}
function updateScenePreview(){
 const root=document.querySelector('.story-sticky'),panel=document.querySelector('.automation-panel'),key=automationSceneAsset(),feedback=automationFeedback();
 const preview=panel.querySelector('.scene-preview');
 if(!preview.firstElementChild)preview.innerHTML='<div class="scene-photo" role="img"></div>';
 const photo=preview.querySelector('.scene-photo');photo.style.backgroundImage=`url("${assets[key]}")`;
 photo.setAttribute('aria-label',locale==='uk'?'Концептуальний простір студії':'Studio concept space');
 preview.dataset.scene=key;
 preview.style.setProperty('--scene-light',['light','media'].includes(systemState.group)? .45+automation.light*.0055:1);
 preview.classList.toggle('scene-biodynamic',systemState.biodynamic&&systemState.group==='light');
 const notes=panel.querySelector('.system-summary');notes.replaceChildren(...feedback.map(text=>{const line=document.createElement('div');line.textContent=text;return line;}));
 // Keep status out of the photograph so no rectangular overlay obscures the space.
 root.querySelector('.device-effects').replaceChildren();
 root.dataset.controlGroup=systemState.group;
 const indoor=['interior','night','privacy','climate'].includes(key);
 root.style.setProperty('--light',indoor&&['light','media'].includes(systemState.group)?String(.45+automation.light*.0055):'1');
 root.style.setProperty('--warmth',indoor&&systemState.group==='climate'?String((automation.temp-16)/12*.1):'0');
}
