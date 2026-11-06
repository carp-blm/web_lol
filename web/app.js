const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roles = ['top','jng','mid','bot','sup'];
const roleKo = {top:'탑',jng:'정글',mid:'미드',bot:'바텀',sup:'서포터'};
const phaseKo = {regular:'정규시즌',semifinal:'플레이오프 · 준결승',final:'플레이오프 · 결승',complete:'시즌 종료'};
const clock = (t) => `${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`;
const num = (n) => Number(n).toLocaleString('ko-KR');
const norm = (s) => String(s).toLowerCase().replace(/[^a-z0-9]/g,'');
let catalog, champs, media, cards, aliases, state, saveText, busy=false, tab='home', auto=true, speed=6;
let storageBlocked=false, storedRecovery=null, toastTimer, lastEventId=null;
let lastOpenedRole=null, resumeAfterNew=false;
let draftSearch='', draftRole=null, inspectedUnit='0:mid', feedFilter='all';
const mapPositions=new Map();
const summonerSelections=new Map();
const freshSeed=()=>`NEXUS-${Array.from(crypto.getRandomValues(new Uint32Array(2)),n=>n.toString(16)).join('-')}`;
let collectionFilter={search:'',role:'any',year:'any',owned:'owned',limit:30};
const STORAGE = `nexus-archive:${location.pathname.replace(/index\.html$/, '')}:v1`;
const worker = new Worker(new URL('./worker.js?v=0.6.0', import.meta.url), {type:'module'});
let workerFailure=null;
const pending=new Map(); let sequence=0;
worker.onmessage=({data})=>{
  if(data.status){$('#load-status').textContent=data.status;return;}
  const p=pending.get(data.id);if(!p)return;
  clearTimeout(p.timeout);pending.delete(data.id);
  data.ok?p.resolve(data):p.reject(new Error(data.error));
};
worker.onerror=()=>{workerFailure=new Error('Python 엔진 연결이 끊겼습니다. 페이지를 새로고침해 주세요.');for(const p of pending.values()){clearTimeout(p.timeout);p.reject(workerFailure);}pending.clear();};
function rpc(action){return new Promise((resolve,reject)=>{if(workerFailure){reject(workerFailure);return;}const id=++sequence;const timeout=setTimeout(()=>{pending.delete(id);reject(new Error('엔진 응답 시간이 초과됐습니다. 새로고침 후 다시 시도해 주세요.'));},120000);pending.set(id,{resolve,reject,timeout});worker.postMessage({id,action});});}
function toast(message,error=false){const el=$('#toast');el.textContent=message;el.classList.toggle('error',error);el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,error?8000:4000);}
function persist(){if(storageBlocked||!saveText)return;try{localStorage.setItem(STORAGE,saveText);}catch{storageBlocked=true;toast('자동 저장을 사용할 수 없습니다. 세이브를 파일로 내보내 주세요.',true);}}
async function act(action,{switchTo=null,quiet=false}={}){
  if(busy)return;busy=true;
  try{
    const result=await rpc(action);state=result.state;saveText=result.save;
    lastOpenedRole=action.type==='starter_open'?action.role:null;
    if(action.type==='import'||action.type==='new'){mapPositions.clear();draftRole=null;storageBlocked=false;storedRecovery=null;if(state.banpick)switchTo='draft-room';}
    persist();if(switchTo){tab=switchTo;window.scrollTo(0,0);}render();
    if(!quiet&&['pull','equip','import','new'].includes(action.type))toast(action.type==='pull'?state.notice:'저장했습니다.');
  }catch(e){toast(e.message,true);}finally{busy=false;}
}
function image(url,alt,cls=''){return `<img class="${cls}" src="${esc(url)}" alt="${esc(alt)}" loading="lazy" referrerpolicy="no-referrer">`;}
document.addEventListener('error',e=>{if(e.target.tagName==='IMG'&&!e.target.dataset.fallback){e.target.dataset.fallback='1';e.target.src='./assets/skill-placeholder.svg';}},true);
const precise=n=>Number(n.toFixed(2));
function masteries(c){return c.mastery.map(m=>({...m,id:aliases[norm(m.name)]})).filter(m=>m.id).map(m=>({...m,value:precise(Math.min(100,m.value+(state?.progression?.[c.id]?.mastery?.[m.id]??0)))}));}
function mastery(c,cid){return masteries(c).find(m=>m.id===cid)?.value??precise(Math.min(100,35+(state?.progression?.[c.id]?.mastery?.[cid]??0)));}
function grownCard(c){const progress=state.progression?.[c.id],ratings=Object.fromEntries(Object.entries(c.ratings).map(([k,v])=>[k,precise(Math.min(99,v+(progress?.stats?.[k]??0)))]));return {...c,ratings,overall:precise(Object.values(ratings).reduce((a,b)=>a+b,0)/4)};}
function skills(cid){const c=champs.champions[cid],form=c.kit?.initial??'base';const pool=(c.variants??c.skills).filter(s=>(s.form??'base')===form&&(!s.stage||s.stage===1));return ['P','Q','W','E','R'].map(k=>pool.find(s=>s.key===k&&s.castable)??pool.find(s=>s.key===k)).filter(Boolean).map(s=>`<span class="skill" title="${esc((s.display_key??s.key)+' · '+s.name+' · '+(s.form_label??'기본')+' · '+(effectText(s)||'이동/보조'))}">${image(s.icon,s.name)}<small>${s.display_key??s.key}</small></span>`).join('');}
function showAbilities(cid){
  const c=champs.champions[cid],groups=c.kit.form_order.map(form=>[form,c.kit.forms[form]]);
  $('#ability-content').innerHTML=`<span class="eyebrow">ABILITY ARCHIVE · ${esc(champs.version)}</span><h2>${esc(c.name)}의 스킬</h2><p class="muted">${esc(c.kit.condition??'패시브와 기본 스킬입니다.')}</p><div class="ability-groups">${groups.map(([form,label])=>`<section class="ability-group"><h3>${esc(label)}</h3>${c.variants.filter(s=>s.form===form).map(s=>`<div class="ability-entry">${image(s.icon,s.name)}<div><strong><span>${esc(s.display_key)}</span> ${esc(s.name)}</strong><small>${s.castable?'시전 스킬':s.control?'형태 전환 / 선택기':s.unavailable?'현재 형태에서 사용 불가':'지속 효과 · 직접 시전하지 않음'}${s.stage?' · '+s.stage+'단계':''} · ${esc(s.tags.join(' / '))}</small><small class="effect-summary">${esc(effectText(s))}</small></div></div>`).join('')}</section>`).join('')}</div><p class="evidence">현재 형태와 재시전 조건에 맞는 스킬만 경기에서 사용합니다. 아이콘은 Data Dragon이 제공하는 해당 슬롯의 기본 아이콘을 공유합니다.</p><a href="${esc(c.source)}" target="_blank" rel="noopener">공식 한국어 스킬 자료 ↗</a>`;
  $('#ability-dialog').showModal();
}
function unitAbilityStatus(u){
  if(!u.ability_state)return '기존 경기 규칙 · 다음 경기부터 형태 적용';
  const a=u.ability_state,b=a.borrowed;
  const form=b?`빙의 · ${champs.champions[b.champion].name} / ${b.state.form_label}`:a.form_label;
  const ready=(u.available_skills??[]).map(s=>s.display_key??s.key).join(' · ')||'기본 공격';
  return `${esc(form)}<br><span class="ready-skills" title="${esc((u.available_skills??[]).map(s=>s.name).join(' / '))}">준비 ${esc(ready)}</span>`;
}
const ccKo={blind:'실명',slow:'감속',root:'속박',polymorph:'변이',stun:'기절',airborne:'공중에 뜸',suppression:'제압',silence:'침묵',fear:'공포',charm:'매혹',taunt:'도발',sleep:'수면'};
function effectText(s){const e=s.effects;if(!e)return '';const targets={self:'자신',ally:'다른 아군',both:'자신/아군',team:'주변 아군'};const kinds={heal:'회복',shield:'보호막',magic_shield:'마법 보호막',bonus_health:'추가 체력',revive:'조건부 부활',invulnerable:'죽음 방지',rescue:'아군 구조'};return [e.damage?'피해':'',...e.cc.map(c=>ccKo[c]??c),...e.defense.map(d=>`${targets[d.target]} ${kinds[d.kind]}`),e.aoe?'다중 적중 판정':''].filter(Boolean).join(' · ');}
function unitHealth(u,time){if(u.hp===undefined)return '';const label=u.status==='dead'?`사망 · ${u.return_at-time}초`:u.status==='recall'?`귀환 · ${u.return_at-time}초`:`${({top:'탑',mid:'미드',bot:'바텀',jungle:'정글',river:'강가'})[u.location]??u.location}${u.roam_until>time?' · 이동 중':''}`;return `<div class="unit-health"><div><strong>${Math.round(u.hp)}%</strong><small>${esc(label)}</small></div><div class="bar ${u.side?'red':''}"><i style="width:${u.hp}%"></i></div><small>${u.kills}/${u.deaths}/${u.assists} · CS ${u.cs}</small></div>`;}
function visionPanel(m){if(!m.local_vision)return '';return `<div class="vision-panel"><span>주변 시야 · 우리 / 상대</span>${['top','mid','bot','jungle','river'].map(l=>`<div><small>${({top:'탑',mid:'미드',bot:'바텀',jungle:'정글',river:'강가'})[l]}</small><b>${m.local_vision[0][l].toFixed(1)} / ${m.local_vision[1][l].toFixed(1)}</b></div>`).join('')}</div><div class="hint">와드 설치 ${m.vision_actions[0].placed} · 제거 ${m.vision_actions[0].cleared} · 제어 와드 ${m.vision_actions[0].control}${m.objective_attempt?`<br>${m.objective_attempt.kind} 사냥 진행 · ${Math.max(0,m.objective_attempt.finish_at-m.time)}초`:''}</div>`;}
function activeMatch(){return state?.match&&state.match.winner===null;}
function starterHome(){
  const starter=state.starter,opened=roles.filter(r=>starter.packs[r].card).length;
  const leagues=[...new Set(catalog.cards.map(c=>c.league))].sort();
  $('#home').innerHTML=`<div class="page-heading"><div><span class="eyebrow">YOUR FIRST FIVE</span><h1>첫 드림팀을<br><em>직접 열어보세요.</em></h1><p class="muted">포지션마다 한 번, 무료로 만나는 새로운 선수.<br>팩마다 리그와 연도를 고르고 원하는 순서로 열어보세요.</p></div><div class="starter-progress"><b>${opened}<span> / 5</span></b><small>팩 개봉 완료</small><div class="pack-progress" aria-label="${opened}개 팩 개봉"><i style="width:${opened*20}%"></i></div></div></div>
  <div class="starter-guide"><span>✧ 시작 팩은 무료입니다</span><span>600 CR은 그대로 보관됩니다</span><span>선택한 풀의 모든 카드가 같은 확률</span></div>
  <div class="starter-packs">${roles.map((r,i)=>{
    const pack=starter.packs[r],count=state.starter_counts[r];
    if(pack.card)return `<div class="starter-slot opened ${lastOpenedRole===r?'just-opened':''}"><div class="pack-label"><b>${roleKo[r]}</b><span>✓ 개봉 완료</span></div>${playerCard(cards[pack.card])}<p class="pack-receipt">${esc(pack.league==='any'?'전체 리그':pack.league)} · ${pack.year==='any'?'모든 연도':esc(pack.year)}</p></div>`;
    return `<article class="starter-slot"><div class="pack-label"><b>${roleKo[r]}</b><span>PACK 0${i+1}</span></div><div class="sealed-pack"><span class="pack-number">0${i+1}</span><span class="pack-emblem">${['♜','⌁','✧','⌖','◇'][i]}</span><strong>${r.toUpperCase()}</strong><small>NEXUS ARCHIVE</small></div><label>리그<select data-starter-filter="league" data-role="${r}" aria-label="${roleKo[r]} 팩 리그"><option value="any">전체 리그</option>${leagues.map(l=>`<option value="${esc(l)}" ${pack.league===l?'selected':''}>${esc(l)}</option>`).join('')}</select></label><label>연도<select data-starter-filter="year" data-role="${r}" aria-label="${roleKo[r]} 팩 연도"><option value="any">모든 연도</option>${catalog.coverage.years.map(y=>`<option value="${y}" ${pack.year===String(y)?'selected':''}>${y}</option>`).join('')}</select></label><p class="pack-pool ${count?'':'empty-pool'}">${count?`${num(count)}장 중 1장 · 카드당 ${(100/count).toFixed(2)}%`:'선수가 없는 조합입니다. 조건을 바꿔주세요.'}</p><button class="primary full" data-starter-open="${r}" ${count?'':'disabled'}>${roleKo[r]} 팩 열기 <span>↗</span></button></article>`;
  }).join('')}</div><div class="starter-footer"><p role="status" aria-live="polite">${esc(state.notice)}</p>${opened===5?'<button class="primary" data-action="starter_finish">드림팀으로 시즌 시작 <span>→</span></button>':'<span class="muted">열지 않은 팩은 언제든 조건을 바꿀 수 있습니다. 개봉 결과는 자동 저장됩니다.</span>'}</div>`;
}
function playerCard(c,{draft=false,collection=false}={}){
  c=grownCard(c);
  const photo=media.assets[c.id],logo=media.assets[c.team_media_key];
  const selected=state.roster[c.role]===c.id,owned=state.owned.includes(c.id);
  const champ=draft?state.draft[c.role]:(masteries(c)[0]?.id??'Ahri');
  const cp=champs.champions[champ];
  let picker='';
  if(draft){
    const experienced=masteries(c),known=new Set(experienced.map(m=>m.id));
    picker=`<div class="champion-select">${image(cp.portrait,cp.name)}<select aria-label="${esc(c.name)} 챔피언 선택" data-draft="${c.role}" ${activeMatch()||state.banpick?'disabled':''}><optgroup label="공식 출전 기반 숙련 챔피언">${experienced.map(m=>`<option value="${m.id}" ${m.id===champ?'selected':''}>${esc(champs.champions[m.id].name)} · ${m.value}</option>`).join('')}</optgroup><optgroup label="미출전 챔피언 · 기본 숙련도 35">${Object.values(champs.champions).filter(ch=>!known.has(ch.id)).sort((a,b)=>a.name.localeCompare(b.name,'ko')).map(ch=>`<option value="${ch.id}" ${ch.id===champ?'selected':''}>${esc(ch.name)} · ${mastery(c,ch.id)}</option>`).join('')}</optgroup></select></div><div class="skills">${skills(champ)}</div><p class="mastery">숙련도 ${mastery(c,champ)}</p><button class="skill-library-link" data-abilities="${champ}">형태별 스킬 보기 ↗</button>`;
  }
  return `<article class="player-card"><div class="player-top" data-year="${c.year}"><span class="role">${c.role.toUpperCase()}</span><span class="ovr">${c.overall}<small>OVR</small></span>${image(photo?.display??'assets/player-placeholder.svg',`${c.name} ${c.year} 프로필 대체 이미지`)}<span class="photo-note">${photo?.verified&&photo?.display?.includes('/approved/')?'검증 이미지':'프로필 대체 이미지'}</span></div><div class="player-info"><div class="player-name">${esc(c.name)}</div>${opsView()&&state.owned.includes(c.id)?`<div class="trait-line">${traitChips(c.id)}</div>`:''}${opsView()&&selected?staminaBar(c.id,{compact:true}):''}<div class="player-sub" title="${esc(c.team)}">${image(logo?.display??'assets/team-placeholder.svg','팀 로고 대체 이미지')}${c.year} · ${esc(c.team)}</div><div class="ratings"><span>라인전 <b>${c.ratings.lane}</b></span><span>전투 <b>${c.ratings.combat}</b></span><span>시야 <b>${c.ratings.vision}</b></span><span>성장 <b>${c.ratings.farm}</b></span></div>${picker}${cardDevelopment(c)}${collection?`<div class="evidence">${esc(c.league)} · ${c.tier}군 리그 · ${c.games}회 출전<br>${esc(cp?.name)} 숙련 ${mastery(c,champ)}</div><button class="${selected?'ghost':'secondary'}" data-equip="${c.id}" ${(!owned||selected||activeMatch()||state.banpick)?'disabled':''}>${selected?'선발 로스터':owned?'로스터 편성':'미보유'}</button><details class="evidence"><summary>출전 기록 확인</summary>${esc(c.evidence.first_date)}<br>${esc(c.evidence.first_game)}<br>마지막: ${esc(c.evidence.last_date)}<br>${esc(c.evidence.last_game)}</details>`:''}</div></article>`;
}
function opponent(){const s=state.season;if(s.phase==='complete')return null;if(s.phase!=='regular')return s.opponent;return s.schedule[s.round].find(p=>p.includes(0)).find(i=>i!==0);}
function startButton(){if(state.banpick)return '<button class="primary full" data-goto="draft-room">진행 중인 밴픽으로 →</button>';if(!state.starter.finished)return '<button class="primary" data-goto="home">시작 팩 열기 →</button>';if(state.reward_event)return '<button class="primary full" data-goto="relics">경기 보상 선택 →</button>';return activeMatch()?'<button class="primary full" data-goto="arena">진행 중인 경기로 <span>↗</span></button>':state.season.phase==='complete'?'<button class="primary full" data-action="next_season">다음 시즌 시작 <span>→</span></button>':'<button class="primary full" data-action="begin_draft">밴픽 시작 <span class="arrow">→</span></button>';}
function home(){
  if(!state.starter.finished){starterHome();return;}
  const s=state.season,opp=opponent(),record=s.teams[0],round=Math.min(s.round+1,5),team=opp===null?'SEASON COMPLETE':s.teams[opp].name;
  $('#home').innerHTML=`<div class="hero"><div><span class="eyebrow"><i class="line"></i> EVERY DECISION. YOUR LEGACY.</span><h1>기록은 그들의 것.<br><em>승리는 당신의 것.</em></h1><p>기록 속의 선수들을 당신의 로스터로.<br>드래프트부터 마지막 한타까지, 당신이 이끄는 새로운 역사.</p><div class="hero-meta"><span><b>${num(catalog.coverage.cards)}</b> 선수 카드</span><span><b>${catalog.coverage.years.join(' / ')}</b> 아카이브</span><span><span class="status-dot"></span> 로컬 플레이</span></div></div><div class="match-preview"><div class="preview-top"><span>SEASON ${String(state.season_number).padStart(2,'0')} / MATCHDAY ${String(round).padStart(2,'0')}</span><span class="pill">${esc(divisionInfo()?.name??'')} · ${phaseKo[s.phase]}</span></div><div class="versus"><div class="team-block"><div class="team-mark home-mark">N</div><b>NEXUS CLUB</b><small>나의 드림팀</small></div><span class="vs">VS</span><div class="team-block"><div class="team-mark">${team[0]}</div><b>${team}</b><small>${opp===null?'수고하셨습니다':s.teams[opp].style?`${esc(opsView().plans[s.teams[opp].style].name)} · 평균 OVR ${opsView().scouting?.overall??'—'}`:'전 세계 선수로 구성된 AI 구단'}</small></div></div>${opp!==null&&opsView()?.scouting?`<button class="preview-plan ${counterOf(ops().plan,opsView().scouting.style)>0?'good':counterOf(ops().plan,opsView().scouting.style)<0?'bad':''}" data-goto="ops"><span>우리 전략 <b>${esc(opsView().plans[ops().plan].name)}</b></span><em>${counterText(counterOf(ops().plan,opsView().scouting.style))}</em></button>`:''}${startButton()}</div></div><div class="section-head"><div><h2>선발 로스터 <span class="muted">/ 05</span></h2><span class="eyebrow">YOUR STARTING FIVE</span></div><small>챔피언을 선택하고 나만의 조합을 완성하세요</small></div><div class="roster">${roles.map(r=>playerCard(cards[state.roster[r]],{draft:true})).join('')}</div><div class="bottom-grid"><div class="panel scout-panel"><div class="scout-art">?</div><div class="scout-content"><div class="eyebrow">SCOUTING ROOM</div><h3>다음 에이스를 만나보세요</h3><p>실제 출전 기록이 있는 선수만 영입합니다.<br>현금 결제 없이, 경기 보상으로 모으는 컬렉션.</p><div class="scout-actions"><select id="scout-role" aria-label="영입 포지션"><option value="any">전체 · 150 CR</option>${roles.map(r=>`<option value="${r}">${roleKo[r]} · 200 CR</option>`).join('')}</select><button class="primary" data-pull ${activeMatch()||state.banpick?'disabled':''}>선수 영입 <span>↗</span></button></div></div></div><div class="panel"><span class="eyebrow">CLUB OVERVIEW</span><div class="mini-stats"><b>${record.wins} — ${record.losses}<small>이번 시즌 승 · 패</small></b><b>${state.owned.length}<small>보유 선수 카드</small></b><b>${state.trophies}<small>우승 트로피</small></b></div><div class="hint">선택 이벤트가 발생하면 경기가 멈춥니다.<br>위험을 감수할지, 다음 기회를 만들지 결정하세요.</div></div></div>${state.last_pull?`<div class="notice" style="margin-top:18px">최근 영입: ${esc(cards[state.last_pull.id].name)} · ${cards[state.last_pull.id].year} · ${esc(cards[state.last_pull.id].team)} ${state.last_pull.duplicate?'(중복 · 90 CR 환급)':''} <button class="ghost" data-goto="collection">컬렉션에서 확인 →</button></div>`:''}`;
  $('#home .hero').insertAdjacentHTML('afterend',`<div class="club-pulse"><span><i class="status-dot"></i> SEASON ${String(state.season_number).padStart(2,'0')}</span><b>${record.wins}승 ${record.losses}패</b><span>${state.owned.length}명의 선수</span><span>${state.trophies}개의 트로피</span><button class="ghost" data-goto="season">시즌 기록 →</button></div>${seasonResultMarkup()}${opsStrip()}`);$('#home').insertAdjacentHTML('beforeend',loadoutPanel()+campaignOverview());
}
function speedControls(){return `<div class="speed-controls" role="group" aria-label="경기 배속">${[1,3,6,12,30,60].map(n=>`<button class="ghost ${speed===n?'selected':''}" data-speed="${n}" aria-pressed="${speed===n}">${n}×</button>`).join('')}</div>`;}
function loadoutPanel(){
  if(!state.summoner_catalog)return '';
  return `<section class="loadout-panel"><div class="section-head"><div><span class="eyebrow">PREPARE YOUR EDGE</span><h2>소환사 주문 준비</h2></div><small>주문 2개 · 경기 시간 기준 재충전</small></div><div class="loadout-grid">${roles.map(r=>`<div><b>${roleKo[r]}</b>${(state.summoner_loadouts?.[r]??[]).map((key,i)=>`<label>${image(state.summoner_catalog[key].icon,state.summoner_catalog[key].name)}<select aria-label="${roleKo[r]} ${i+1}번 소환사 주문" data-loadout="${r}" data-slot="${i}" ${activeMatch()?'disabled':''}>${Object.values(state.summoner_catalog).filter(x=>r==='jng'||x.id!=='smite').map(x=>`<option value="${x.id}" ${x.id===key?'selected':''}>${x.name} · ${x.cooldown}초</option>`).join('')}</select></label>`).join('')}</div>`).join('')}</div></section>`;
}
function draftTeam(d,side){
  return `<section class="draft-team side-${side}"><span class="eyebrow">${side?'SECOND PICK':'FIRST PICK'}</span><h2>${side?esc(d.opponent):'NEXUS CLUB'}</h2><div class="draft-roster">${roles.map(r=>{const cid=d.picks[side][r];return `<div class="draft-slot ${!side&&r===(draftRole??d.role)&&d.phase==='pick'?'on-clock':''}"><span class="role-badge">${r.toUpperCase()}</span>${cid?image(champs.champions[cid].portrait,champs.champions[cid].name):'<span class="empty-portrait">＋</span>'}<div><b>${cid?esc(champs.champions[cid].name):'선택 대기'}</b><small>${!side?esc(cards[state.roster[r]].name):roleKo[r]}</small></div></div>`;}).join('')}</div><div class="ban-label">BANNED CHAMPIONS <span>${d.bans[side].length} / ${d.format?5:3}</span></div><div class="ban-slots">${Array.from({length:d.format?5:3},(_,i)=>{const cid=d.bans[side][i];return `<span title="${cid?esc(champs.champions[cid].name):'밴 대기'}">${cid?image(champs.champions[cid].portrait,champs.champions[cid].name):'—'}</span>`;}).join('')}</div></section>`;
}
function draftRoom(){
  const d=state.banpick;
  if(!d){$('#draft-room').innerHTML=`<div class="page-heading"><div><span class="eyebrow">THE DRAFT</span><h1>승부의 첫 번째 수.</h1><p class="muted">3밴 · 3픽 → 2밴 · 2픽, 조합을 완성하세요.</p></div></div><div class="empty">${startButton()}</div>`;return;}
  if(!draftRole||d.picks[0][draftRole])draftRole=d.role;
  const role=draftRole,player=cards[state.roster[role]],focus=$('#draft-search')===document.activeElement,selection=$('#draft-search')?.selectionStart;
  const unavailable=new Set([...d.bans.flat(),...Object.values(d.picks[0]),...Object.values(d.picks[1])]);
  const choices=Object.values(champs.champions).filter(c=>c.name.toLowerCase().includes(draftSearch.toLowerCase())||c.id.toLowerCase().includes(draftSearch.toLowerCase())).sort((a,b)=>d.phase==='pick'?mastery(player,b.id)-mastery(player,a.id)||a.name.localeCompare(b.name,'ko'):a.name.localeCompare(b.name,'ko'));
  const stage=d.phase==='ready'?4:((d.round??1)-1)*2+(d.phase==='pick'?1:0);
  $('#draft-room').innerHTML=`<div class="page-heading"><div><span class="eyebrow">TOURNAMENT DRAFT / MATCHDAY ${Math.min(state.season.round+1,5)}</span><h1>${d.phase==='ready'?'우리의 조합, 완성.':d.phase==='ban'?'상대의 가능성을 지우세요.':'승리의 조각을 선택하세요.'}</h1></div><span class="outline-tag">${d.phase==='ready'?'READY TO PLAY':`${d.round??1}라운드 · 우리 팀 ${d.phase==='ban'?'밴':'픽'}`}</span></div><div class="draft-stages">${['01 / 3 BANS','02 / 3 PICKS','03 / 2 BANS','04 / 2 PICKS'].map((t,i)=>`<div class="${i===stage?'active':i<stage?'done':''}"><i>${i<stage?'✓':String(i+1).padStart(2,'0')}</i><span>${t}</span><small>${i===0?'선픽 팀부터 교대':i===1?'A → BB → AA → B':i===2?'후픽 팀부터 교대':'B → AA → B'}</small></div>`).join('')}</div><div class="draft-layout">${draftTeam(d,0)}<section class="draft-pool">${d.phase==='ready'?`<div class="draft-ready"><div class="ready-emblem">N</div><span class="eyebrow">ALL SYSTEMS READY</span><h2>이제, 전장으로.</h2><p>준비한 조합과 전술로<br>다음 승리를 만들어보세요.</p><button class="primary full" data-action="start">경기 시작 <span>→</span></button></div>`:`<div class="pool-tools"><div class="role-tabs" aria-label="먼저 픽할 포지션">${roles.map(r=>`<button data-draft-role="${r}" class="${r===role?'selected':''}" ${d.picks[0][r]||d.phase==='ban'?'disabled':''}>${r.toUpperCase()}</button>`).join('')}</div><input id="draft-search" placeholder="챔피언 검색…" aria-label="밴픽 챔피언 검색" value="${esc(draftSearch)}"></div><div class="pool-caption"><b>${d.phase==='pick'?`${esc(player.name)} · ${roleKo[role]}`:'BAN PHASE'}</b><span>${d.phase==='pick'?'숙련도 높은 순':'선택 즉시 밴 확정'} · ${choices.length} champions</span></div>${ops()?.meta?`<div class="patch-caption">PATCH ${esc(ops().meta.patch)} · <b class="buff">▲ 상향</b> <b class="nerf">▼ 하향</b> <b class="tag">◆ ${esc(opsView().meta_tags[ops().meta.tag])} 메타</b> · 양 팀 동일 적용</div>`:''}<div class="draft-champions">${choices.map(c=>`<button data-draft-champion="${c.id}" ${unavailable.has(c.id)?'disabled':''} title="${esc(c.name)} ${d.phase==='pick'?'선택':'금지'}">${image(c.portrait,c.name)}<strong>${esc(c.name)}</strong><small>${unavailable.has(c.id)?'LOCKED':d.phase==='pick'?`숙련 ${mastery(player,c.id)}`:'BAN'}</small>${metaBadge(c.id)}</button>`).join('')||'<div class="empty">검색 결과가 없습니다.</div>'}</div>`}</section>${draftTeam(d,1)}</div>${d.phase==='ready'?loadoutPanel():''}<p class="evidence">A = 우리 선픽 팀 · B = 상대 후픽 팀 / 각 팀 5밴·5픽 / 이 게임은 블루 선픽 고정 대회 드래프트를 사용합니다.</p>`;
  if(focus){$('#draft-search')?.focus();$('#draft-search')?.setSelectionRange(selection,selection);}
}
function targetControls(m){return m.progression_rules?`<div class="target-controls"><span>교전 타깃</span><button class="ghost ${m.target_focus==='front'?'selected':''}" data-target-focus="front" aria-pressed="${m.target_focus==='front'}" ${m.winner!==null?'disabled':''}>앞라인부터</button><button class="ghost ${m.target_focus==='rear'?'selected':''}" data-target-focus="rear" aria-pressed="${m.target_focus==='rear'}" ${m.winner!==null?'disabled':''}>뒷라인 압박</button><small>상대는 최고 딜러 우선 · 후열 접근은 전열/이동기/시야로 판정</small></div>`:'';}
function streakMarkup(u){const n=u.kill_streak??0;if(n<2)return '';const tier=n>=7?'legend':n>=5?'unstoppable':n>=3?'rampage':'double';return `<span class="streak ${tier}">${n>=7?'전설':n>=5?'막을 수 없는':n>=3?'연속 처치':'상승세'} · ${n}연속 킬</span>`;}
function awardsMarkup(m){const p=m.player_of_match;if(!p)return '';return `<section class="potm-panel"><span class="eyebrow">PLAYER OF THE MATCH</span><div>${image(champs.champions[p.champion].portrait,champs.champions[p.champion].name)}<div><h2>${esc(p.name)}</h2><p>${p.side?'상대':'우리'} ${roleKo[p.role]} · ${esc(champs.champions[p.champion].name)}<br>${p.kills} / ${p.deaths} / ${p.assists} · 최고 ${p.peak_streak}연속 킬</p></div></div><small>평점 ${p.score} · 피해 ${num(p.damage)}%p · 아군 구조 ${p.saves}회<br>킬·도움·사망·피해·구조·최고 연속 킬·승리 보너스를 합산합니다.</small></section>`;}
function highlightsMarkup(m){if(!m.highlights?.length)return '';return `<section class="panel highlights-panel"><span class="eyebrow">MATCH HIGHLIGHTS</span><h2>승부의 순간들</h2><details ${m.winner!==null?'open':''}><summary>하이라이트 ${m.highlights.length}개 보기</summary><div class="highlight-feed">${[...m.highlights].reverse().map(h=>`<article><time>${clock(h.time)}</time><div><b>${esc(h.title)}</b><p>${esc(h.detail)}</p></div></article>`).join('')}</div></details></section>`;}
function matchPopup(){
  const m=state.match,dialog=$('#match-dialog'),report=m?.reports?.[0],event=m?.event;
  if(!report&&!event){if(dialog.open)dialog.close();summonerSelections.clear();return;}
  if(autoCoach){if(dialog.open)dialog.close();return;}
  const focused=document.activeElement,focusKey=focused?.dataset?.choiceSpell;
  let body;
  if(report){const f=report.fight;body=`<div class="spotlight-top"><span class="eyebrow">MATCH SPOTLIGHT</span><time>${clock(report.time)}</time></div><h2 id="match-dialog-title">${esc(report.title)}</h2><p class="outcome-result">${esc(report.detail)}</p>${f?`<div class="fight-participants">${f.participants.map((t,i)=>`<div class="side-${i}"><small>${i?'상대 팀':'우리 팀'}</small>${t.map(n=>`<b>${esc(n)}</b>`).join('')}</div>`).join('')}</div><details class="combo-report"><summary>콤보 흐름과 실제 피해 보기</summary><div class="cast-feed">${f.casts.map(c=>`<div class="cast-row">${c.skill_icon?image(c.skill_icon,c.skill_name):''}<div><small>${esc(c.combo??'공격')} ${c.combo_step?`· ${c.combo_step}단계`:''}</small><b>${esc(c.caster_name??c.caster)} · ${esc(c.skill_name??'위치 확보')}</b><p>${c.targets?.length?c.targets.map(t=>`${esc(t.name)} −${t.damage}%p`).join(' / '):'위치 확보 또는 회피'}${c.aoe&&c.hits>1?` · ${c.hits}명 적중`:''}</p></div></div>`).join('')}</div></details>`:''}<button class="primary full" data-ack-report="${report.id}">${m.reports.length>1?'다음 교전 보고':'확인 · 경기 계속'} →</button>`;}
  else{body=`<div class="spotlight-top"><span class="eyebrow">YOUR CALL, COACH.</span><time>${clock(m.time)}</time></div><h2 id="match-dialog-title">${esc(event.title)}</h2><p class="event-context">${esc(event.context)}</p><p class="event-story">${esc(event.story)}</p><div class="decision-note"><span>Ⅱ 경기 일시정지</span><span>주문을 선택하면 성공률을 미리 확인할 수 있습니다.</span></div>${eventConsumables(m)}<div class="choices">${choiceCards(event)}</div><p class="decision-footnote">숫자 1–4로 선택 · 주문은 전술을 실행할 때 소모됩니다.</p>`;}
  $('#match-dialog-content').innerHTML=body;
  if(!dialog.open)dialog.showModal();
  if(focusKey)document.querySelector(`[data-choice-spell="${focusKey}"]`)?.focus({preventScroll:true});
}
const relicKind={team:'팀 버프',player:'선수 버프',mastery:'숙련도 버프',consumable:'1회 소비'};
function executeChoice(option){
  const event=state.match?.event;if(!event)return;
  const selected=summonerSelections.get(`${event.id}:${option}`),[role,summoner]=(selected??'').split(':');
  return act({type:'choose',option,...(summoner?{role,summoner}:{})},{quiet:true});
}
function synergyMarkup(groups){return groups.length?groups.map(g=>`<span class="synergy-chip"><b>${esc(g.team)} ${g.count}인</b> 전투·시야 +${g.bonus}${g.same_year?' · 동일 연도':''}</span>`).join(''):'<span class="muted">같은 원소속 팀 선수 2명부터 활성화됩니다.</span>';}
function campaignOverview(){
  const groups=[...new Map((state.lineup_preview??[]).filter(u=>u.synergy).map(u=>[u.synergy.team_id,u.synergy])).values()];
  return `<div class="campaign-overview panel"><div class="section-head"><div><span class="eyebrow">TEAM CHEMISTRY</span><h2>함께 뛰었던 동료들</h2></div><button class="secondary" data-goto="relics">유물 보관함 · ${Object.keys(state.relics??{}).length}종 ↗</button></div><div class="synergy-list">${synergyMarkup(groups)}</div><p class="hint">원소속 팀 ID 기준 · 같은 팀 2/3/4/5인에게 전투·시야 +2/+4/+6/+8, 동일 연도 +1.<br>컨디션은 경기 시작 시 양 팀 선수마다 판정합니다. 부진 −6 / 저조 −3 / 보통 0 / 좋음 +3 / 절정 +6.</p>${preparedMarkup()}${rewardMarkup()}</div>`;
}
function preparedMarkup(){return state.prepared_relics?.length?`<div class="notice">다음 경기 준비: ${state.prepared_relics.map(id=>esc(state.relic_catalog[id].name)).join(' · ')} · 다음 한 경기만 적용</div>`:'';}
function rewardMarkup(){
  const event=state.reward_event;if(!event)return '';
  return `<section class="reward-panel" aria-label="경기 후 유물 보상"><span class="eyebrow">POST-MATCH DISCOVERY</span><h3>${esc(event.title)}</h3><p>유물 하나 또는 100 CR을 선택하세요. 다음 경기 전에 받을 수 있습니다.</p><div class="reward-options">${event.relics.map(id=>{const r=state.relic_catalog[id],blocked=state.relic_availability[id];return `<button class="relic-reward" data-reward="${id}" ${blocked?'disabled':''}>${image(r.icon,r.name)}<strong>${esc(r.name)}</strong><small>${esc(blocked??r.description)}</small>${r.exclusive?`<small>동시 소유 제한 · ${esc(r.exclusive)}</small>`:''}</button>`;}).join('')}<button class="relic-reward credit-reward" data-reward="credits"><b>+100</b><strong>연구 지원금</strong><small>CR로 받기</small></button></div></section>`;
}
function growthMarkup(rows){
  if(!rows?.length)return '';
  return `<section class="growth-panel"><span class="eyebrow">PLAYER DEVELOPMENT</span><h3>이번 경기의 성장</h3><p class="hint">승패·KDA·분당 CS·아군 구조를 반영합니다. 스탯 최대 99, 숙련도 최대 100.</p><div class="growth-rows">${rows.map(r=>`<div class="growth-row"><div><b>${esc(r.name)}</b><small>${roleKo[r.role]} · ${r.kda} · 활약 ${r.score}/5</small></div><div><span>라인 +${r.stats.lane} · 전투 +${r.stats.combat}<br>시야 +${r.stats.vision} · 성장 +${r.stats.farm}</span><strong>${esc(champs.champions[r.champion].name)} 숙련 +${r.mastery} → ${r.mastery_after}</strong></div></div>`).join('')}</div></section>`;
}
function unitCampaignStatus(u){
  if(!u.condition)return '';
  const c=u.condition;
  return `<div class="unit-campaign"><span class="condition ${c.modifier>0?'good':c.modifier<0?'poor':''}">컨디션 ${esc(c.label)} · ${c.modifier>=0?'+':''}${c.modifier}${c.rolled!==c.modifier?' (유물 보정)':''}</span>${u.synergy?`<small>${esc(u.synergy.team)} ${u.synergy.count}인 · 전투/시야 +${u.synergy.bonus}</small>`:''}${u.relic_effects?.length?`<small>유물: ${u.relic_effects.map(id=>esc(state.relic_catalog[id].name)).join(' · ')}</small>`:''}</div>`;
}
function cardDevelopment(c){
  const p=state.progression?.[c.id],u=state.lineup_preview?.find(u=>u.card_id===c.id);
  return `${p?`<div class="card-development">누적 성장 · ${p.games}경기 / ${p.wins}승<br>라인 +${p.stats.lane} · 전투 +${p.stats.combat}<br>시야 +${p.stats.vision} · 성장 +${p.stats.farm}</div>`:''}${u?`<div class="card-development">편성 효과 포함 OVR ${u.overall} · 숙련 ${u.mastery}${u.synergy?`<br>${esc(u.synergy.team)} ${u.synergy.count}인 시너지`:''}${u.relic_effects.length?`<br>적용 유물 ${u.relic_effects.length}종`:''}<br><small>경기 컨디션은 시작 시 판정</small></div>`:''}`;
}
function relics(){
  if(!state.starter.finished){$('#relics').innerHTML=`<div class="empty"><h2>구단 창단 후 유물이 열립니다.</h2>${startButton()}</div>`;return;}
  const locked=activeMatch(),catalog=state.relic_catalog;
  $('#relics').innerHTML=`<div class="page-heading"><div><span class="eyebrow">THE RELIC VAULT</span><h1>승리의 또 다른 조각.</h1><p class="muted">경기 후 발견하거나 CR로 구매하세요.<br>LoL 아이템 이름과 공식 아이콘을 사용하는 Nexus Archive 전용 효과입니다.</p></div><span class="pill">${num(state.coins)} CR</span></div>${rewardMarkup()}${preparedMarkup()}<div class="section-head"><h2>보유 유물</h2><small>지정 효과는 배정된 선수가 출전할 때 적용</small></div><div class="relic-grid">${Object.entries(state.relics).map(([id,item])=>{
    const r=catalog[id],eventReady=locked&&state.match.progression_rules&&state.match.event&&!state.match.event.used_relics.includes(id);
    const canUse=r.timing==='event'?eventReady:!locked&&!state.prepared_relics.includes(id);
    return `<article class="relic-card owned"><div class="relic-title">${image(r.icon,r.name)}<div><small>${relicKind[r.kind]} · ${item.count}개</small><h3>${esc(r.name)}</h3></div></div><p>${esc(r.description)}</p>${['player','mastery'].includes(r.kind)?`<label>적용 선수<select data-assign-relic="${id}" aria-label="${esc(r.name)} 적용 선수" ${locked?'disabled':''}>${state.owned.map(cid=>{const c=cards[cid];return `<option value="${cid}" ${item.target===cid?'selected':''}>${c.year} ${esc(c.name)} · ${roleKo[c.role]}${state.roster[c.role]===cid?' (선발)':' (후보)'}</option>`;}).join('')}</select></label>`:''}${r.kind==='consumable'?`<button class="secondary" data-use-relic="${id}" ${canUse?'':'disabled'}>${r.timing==='event'?'현재 선택에 사용':'다음 경기 준비'}</button>`:'<span class="passive-label">상시 적용</span>'}</article>`;
  }).join('')||'<div class="empty">아직 보유한 유물이 없습니다.<br>상점에서 첫 유물을 선택해보세요.</div>'}</div><div class="section-head"><h2>유물 상점</h2><small>소비성 유물은 종류별 최대 3개</small></div><div class="relic-grid">${Object.values(catalog).map(r=>{const reason=state.relic_availability[r.id];return `<article class="relic-card"><div class="relic-title">${image(r.icon,r.name)}<div><small>${relicKind[r.kind]}</small><h3>${esc(r.name)}</h3></div></div><p>${esc(r.description)}</p>${r.exclusive?`<p class="exclusive-label">동시 소유 제한 그룹: ${esc(r.exclusive)}</p>`:''}<button class="primary" data-buy-relic="${r.id}" ${locked||reason||state.coins<r.price?'disabled':''}>${r.price} CR · 구매</button><small class="purchase-note">${esc(reason??(locked?'경기 종료 후 구매 가능':state.coins<r.price?'크레딧 부족':['player','mastery'].includes(r.kind)?'획득 시 미드에 배정 · 자유롭게 변경 가능':''))}</small></article>`;}).join('')}</div><p class="evidence">Riot Data Dragon 16.20.1 · ko_KR · <a href="https://developer.riotgames.com/docs/lol#data-dragon" target="_blank" rel="noopener">공식 데이터 출처 ↗</a></p>`;
}
function eventConsumables(m){
  if(!m.event||!m.progression_rules)return '';
  const count=state.relics['2055']?.count??0,used=m.event.used_relics.includes('2055');
  return `<div class="event-relics"><span>유물 성공률 보정 +${Math.round(m.event.relic_bonus*100)}%p · 최대 98%</span><button class="secondary" data-use-relic="2055" ${count&&!used?'':'disabled'}>${image(state.relic_catalog['2055'].icon,'제어 와드')}제어 와드 ${used?'사용 완료':`사용 (${count})`}</button></div>`;
}
function summonerIcons(u,m){
  return `<div class="summoner-pair">${Object.entries(u.summoners??{}).map(([key,v])=>{const spell=state.summoner_catalog[key],remaining=Math.max(0,v.ready_at-m.time,v.charges?0:v.recharge_at-m.time);return `<span class="summoner-icon ${remaining?'cooling':'ready'}" title="${spell.name} · ${remaining?remaining+'초 후 사용 가능':'사용 가능'}${key==='smite'?' · '+v.charges+'충전':''}">${image(spell.icon,spell.name)}${remaining?`<b>${remaining}</b>`:'<i></i>'}${key==='smite'?`<small>${v.charges}</small>`:''}</span>`;}).join('')}</div>`;
}
function choiceCards(event){
  return event.options.map((o,i)=>{const offers=o.summoners??[],id=`${event.id}:${o.id}`,selection=summonerSelections.get(id),selected=offers.find(x=>`${x.role}:${x.id}`===selection);return `<div class="decision-card"><button class="choice" data-choice="${o.id}"><span class="chance">${Math.round((selected?.chance??o.chance)*100)}%${selected?`<small>기본 ${Math.round(o.chance*100)}%</small>`:''}</span><strong><kbd>${i+1}</kbd> ${esc(o.label)}</strong><small>${esc(o.detail)}</small></button>${offers.length?`<label class="spell-choice"><span>${selected?image(selected.icon,selected.name):'<span class="spell-plus">＋</span>'} 주문으로 지원</span><select aria-label="${esc(o.label)}에 사용할 주문" data-choice-spell="${id}"><option value="">주문 아끼기</option>${offers.map(x=>`<option value="${x.role}:${x.id}" ${selected===x?'selected':''}>${x.player} · ${x.name} → ${Math.round(x.chance*100)}% (${x.cooldown}초)</option>`).join('')}</select></label>`:''}</div>`;}).join('');
}
function mapSvg(m){
  const spatial=m.rules==='spatial-v5';
  const tokens=m.teams.flatMap((team,side)=>team.map(u=>{const pos=u.pos??[side?75:25,25+roles.indexOf(u.role)*12],id=`${side}:${u.role}`,dead=u.status==='dead',casts=u.recent_casts??[];return `<button class="map-unit side-${side} ${dead?'dead':''} ${inspectedUnit===id?'inspected':''}" data-inspect="${id}" style="left:${pos[0]}%;top:${pos[1]}%" aria-label="${esc(u.name)} ${esc(champs.champions[u.champion].name)} ${roleKo[u.role]} 체력 ${Math.round(u.hp??100)}%" title="${esc(u.name)} · ${roleKo[u.role]} · ${esc(u.intent??u.location)}"><span class="map-casts">${casts.slice(-3).map(c=>`<span title="${esc(c.name)}">${image(c.icon,c.name)}<small>${esc(c.key)}</small></span>`).join('')}</span>${image(champs.champions[u.champion].portrait,champs.champions[u.champion].name)}<i class="map-hp"><b style="width:${u.hp??100}%"></b></i><small class="map-role">${u.role.toUpperCase()}</small></button>`;})).join('');
  const towerPaths={top:[[11,70],[11,44],[12,25]],mid:[[25,75],[33,67],[40,60]],bot:[[30,89],[56,89],[75,88]]};
  let towers='';for(const side of [0,1])for(const lane of ['top','mid','bot'])towerPaths[lane].forEach(([x,y],i)=>{if(side){x=100-x;y=100-y;}const alive=i<m.towers[side][lane];towers+=`<path d="M${x} ${y-1.5}l1.5 1.5-1.5 1.5-1.5-1.5Z" fill="${side?'#f27f8c':'#63dcd3'}" opacity="${alive?1:.18}"/>`;});
  const routes=spatial?m.teams.flatMap(t=>t.filter(u=>u.moving&&u.status==='active').map(u=>`<path class="route-line side-${u.side}" d="M${u.pos.join(' ')} ${[...(u.route??[]),u.destination].map(p=>'L'+p.join(' ')).join(' ')}"/>`)).join(''):'';
  return `<div class="rift-map"><svg viewBox="0 0 100 100" aria-hidden="true"><defs><pattern id="rift-grid" width="5" height="5" patternUnits="userSpaceOnUse"><path d="M5 0H0V5" fill="none" stroke="#8ad3c8" stroke-width=".08" opacity=".15"/></pattern><radialGradient id="terrain"><stop stop-color="#183b37"/><stop offset="1" stop-color="#0b211f"/></radialGradient></defs><rect width="100" height="100" rx="4" fill="url(#terrain)"/><rect width="100" height="100" fill="url(#rift-grid)"/><path d="M12 76V22Q12 12 22 12H76M24 88H78Q88 88 88 78V24M17 83 83 17" stroke="#658575" stroke-width="4" opacity=".34" fill="none"/><path d="M13 78V22Q13 13 22 13H78M22 87H78Q87 87 87 78V22M17 83 83 17" stroke="#d0bb85" stroke-width=".3" opacity=".35" fill="none"/><path d="M7 40C23 29 36 38 48 49S71 72 94 60" fill="none" stroke="#367f86" stroke-width="5" opacity=".45"/><path d="m20 25 11-5 6 8-10 9Zm-1 26 10-8 10 9-11 11ZM43 72l9-9 13 13-13 6Zm19-45 10-8 8 12-10 8Zm4 18 12-4 6 12-7 7ZM24 67l7 3-5 9-8-7Z" fill="#315344" stroke="#4a6d55" stroke-width=".4"/><path d="M11 82 18 89 11 96 4 89Z" fill="#163c43" stroke="#65d9d2" stroke-width=".5"/><path d="M89 4 96 11 89 18 82 11Z" fill="#472735" stroke="#ec8493" stroke-width=".5"/>${towers}${routes}<circle cx="35" cy="35" r="4.5" fill="#27253e" stroke="#b69be1" stroke-width=".45"/><text x="35" y="36.3" class="pit-label">${m.time>=1200?'B':'H'}</text><circle cx="66" cy="66" r="4.5" fill="#3a3321" stroke="#c9ae74" stroke-width=".45"/><text x="66" y="67.3" class="pit-label">D</text><text x="5" y="7" class="lane-map-label">TOP</text><text x="90" y="96" class="lane-map-label">BOT</text><text x="53" y="43" class="lane-map-label">MID</text></svg>${tokens}${m.last_encounter&&m.time-m.last_encounter.time<7&&m.last_encounter.position?`<span class="contact-ring" style="left:${m.last_encounter.position[0]}%;top:${m.last_encounter.position[1]}%"></span>`:''}<span class="map-watermark">SUMMONER'S RIFT / LIVE TACTICS</span></div>`;
}
function liveTeam(m,side){
  return `<aside class="live-team side-${side}"><div class="team-heading"><span class="team-orb">${side?'R':'N'}</span><div><small>${side?'OPPONENT':'YOUR TEAM'}</small><b>${side?esc(m.opponent_name):'NEXUS CLUB'}</b></div></div>${m.teams[side].map(u=>`<button class="live-player ${inspectedUnit===`${side}:${u.role}`?'selected':''} ${u.status!=='active'?'inactive':''}" data-inspect="${side}:${u.role}"><div class="live-player-top"><span class="live-portrait">${image(champs.champions[u.champion].portrait,champs.champions[u.champion].name)}<small>${u.level??1}</small></span><span><b>${esc(u.name)}</b><small>${roleKo[u.role]} · ${esc(champs.champions[u.champion].name)}</small></span><strong class="kda">${u.kills??0}<i> / </i>${u.deaths??0}<i> / </i>${u.assists??0}</strong></div><div class="player-hp"><i style="width:${u.hp??100}%"></i></div><div class="live-player-bottom">${summonerIcons(u,m)}<span>${u.status==='dead'?`복귀 ${Math.max(0,u.return_at-m.time)}초`:u.status==='recall'?'귀환 중':esc(u.intent??u.location)}<small>${u.cs??0} CS · ${num(u.gold??0)} G</small></span></div>${(u.kill_streak??0)>=2?`<span class="small-streak">${u.kill_streak}연속 처치</span>`:''}</button>`).join('')}</aside>`;
}
function unitInspector(m){
  const [side,role]=inspectedUnit.split(':'),u=m.teams[Number(side)].find(u=>u.role===role)??m.teams[0][0];
  const enemies=m.teams[1-Number(side)].filter(e=>e.status==='active'),near=u.pos?enemies.map(e=>Math.hypot(e.pos[0]-u.pos[0],e.pos[1]-u.pos[1])):[];
  return `<div class="unit-inspector"><div class="inspector-person">${image(champs.champions[u.champion].portrait,champs.champions[u.champion].name)}<span><b>${esc(u.name)} <small>${esc(champs.champions[u.champion].name)}</small></b><small>${esc(u.intent??u.location)} · 체력 ${Math.round(u.hp??100)}%</small></span></div><div class="inspector-metric"><small>가장 가까운 적</small><b>${near.length?Math.min(...near).toFixed(1):'—'} <small>거리</small></b></div><div class="combo-preview"><small>${esc(u.last_combo?.name??'다음 콤보 준비')}</small><div>${u.last_combo?.steps.map(c=>image(c.icon??'assets/skill-placeholder.svg',c.name)).join('<span>›</span>')??'<span class="muted">교전 시 메커니즘에 맞춰 연계</span>'}</div></div><button class="ghost" data-abilities="${u.champion}">스킬 정보 ↗</button></div>`;
}
function objectiveRibbon(m){
  return `<div class="objective-ribbon">${[['dragon','드래곤',m.next_dragon,'D',m.dragons],['herald','전령',480,'H',m.heralds],['baron','바론',m.next_baron,'B',m.barons]].map(([key,name,at,letter,score])=>`<div class="${m.objective_attempt?.kind===key?'contested':''}"><span class="objective-symbol">${letter}</span><span><b>${name}</b><small>${key==='herald'&&(!m.herald_available||m.time>=1200)?'사라짐':at>m.time?clock(at-m.time)+' 후 등장':m.objective_attempt?.kind===key?'사냥 중 · '+Math.max(0,m.objective_attempt.finish_at-m.time)+'초':'전장에 등장'}</small></span><strong>${score[0]}<i> : </i>${score[1]}</strong></div>`).join('')}</div>`;
}
function animateMap(){
  const width=$('.rift-map')?.clientWidth??0;
  document.querySelectorAll('.map-unit').forEach(el=>{const id=el.dataset.inspect,x=parseFloat(el.style.left),y=parseFloat(el.style.top),old=mapPositions.get(id);if(old&&!matchMedia('(prefers-reduced-motion: reduce)').matches&&Math.hypot(x-old.x,y-old.y)<35)el.animate([{translate:`${(old.x-x)*width/100}px ${(old.y-y)*width/100}px`},{translate:'0 0'}],{duration:850,easing:'linear'});mapPositions.set(id,{x,y});});
}
function arena(){
  const m=state.match;
  if(!m){$('#arena').innerHTML=`<div class="arena-empty"><span class="eyebrow">THE RIFT AWAITS</span><h1>당신의 첫 승부를<br>기다리고 있습니다.</h1><p>드래프트에서 다섯 챔피언을 확정하고<br>나만의 팀을 지휘하세요.</p>${startButton()}<div class="empty-grid-art">N</div></div>`;return;}
  const event=m.event,over=m.winner!==null,delta=m.gold[0]-m.gold[1],lead=Math.max(10,Math.min(90,50+delta/500));
  const filtered=[...m.log].reverse().filter(l=>feedFilter==='all'||(feedFilter==='combat'?['fight','encounter','skill','save','summoner'].includes(l.kind):['objective','decision','decision_result','roam','gank','vision'].includes(l.kind))).slice(0,45);
  const last=m.highlights?.at(-1);
  $('#arena').innerHTML=`<div class="arena-heading"><div><span class="eyebrow">MATCHDAY ${Math.min(state.season.round+1,5)} / ${phaseKo[state.season.phase]}${m.plans?` · ${esc(opsView()?.plans?.[m.plans.ours]?.name??'')} vs ${esc(opsView()?.plans?.[m.plans.theirs]?.name??'')} ${m.plans.counter>0?'▲':m.plans.counter<0?'▼':''}`:''}</span><h1>전장의 모든 순간.</h1></div><div class="arena-toolbar"><button class="secondary" data-auto ${over||event||m.reports?.length?'disabled':''}>${auto?'Ⅱ 일시정지':'▶ 경기 재개'}</button>${speedControls()}<button class="ghost coach-toggle ${autoCoach?'selected':''}" data-coach aria-pressed="${autoCoach}" ${over?'disabled':''} title="전술 선택은 성공률이 가장 높은 안을, 교전 보고서는 자동 확인합니다">AI 코치 ${autoCoach?'ON':'OFF'}</button><button class="ghost" data-step ${over||event||m.reports?.length?'disabled':''}>+1초</button></div></div><div class="broadcast-score"><div class="broadcast-team"><span class="club-monogram">N</span><div><small>BLUE SIDE</small><b>NEXUS CLUB</b><span>${num(m.gold[0])} G · ${m.dragons[0]} 드래곤</span></div><strong>${m.kills[0]}</strong></div><div class="broadcast-clock"><span class="live-label ${event||m.reports?.length?'paused':''}">${over?'FINAL':event?'DECISION':m.reports?.length?'SPOTLIGHT':auto?'● LIVE':'PAUSED'}</span><b>${clock(m.time)}</b><small>${m.time<840?'LANING PHASE':m.time<1800?'MID GAME':'LATE GAME'}</small></div><div class="broadcast-team opponent"><strong>${m.kills[1]}</strong><div><small>RED SIDE</small><b>${esc(m.opponent_name)}</b><span>${num(m.gold[1])} G · ${m.dragons[1]} 드래곤</span></div><span class="club-monogram">${esc(m.opponent_name?.[0]??'R')}</span></div></div><div class="gold-balance"><i style="width:${lead}%"></i><span>GOLD ${delta>=0?'+':''}${num(delta)}</span></div>${objectiveRibbon(m)}<div class="battle-layout">${liveTeam(m,0)}<div class="battle-center"><div class="battle-map-heading"><span><i class="status-dot"></i> LIVE BATTLEFIELD</span><small>챔피언을 선택해 전술 확인</small></div>${mapSvg(m)}<div class="map-legend"><span><i></i>우리 팀</span><span><i class="enemy-dot"></i>상대 팀</span><span>점선 · 이동 경로</span><span>초상화 위 · 사용 스킬</span></div></div>${liveTeam(m,1)}</div>${unitInspector(m)}${last?`<div class="moment-strip"><span>${clock(last.time)}</span><b>${esc(last.title)}</b><small>${esc(last.detail)}</small></div>`:''}${over?`<section class="match-result"><span class="eyebrow">NEXUS DESTROYED</span><div class="result-word ${m.winner===1?'loss':''}">${m.winner===0?'VICTORY':'DEFEAT'}</div><p>${clock(m.time)} · ${m.decisions.length}번의 선택 · ${esc(state.notice)}</p><div class="result-columns">${awardsMarkup(m)}${growthMarkup(m.growth_report)}</div>${weekMarkup(m.week_report,m.sponsor_income)}${seasonResultMarkup()}${rewardMarkup()}${startButton()}</section>`:''}<div class="command-grid"><section class="log-panel"><div class="log-heading"><span>MATCH FEED <small>실시간 중계</small></span><div class="feed-tabs">${[['all','전체'],['combat','교전'],['macro','운영']].map(([id,label])=>`<button class="${feedFilter===id?'selected':''}" data-feed="${id}">${label}</button>`).join('')}</div></div><div class="log-feed" tabindex="0" aria-label="최근 경기 중계">${filtered.map(l=>`<div class="log-line log-${esc(l.kind)}"><time>${clock(l.time)}</time>${l.skill?image(l.skill.icon,l.skill.name):'<span class="feed-dot">·</span>'}<span>${esc(l.text)}</span></div>`).join('')||'<div class="feed-empty">선수들이 담당 라인으로 향하고 있습니다.</div>'}</div></section><section class="command-panel"><span class="eyebrow">COACH’S PLAYBOOK</span><h2>다음 한 수를 준비하세요.</h2>${targetControls(m)}${event?`<div class="pending-decision"><b>${esc(event.title)}</b><p>${esc(event.context)}</p><button class="primary" data-open-decision>전술 선택 열기 →</button></div>`:`<p>위치와 시야가 기회를 만듭니다.<br>중요한 순간, 경기가 멈추고<br>감독님의 결정을 기다립니다.</p>`}<div class="command-stats"><span>우리 시야<b>${m.vision[0]}</b></span><span>상대 시야<b>${m.vision[1]}</b></span><span>위치 기반 교전<b>${m.spatial_events??'—'}</b></span></div><div class="nexus-bars"><div>우리 넥서스 · ${m.nexus[0]}<div class="bar"><i style="width:${m.nexus[0]/40}%"></i></div></div><div>상대 넥서스 · ${m.nexus[1]}<div class="bar red"><i style="width:${m.nexus[1]/40}%"></i></div></div></div></section></div>${highlightsMarkup(m)}<p class="evidence">SIMULATION / ${m.seed} · 1× = 실제 1초당 경기 1초 · 지도 거리는 시뮬레이션 단위 · 소환사 주문은 경기 시간에 따라 재충전</p>`;
  animateMap();
}
function collection(){
  const f=collectionFilter;
  let pool=catalog.cards.filter(c=>(f.owned==='all'||state.owned.includes(c.id))&&(f.role==='any'||c.role===f.role)&&(f.year==='any'||String(c.year)===f.year)&&`${c.name} ${c.team} ${c.league}`.toLowerCase().includes(f.search.toLowerCase()));
  pool.sort((a,b)=>grownCard(b).overall-grownCard(a).overall||a.name.localeCompare(b.name));
  const focus=document.activeElement?.id==='collection-search',selection=document.activeElement?.selectionStart;
  $('#collection').innerHTML=`<div class="page-heading"><div><span class="eyebrow">THE PLAYER ARCHIVE</span><h1>당신만의 드림팀.</h1><p class="muted">보유 ${state.owned.length}장 / 전체 ${num(catalog.cards.length)}장 · 연도 제한 없이 편성하세요.</p></div><button class="secondary" data-goto="home">선수 영입 →</button></div><div class="filters"><input id="collection-search" placeholder="선수, 구단, 리그 검색" aria-label="선수 검색" value="${esc(f.search)}"><select data-filter="owned" aria-label="보유 여부"><option value="owned" ${f.owned==='owned'?'selected':''}>보유 카드</option><option value="all" ${f.owned==='all'?'selected':''}>모든 카드</option></select><select data-filter="role" aria-label="포지션"><option value="any">전체 포지션</option>${roles.map(r=>`<option value="${r}" ${f.role===r?'selected':''}>${roleKo[r]}</option>`).join('')}</select><select data-filter="year" aria-label="연도"><option value="any">모든 연도</option>${catalog.coverage.years.map(y=>`<option value="${y}" ${f.year===String(y)?'selected':''}>${y}</option>`).join('')}</select></div><div class="section-head"><small>${num(pool.length)}개의 카드</small><small>능력치순 · 출전 데이터 기반</small></div><div class="collection-grid">${pool.slice(0,f.limit).map(c=>playerCard(c,{collection:true})).join('')}</div>${pool.length===0?'<div class="empty">검색 조건에 맞는 카드가 없습니다.</div>':''}${pool.length>f.limit?'<button class="secondary load-more" data-more>카드 더 보기 ↓</button>':''}<div class="hint">전체 영입은 ${num(catalog.cards.length)}개 카드 각각 동일 확률(1/${num(catalog.cards.length)})입니다. 포지션 영입도 해당 포지션 내 동일 확률입니다. 중복 카드는 90 CR로 환급합니다. 선수 능력치는 실제 선수를 평가하는 공식 지표가 아닙니다.</div>`;
  if(focus){$('#collection-search').focus();$('#collection-search').setSelectionRange(selection,selection);}
}
function season(){
  if(!state.season){$('#season').innerHTML=`<div class="empty"><h2>드림팀을 먼저 완성하세요.</h2><p>다섯 포지션 팩을 열면 시즌이 시작됩니다.</p>${startButton()}</div>`;return;}
  const s=state.season;
  $('#season').innerHTML=`<div class="page-heading"><div><span class="eyebrow">SEASON ${state.season_number} / ROAD TO THE TITLE</span><h1>${phaseKo[s.phase]}</h1><p class="muted">${esc(divisionInfo()?.name??'')} · 6개 구단 · 5경기 정규시즌 · 상위 4팀 플레이오프</p></div>${s.phase==='complete'?'<button class="primary" data-action="next_season">다음 시즌 →</button>':'<button class="secondary" data-goto="home">로스터로 돌아가기 →</button>'}</div>${s.phase==='complete'?`<div class="notice">시즌 우승: ${esc(s.teams[s.champion]?.name??'결정 중')} · 선수 컬렉션과 크레딧은 다음 시즌으로 이어집니다.</div>`:''}${seasonResultMarkup()}${ladderMarkup()}<div class="season-grid"><div class="panel"><div class="section-head"><h2>리그 테이블</h2><small>${Math.min(s.round,5)} / 5 경기</small></div><table class="standings"><thead><tr><th>순위</th><th>구단</th><th>승</th><th>패</th></tr></thead><tbody>${s.standings.map((idx,i)=>`<tr class="${idx===0?'mine':''} ${i===5&&ops()?.division>0?'danger':''}"><td>${String(i+1).padStart(2,'0')}</td><td>${esc(s.teams[idx].name)} ${idx===0?'↖':''}${s.teams[idx].style?` <span class="style-chip style-${s.teams[idx].style}">${esc(opsView().plans[s.teams[idx].style].name)}</span>`:''}</td><td>${s.teams[idx].wins}</td><td>${s.teams[idx].losses}</td></tr>`).join('')}</tbody></table><div class="hint">상위 4팀 진출. 동률이면 시즌 구단 번호순으로 결정합니다.<br>플레이오프는 3전 2선승제입니다. 결승 진출 시 승격, 정규시즌 6위는 강등됩니다.</div></div><div class="panel"><span class="eyebrow">MATCH HISTORY</span><h2 style="margin-top:10px">우리가 만든 기록</h2>${s.history.length?s.history.map(h=>`<div class="schedule-row"><span class="result ${h.won?'':'loss'}">${h.won?'W':'L'}</span><span>${esc(s.teams[h.opponent].name)}<br><small>${phaseKo[h.phase]} · +${h.reward} CR</small></span><small>${clock(h.duration)}</small></div>`).join(''):'<div class="empty">아직 경기를 치르지 않았습니다.</div>'}${['semifinal','final'].includes(s.phase)?`<div class="notice" style="margin-top:20px">현재 시리즈 ${s.series[0]} : ${s.series[1]}<br>상대 ${esc(s.teams[s.opponent].name)}</div>`:''}</div></div>`;
}
function sources(){
  $('#sources').innerHTML=`<div class="page-heading"><div><span class="eyebrow">BUILT ON REAL APPEARANCES</span><h1>기록에는 출처가 있습니다.</h1></div></div><div class="source-stats"><b>${num(catalog.coverage.cards)}<small>선수 / 연도 / 구단 / 포지션 카드</small></b><b>${num(catalog.coverage.appearances)}<small>중복 제거된 공식 출전 행</small></b><b>${Object.keys(champs.champions).length}<small>한국어 챔피언</small></b></div><div class="sources-grid"><div class="panel"><h3>Oracle's Elixir 경기 기록</h3><p>Oracle's Elixir / Tim Sevenhuysen의 ${catalog.coverage.years.join('·')} CSV 공개 보존본에서 추출했습니다. 명단에만 있는 선수는 생성하지 않으며, playerid·gameid·실제 경기 시간이 있는 출전만 사용합니다.</p><p>리그 허용 목록: ${esc(catalog.coverage.leagues.join(', '))}. 1군 ${num(catalog.coverage.tiers['1'])}장 / 2군 ${num(catalog.coverage.tiers['2'])}장. 2군은 대회 단계 기준으로 독립 팀도 포함합니다. 모든 지역·모든 연도의 완전 수록은 아닙니다.</p><a href="https://oracleselixir.com/tools/downloads" target="_blank" rel="noopener">원본 배포 안내 ↗</a><p>원본 접근 실패로 공개 CSV 보존본 사용. 원본과의 완전 일치 및 재배포 권한은 미검증입니다. 포함된 출전 행은 보존본 기준으로 검증했습니다.</p>${catalog.provenance.sources.map(s=>`<p><a href="${esc(s.snapshot_url)}" target="_blank" rel="noopener">${esc(s.filename)} 보존본 ↗</a><br><span class="evidence">SHA-256 ${esc(s.sha256.slice(0,20))}…</span></p>`).join('')}</div><div class="panel"><h3>챔피언 & 스킬</h3><p>Riot Data Dragon ${esc(champs.version)} · ko_KR<br>패시브/QWER 한국어 명칭·초상화·스킬 아이콘 주소를 수집합니다. 네트워크 오류 시 아이콘 대체 이미지를 표시합니다.</p><p>숙련도는 해당 카드의 공식 챔피언 출전 횟수와 승률로 추정합니다. 기본 스킬 태그는 한국어 설명에서 분류하며, 형태별 예외는 공식 상세 설명과 대조했습니다. ${champs.variant_audit?.reviewed_champions??173}종을 점검하고 ${champs.variant_audit?.families.length??0}종의 변신·무기·세부 주문·재시전 계열을 분리했습니다. 형태 전환 시간과 자원은 이 게임의 추상화이며 실제 LoL 수치와 다릅니다.</p><a href="https://developer.riotgames.com/docs/lol#data-dragon" target="_blank" rel="noopener">Data Dragon 문서 ↗</a><div class="warning">Riot 정책에 게임에서의 IP 사용 제한이 있어, 공개 배포 전 별도 권한 검토가 필요합니다. 비상업·무료라는 이유만으로 사용 권한이 확보되지는 않습니다.</div></div><div class="panel"><h3>연도별 사진 & 로고</h3><p>사진과 로고는 경기 데이터와 별도로 권한을 관리합니다. 출처·권리자·이용 근거·검증 날짜·선수/팀/연도가 확인된 로컬 파일만 적용합니다. 현재는 직접 제작한 대체 프로필·방패를 사용합니다.</p><p>검증되지 않은 사진을 그해 공식 유니폼 사진으로 표시하지 않습니다.</p></div><div class="panel"><h3>나의 저장 기록</h3><p>계정·서버·멀티플레이가 없습니다. 현재 브라우저에 저장되고, JSON 파일로 내보내거나 불러올 수 있습니다. 시드와 선택 기록이 같으면 결과도 같습니다.</p><p>시드: <b>${esc(state.seed)}</b><br>데이터 버전: ${esc(state.dataset)}<br>저장 상태: ${storageBlocked?'자동 저장 중지 · 파일로 내보내 주세요':'브라우저 자동 저장'}<br>기록 동작 ${state.save_actions} / 12,000</p><div class="settings"><button class="ghost" data-new>새 게임 / 시드 변경</button>${storedRecovery?'<button class="secondary" data-recovery>이전 세이브 복구 파일 받기</button>':''}</div></div></div>`;
}
// ---- Engine 6 team operations: rendering only; every rule lives in management.py ----
const statKo={lane:'라인전',combat:'전투',vision:'시야',farm:'성장'};
const focusIcon={lane:'⚔',combat:'✸',vision:'◉',farm:'◆',champion:'★',rest:'☾'};
let autoCoach=false;
const ops=()=>state?.management;
const opsView=()=>state?.ops_view;
function traitChip(t){const info=opsView()?.traits_catalog?.[t];return info?`<span class="trait-chip trait-${t}" title="${esc(info.desc)}">${esc(info.name)}</span>`:'';}
function traitChips(cid,list){return (list??opsView()?.card_traits?.[cid]??[]).map(traitChip).join('');}
function staminaOf(cid){return ops()?.stamina?.[cid]??100;}
function staminaBar(cid,{compact=false}={}){const v=Math.round(staminaOf(cid)),cls=v<25?'low':v<50?'warn':'';return `<div class="stamina ${cls} ${compact?'compact':''}" title="체력 ${v} / 100 · 25 미만이면 탈진(모든 능력치 −4)"><i style="width:${v}%"></i><span>${compact?'':'체력 '}${v}</span></div>`;}
function shiftLabel(shift){if(shift===undefined)return '';return shift>=8?'<span class="shift up2">컨디션 기대 ▲▲</span>':shift>=3?'<span class="shift up">컨디션 기대 ▲</span>':shift<=-8?'<span class="shift down2">컨디션 위험 ▼▼</span>':shift<=-3?'<span class="shift down">컨디션 위험 ▼</span>':'<span class="shift">컨디션 안정</span>';}
function metaOf(cid){const m=ops()?.meta;if(!m)return null;if(m.buffs.includes(cid))return 'buff';if(m.nerfs.includes(cid))return 'nerf';return champs.champions[cid]?.tags?.includes(m.tag)?'tag':null;}
function metaBadge(cid){const k=metaOf(cid);return k==='buff'?'<span class="meta-badge buff" title="이번 패치 버프 · 전투 +3 · 라인전 +2">▲</span>':k==='nerf'?'<span class="meta-badge nerf" title="이번 패치 너프 · 전투 −3 · 라인전 −2">▼</span>':k==='tag'?`<span class="meta-badge tag" title="메타 계열 · 전투 +2">◆</span>`:'';}
function champMini(cid,label){const c=champs.champions[cid];if(!c)return '';return `<span class="champ-mini" title="${esc(c.name)}${label?` · ${esc(label)}`:''}">${image(c.portrait,c.name)}${metaBadge(cid)}</span>`;}
function counterOf(plan,enemy){const plans=opsView()?.plans;if(!plans||!enemy)return 0;if(plans[plan]?.beats===enemy)return 1;if(plans[enemy]?.beats===plan)return -1;return 0;}
function counterText(c){return c>0?'▲ 상성 우위 · 전 능력치 +2':c<0?'▼ 상대가 상성 우위':'상성 없음';}
function divisionInfo(){const v=opsView();return v?v.divisions[ops().division]:null;}
function divisionBadge(){const d=divisionInfo();return d?`<span class="division-badge div-${d.id}"><i>${esc(d.short)}</i><b>${esc(d.name)}</b></span>`:'';}
function opsTodos(){
  const o=ops(),v=opsView();if(!o||!v||!state.season||state.season.phase==='complete')return [];
  const sc=v.scouting,todos=[];
  if(o.sponsor)todos.push({done:true,text:`스폰서 · ${v.sponsor_catalog[o.sponsor].name}`});else if(o.sponsor_offers?.length)todos.push({done:false,text:'스폰서 계약을 선택하세요 (시즌 1회)'});
  if(sc){const c=counterOf(o.plan,sc.style);todos.push(c>0?{done:true,text:`전략 상성 우위 · ${v.plans[o.plan].name}`}:c<0?{done:false,text:`현재 전략이 ${v.plans[sc.style].name}에 불리합니다`}:{done:o.plan!=='balanced',text:o.plan==='balanced'?`상대는 ${v.plans[sc.style].name} · 맞춤 전략을 고려하세요`:`전략 · ${v.plans[o.plan].name}`});}
  const tired=roles.filter(r=>staminaOf(state.roster[r])<35&&(o.training[r]?.focus??'lane')!=='rest');
  todos.push(tired.length?{done:false,text:`체력 35 미만 ${tired.map(r=>roleKo[r]).join('·')} · 휴식을 고려하세요`}:{done:true,text:'선수단 체력 양호'});
  return todos;
}
function opsStrip(){
  const o=ops();if(!o||!state.season)return '';
  const todos=opsTodos(),open=todos.filter(t=>!t.done).length;
  return `<section class="ops-strip panel"><div class="ops-strip-head"><div><span class="eyebrow">THIS WEEK</span><h3>이번 주 운영 ${open?`<span class="todo-count">${open}</span>`:'<span class="todo-ok">✓</span>'}</h3></div>${divisionBadge()}<button class="secondary" data-goto="ops">운영 센터 →</button></div><div class="ops-strip-body"><div class="ops-strip-roster">${roles.map(r=>{const cid=state.roster[r],f=o.training[r]?.focus??'lane';return `<div><small>${roleKo[r]}</small><b>${esc(cards[cid].name)}</b>${staminaBar(cid,{compact:true})}<span class="focus-tag">${focusIcon[f]} ${esc(opsView().training_catalog[f].name)}</span></div>`;}).join('')}</div><ul class="todo-list">${todos.map(t=>`<li class="${t.done?'done':''}">${t.done?'✓':'!'} ${esc(t.text)}</li>`).join('')}</ul></div></section>`;
}
function seasonResultMarkup(){
  const r=ops()?.season_result;if(!r||state.season?.phase!=='complete')return '';
  const d=opsView().divisions;
  const title=r.outcome==='promote'?`${d[r.to].name} 승격!`:r.outcome==='relegate'?`${d[r.to].name}로 강등`:`${d[r.to].name} 잔류`;
  return `<section class="season-result ${r.outcome}"><span class="eyebrow">SEASON ${r.season} RESULT</span><h2>${esc(title)}</h2><p>정규시즌 ${r.standing}위${r.champion?' · 우승':r.final?' · 준우승':''}${r.sponsor_bonus?` · 스폰서 보너스 +${num(r.sponsor_bonus)} CR`:''}</p><small>결승 진출 시 승격 · 정규시즌 6위는 강등 · 상위 리그일수록 상대가 강하고 보상이 큽니다.</small></section>`;
}
function weekMarkup(rows,income){
  if(!rows?.length&&!income)return '';
  const cat=opsView()?.training_catalog??{};
  return `<section class="week-panel"><span class="eyebrow">WEEKLY TRAINING</span><h3>이번 주 훈련 결과</h3>${income?`<p class="sponsor-income">스폰서 수입 +${num(income)} CR</p>`:''}<div class="week-rows">${(rows??[]).map(r=>`<div class="week-row"><b>${focusIcon[r.focus]??''} ${esc(r.name)}</b><span>${esc(cat[r.focus]?.name??r.focus)}${r.stat?` · ${statKo[r.stat]} +${r.gain}`:r.champion?` · ${esc(champs.champions[r.champion]?.name??r.champion)} 숙련 +${r.gain}`:''}</span><small class="${r.stamina_after<25?'low':''}">체력 ${Math.round(r.stamina_before)} → ${Math.round(r.stamina_after)}</small></div>`).join('')}</div></section>`;
}
function forecastStamina(cid,focus){
  const v=opsView(),o=ops(),t=v.training_catalog[focus],traits=v.card_traits[cid]??[];
  const sponsor=o.sponsor?v.sponsor_catalog[o.sponsor]:{};
  const mult=Math.max(0,1-traits.reduce((a,k)=>a+(v.traits_catalog[k].fatigue??0),0)-(sponsor.fatigue??0));
  const cost=t.fatigue>0?t.fatigue*mult:t.fatigue;
  return Math.round(Math.max(0,Math.min(100,staminaOf(cid)-8*mult-cost+5+(sponsor.stamina??0))));
}
function trainingRow(r){
  const o=ops(),v=opsView(),cid=state.roster[r],c=grownCard(cards[cid]),plan=o.training[r]??{focus:'lane'},photo=media.assets[cid];
  const pool=masteries(cards[cid]).slice(0,14).map(m=>m.id),current=state.draft[r];
  if(current&&!pool.includes(current))pool.unshift(current);
  if(plan.champion&&!pool.includes(plan.champion))pool.unshift(plan.champion);
  const after=forecastStamina(cid,plan.focus);
  return `<div class="train-row"><div class="train-player">${image(photo?.display??'assets/player-placeholder.svg',c.name,'train-photo')}<div><b>${esc(c.name)}</b><small>${roleKo[r]} · OVR ${c.overall}</small><div class="trait-line">${traitChips(cid)}</div></div></div><div class="train-stamina">${staminaBar(cid)}${shiftLabel(v.condition_shift[cid])}</div><div class="train-focus"><div class="focus-options" role="group" aria-label="${esc(c.name)} 훈련">${Object.entries(v.training_catalog).map(([k,t])=>`<button class="focus-btn ${plan.focus===k?'selected':''} focus-${k}" data-train-role="${r}" data-train-focus="${k}" title="${esc(t.desc)}" aria-pressed="${plan.focus===k}">${focusIcon[k]} ${esc(t.name)}</button>`).join('')}</div>${plan.focus==='champion'?`<label class="practice-pick">연습 챔피언 <select data-train-champion="${r}">${pool.map(id=>`<option value="${id}" ${id===plan.champion?'selected':''}>${esc(champs.champions[id].name)} · 숙련 ${mastery(cards[cid],id)}</option>`).join('')}</select></label>`:''}</div><div class="train-forecast"><small>다음 경기 후</small><b class="${after<25?'low':after<50?'warn':''}">체력 ≈ ${after}</b></div></div>`;
}
function opsCenter(){
  if(!state.starter.finished||!opsView()){$('#ops').innerHTML=`<div class="empty"><h2>구단 창단 후 운영 센터가 열립니다.</h2>${startButton()}</div>`;return;}
  const o=ops(),v=opsView(),s=state.season,sc=v.scouting,locked=activeMatch(),meta=o.meta,week=s.history.length+1;
  const scout=sc?`<section class="panel ops-scout"><span class="eyebrow">SCOUTING REPORT · 다음 상대</span><h2>${esc(sc.name)}</h2><div class="scout-meta"><span class="style-chip style-${sc.style}">${esc(v.plans[sc.style].name)}</span><span>평균 OVR <b>${sc.overall}</b></span><span>${sc.record[0]}승 ${sc.record[1]}패</span></div><p class="muted">${esc(v.plans[sc.style].desc)} · ${esc(v.plans[sc.style].why)}</p><div class="scout-players">${sc.players.map(p=>`<div class="scout-player"><span class="role-tag">${roleKo[p.role]}</span><div><b>${esc(p.name)}</b><small>${p.year} · OVR ${p.overall}</small><div class="trait-line">${traitChips(null,p.traits)}</div></div><div class="scout-champs">${p.champions.map(ch=>champMini(ch.id,`숙련 ${ch.mastery}`)).join('')}</div></div>`).join('')}</div><div class="hint">상대가 노릴 가능성이 큰 우리 챔피언: ${sc.likely_bans.map(id=>esc(champs.champions[id]?.name??id)).join(' · ')||'—'}<br>추천 전략: <b>${esc(v.plans[sc.suggested].name)}</b></div></section>`:`<section class="panel ops-scout"><span class="eyebrow">SCOUTING REPORT</span><h2>시즌이 끝났습니다</h2><p class="muted">다음 시즌을 시작하면 새 상대와 패치가 공개됩니다.</p>${startButton()}</section>`;
  const plans=`<section class="panel ops-plan"><span class="eyebrow">GAME PLAN</span><h2>경기 전략</h2><p class="muted">난전 → 후반 → 시야 → 라인 → 난전 · 화살표 쪽을 이깁니다. 상성 우위 팀은 전 능력치 +2.</p><div class="plan-cards">${Object.entries(v.plans).map(([id,p])=>{const c=sc?counterOf(id,sc.style):0;return `<button class="plan-card ${o.plan===id?'selected':''} ${c>0?'good':c<0?'bad':''}" data-plan="${id}" ${locked?'disabled':''} aria-pressed="${o.plan===id}"><b>${esc(p.name)}</b><small>${esc(p.desc)}</small><em>${sc?counterText(c):'—'}</em><span>${esc(p.why)}</span></button>`;}).join('')}</div>${locked?'<div class="hint">경기 중에는 전략을 바꿀 수 없습니다.</div>':''}</section>`;
  const patch=meta?`<section class="panel ops-patch"><span class="eyebrow">PATCH ${esc(meta.patch)} · SEASON META</span><h2>이번 시즌 패치 노트</h2><div class="patch-cols"><div><h4 class="buff">▲ 상향 · 전투 +3 · 라인전 +2</h4>${meta.buffs.map(id=>`<div class="patch-line">${champMini(id)}<span>${esc(champs.champions[id].name)}</span></div>`).join('')}</div><div><h4 class="nerf">▼ 하향 · 전투 −3 · 라인전 −2</h4>${meta.nerfs.map(id=>`<div class="patch-line">${champMini(id)}<span>${esc(champs.champions[id].name)}</span></div>`).join('')}</div></div><div class="hint">◆ ${esc(v.meta_tags[meta.tag])} 계열 챔피언 전투 +2 · 양 팀 모두 적용 · AI도 메타 챔피언을 우선 고르고 밴합니다.</div></section>`:'';
  const sponsor=`<section class="panel ops-sponsor"><span class="eyebrow">SPONSORSHIP</span><h2>${o.sponsor?'시즌 스폰서':'스폰서 제안'}</h2>${o.sponsor?`<div class="sponsor-card signed"><b>${esc(v.sponsor_catalog[o.sponsor].name)}</b><small>${esc(v.sponsor_catalog[o.sponsor].desc)}</small><em>이번 시즌 수입 ${num(o.sponsor_income)} CR</em></div>`:o.sponsor_offers.length?`<p class="muted">시즌마다 한 곳과 계약합니다. 계약 이후 경기부터 적용됩니다.</p><div class="sponsor-offers">${o.sponsor_offers.map(id=>`<button class="sponsor-card" data-sponsor="${id}"><b>${esc(v.sponsor_catalog[id].name)}</b><small>${esc(v.sponsor_catalog[id].desc)}</small><em>계약하기 →</em></button>`).join('')}</div>`:'<p class="muted">다음 시즌에 새 제안이 도착합니다.</p>'}</section>`;
  $('#ops').innerHTML=`<div class="page-heading"><div><span class="eyebrow">TEAM OPERATIONS / SEASON ${state.season_number} · WEEK ${week}</span><h1>이번 주,<br><em>감독의 결정.</em></h1><p class="muted">훈련과 휴식, 전략과 스폰서. 경기 밖의 선택이 다음 승부를 만듭니다.</p></div>${divisionBadge()}</div>${seasonResultMarkup()}<ul class="todo-list wide">${opsTodos().map(t=>`<li class="${t.done?'done':''}">${t.done?'✓':'!'} ${esc(t.text)}</li>`).join('')}</ul><div class="ops-grid">${scout}${plans}</div><section class="panel ops-training"><div class="section-head"><div><span class="eyebrow">WEEKLY TRAINING</span><h2>주간 훈련 계획</h2></div><small>경기를 마칠 때마다 1주가 지나며 계획이 적용됩니다 · 경기 출전 피로 8 · 주간 회복 +5</small></div><div class="train-legend">체력이 높을수록 좋은 컨디션이 나올 확률이 오릅니다 · 체력 25 미만은 탈진(모든 능력치 −4) · 체력 30 미만이면 훈련 효과 절반 · 연승 중 사기 ▲ ${o.morale>0?'+':''}${o.morale}</div>${roles.map(trainingRow).join('')}</section><div class="ops-grid">${patch}${sponsor}</div>${weekMarkup(o.last_week)}`;
}
function ladderMarkup(){
  const v=opsView();if(!v)return '';const current=ops().division,hist=ops().division_history??[];
  return `<section class="ladder panel"><span class="eyebrow">DIVISION LADDER</span><div class="ladder-steps">${v.divisions.map((d,i)=>`<div class="ladder-step ${i===current?'current':i<current?'cleared':''}"><i>${esc(d.short)}</i><b>${esc(d.name)}</b><small>AI 평균 OVR ≈ ${Math.round(d.ai_base+d.ai_step*3)} · 보상 ×${d.reward}</small></div>`).join('<span class="ladder-arrow">→</span>')}</div>${hist.length?`<div class="ladder-history">${hist.map(h=>`<span class="${h.outcome}">S${h.season} · ${esc(v.divisions[h.division].short)} ${h.standing}위${h.champion?' 🏆':''} · ${h.outcome==='promote'?'승격':h.outcome==='relegate'?'강등':'잔류'}</span>`).join('')}</div>`:''}</section>`;
}
function render(){
  if(!state)return;
  $('#loading').hidden=true;$('#coins').textContent=num(state.coins);$('#export').disabled=false;$('#import').disabled=false;$('#restart').disabled=false;
  document.querySelectorAll('.nav').forEach(b=>{b.classList.toggle('active',b.dataset.tab===tab);if(b.dataset.tab===tab)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==tab);
  ({home,arena,collection,season,sources,relics,ops:opsCenter,'draft-room':draftRoom})[tab]();
  const opsNav=document.querySelector('.nav[data-tab="ops"] small'),open=opsTodos().filter(t=>!t.done).length;
  if(opsNav){opsNav.textContent=open?`!${open}`:'OPS';opsNav.classList.toggle('alert',open>0);}
  matchPopup();
  const eventId=tab==='arena'?state.match?.event?.id:null;
  if(eventId&&eventId!==lastEventId&&!state.match?.reports?.length){
    const first=$('#match-dialog .choice');first?.focus({preventScroll:true});
    if(window.innerWidth<900)$('.event-box')?.scrollIntoView({block:'center',behavior:'smooth'});
  }
  lastEventId=eventId;
}
function download(text,name){const url=URL.createObjectURL(new Blob([text],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);}
document.addEventListener('click',async(e)=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if(b.dataset.tab||b.dataset.goto){tab=b.dataset.tab||b.dataset.goto;window.scrollTo(0,0);render();return;}
  if(b.dataset.inspect){inspectedUnit=b.dataset.inspect;arena();return;}
  if(b.dataset.feed){feedFilter=b.dataset.feed;arena();return;}
  if(b.dataset.draftRole){draftRole=b.dataset.draftRole;draftRoom();return;}
  if(b.hasAttribute('data-open-decision')){matchPopup();return;}
  if(b.hasAttribute('data-auto')){auto=!auto;arena();return;}
  if(b.hasAttribute('data-coach')){autoCoach=!autoCoach;if(autoCoach)auto=true;render();return;}
  if(b.dataset.plan){await act({type:'set_plan',plan:b.dataset.plan},{quiet:true});return;}
  if(b.dataset.trainFocus){await act({type:'set_training',role:b.dataset.trainRole,focus:b.dataset.trainFocus},{quiet:true});return;}
  if(b.dataset.sponsor){await act({type:'sign_sponsor',sponsor:b.dataset.sponsor});toast(state.notice);return;}
  if(b.hasAttribute('data-speed')){speed=Number(b.dataset.speed);arena();document.querySelector(`[data-speed="${speed}"]`)?.focus({preventScroll:true});return;}
  if(b.dataset.buyRelic){await act({type:'buy_relic',relic:b.dataset.buyRelic});return;}
  if(b.dataset.useRelic){await act({type:'use_relic',relic:b.dataset.useRelic});return;}
  if(b.dataset.reward){await act({type:'reward_choice',option:b.dataset.reward});return;}
  if(b.dataset.targetFocus){await act({type:'target_focus',focus:b.dataset.targetFocus},{quiet:true});return;}
  if(b.dataset.ackReport){await act({type:'ack_report',report:Number(b.dataset.ackReport)},{quiet:true});return;}
  if(b.dataset.draftChampion){const type=state.banpick.phase==='ban'?'ban_champion':'pick_champion';draftSearch='';await act({type,champion:b.dataset.draftChampion,...(type==='pick_champion'?{role:draftRole??state.banpick.role}:{})},{quiet:true});return;}
  if(b.hasAttribute('data-step')){auto=false;await act({type:'tick',steps:1},{quiet:true});return;}
  if(b.dataset.choice){await executeChoice(b.dataset.choice);return;}
  if(b.dataset.action){auto=true;await act({type:b.dataset.action},{switchTo:b.dataset.action==='start'?'arena':b.dataset.action==='begin_draft'?'draft-room':'home'});return;}
  if(b.dataset.starterOpen){b.disabled=true;await act({type:'starter_open',role:b.dataset.starterOpen},{quiet:true});if(!state.starter.packs[b.dataset.starterOpen].card)render();return;}
  if(b.dataset.abilities){showAbilities(b.dataset.abilities);return;}
  if(b.hasAttribute('data-pull')){await act({type:'pull',role:$('#scout-role').value});return;}
  if(b.dataset.equip){await act({type:'equip',card:b.dataset.equip});return;}
  if(b.hasAttribute('data-more')){collectionFilter.limit+=30;collection();return;}
  if(b.hasAttribute('data-new')){if(busy){toast('현재 동작이 끝난 뒤 다시 눌러주세요.');return;}resumeAfterNew=auto;auto=false;$('#seed-input').value=freshSeed();$('#new-dialog').showModal();if(tab==='arena')arena();return;}
  if(b.hasAttribute('data-recovery')){download(storedRecovery,'nexus-recovery.json');return;}
});
document.addEventListener('change',async(e)=>{
  if(e.target.dataset.choiceSpell){summonerSelections.set(e.target.dataset.choiceSpell,e.target.value);matchPopup();return;}
  if(e.target.dataset.loadout){const role=e.target.dataset.loadout,spells=[...state.summoner_loadouts[role]];spells[Number(e.target.dataset.slot)]=e.target.value;await act({type:'summoner_loadout',role,spells},{quiet:true});render();return;}
  if(e.target.dataset.trainChampion){await act({type:'set_training',role:e.target.dataset.trainChampion,focus:'champion',champion:e.target.value},{quiet:true});return;}
  if(e.target.dataset.assignRelic){await act({type:'assign_relic',relic:e.target.dataset.assignRelic,card:e.target.value});return;}
  if(e.target.dataset.starterFilter){const field=e.target.dataset.starterFilter,role=e.target.dataset.role;await act({type:'starter_filter',role,[field]:e.target.value},{quiet:true});document.querySelector(`[data-starter-filter="${field}"][data-role="${role}"]`)?.focus({preventScroll:true});return;}
  if(e.target.dataset.draft){await act({type:'draft',role:e.target.dataset.draft,champion:e.target.value});render();}
  if(e.target.dataset.filter){collectionFilter[e.target.dataset.filter]=e.target.value;collectionFilter.limit=30;collection();}
});
document.addEventListener('input',e=>{if(e.target.id==='collection-search'){collectionFilter.search=e.target.value;collectionFilter.limit=30;collection();}if(e.target.id==='draft-search'){draftSearch=e.target.value;draftRoom();}});
$('#export').onclick=()=>download(saveText,`nexus-season-${state.season_number}.json`);
$('#import').onclick=()=>$('#save-file').click();
$('#save-file').onchange=async(e)=>{const f=e.target.files[0];if(!f)return;if(f.size>4000000){toast('4MB 이하 세이브 파일을 선택하세요.',true);return;}auto=false;await act({type:'import',save:await f.text()},{switchTo:'home'});e.target.value='';};
$('#new-dialog').addEventListener('close',()=>{auto=resumeAfterNew;resumeAfterNew=false;if(state&&tab==='arena')arena();});
$('#confirm-new').onclick=async(e)=>{e.preventDefault();if(busy)return;const seed=$('#seed-input').value.trim();if(!seed){$('#seed-input').reportValidity();return;}resumeAfterNew=false;$('#new-dialog').close();auto=false;await act({type:'new',seed},{switchTo:'home'});};
$('#match-dialog').addEventListener('cancel',e=>e.preventDefault());
document.addEventListener('keydown',e=>{if($('#match-dialog').open&&!state.match.reports?.length&&state.match.event&&!['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)&&/^[1-4]$/.test(e.key)){const o=state.match.event.options[Number(e.key)-1];if(o){e.preventDefault();executeChoice(o.id);}}});
// Match clock advances once per second; the AI coach clears reports and decisions between ticks.
let lastTick=0;
setInterval(()=>{
  if(busy||!activeMatch())return;
  const m=state.match,now=Date.now();
  if(autoCoach&&m.reports?.length){act({type:'ack_report',report:m.reports[0].id},{quiet:true});return;}
  if(autoCoach&&m.event){const best=[...m.event.options].sort((a,b)=>b.chance-a.chance)[0];act({type:'choose',option:best.id},{quiet:true});return;}
  if(auto&&!m.event&&!m.reports?.length&&now-lastTick>=1000){lastTick=now;act({type:'tick',steps:speed},{quiet:true});}
},200);
async function fetchJSON(path){const r=await fetch(new URL(path,import.meta.url),{cache:'no-cache'});if(!r.ok)throw new Error(`${path} 파일을 읽을 수 없습니다 (${r.status}).`);return r.json();}
async function boot(){
  try{
    [catalog,champs,media]=await Promise.all([fetchJSON('./data/cards.json'),fetchJSON('./data/champions.json'),fetchJSON('./data/media.json')]);
    cards=Object.fromEntries(catalog.cards.map(c=>[c.id,c]));aliases=Object.fromEntries(Object.keys(champs.champions).map(k=>[norm(k),k]));aliases.wukong='MonkeyKing';
    let saved;try{saved=localStorage.getItem(STORAGE);}catch{storageBlocked=true;}
    let result;
    if(saved){try{result=await rpc({type:'import',save:saved});}catch(e){storageBlocked=true;storedRecovery=saved;toast(`${e.message} 이전 저장은 유지했습니다.`,true);}}
    result=result??await rpc({type:'new',seed:freshSeed()});state=result.state;saveText=result.save;auto=false;if(state.banpick)tab='draft-room';persist();render();
  }catch(e){$('#load-status').textContent=e.message;$('.loading-track').hidden=true;toast('게임을 불러오지 못했습니다. README의 실행·네트워크 안내를 확인해 주세요.',true);}
}
boot();
