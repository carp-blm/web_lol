const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roles = ['top','jng','mid','bot','sup'];
const roleKo = {top:'탑',jng:'정글',mid:'미드',bot:'바텀',sup:'서포터'};
const phaseKo = {regular:'정규시즌',semifinal:'플레이오프 · 준결승',final:'플레이오프 · 결승',complete:'시즌 종료'};
const clock = (t) => `${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`;
const num = (n) => Number(n).toLocaleString('ko-KR');
const norm = (s) => String(s).toLowerCase().replace(/[^a-z0-9]/g,'');
let catalog, champs, media, cards, aliases, state, saveText, busy=false, tab='home', auto=true, speed=1;
let storageBlocked=false, storedRecovery=null, toastTimer, lastEventId=null;
let lastOpenedRole=null, resumeAfterNew=false;
const freshSeed=()=>`NEXUS-${Array.from(crypto.getRandomValues(new Uint32Array(2)),n=>n.toString(16)).join('-')}`;
let collectionFilter={search:'',role:'any',year:'any',owned:'owned',limit:30};
const STORAGE = `nexus-archive:${location.pathname.replace(/index\.html$/, '')}:v1`;
const worker = new Worker(new URL('./worker.js?v=0.3.0', import.meta.url), {type:'module'});
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
    if(action.type==='import'||action.type==='new'){storageBlocked=false;storedRecovery=null;}
    persist();if(switchTo){tab=switchTo;window.scrollTo(0,0);}render();
    if(!quiet&&['pull','equip','import','new'].includes(action.type))toast(action.type==='pull'?state.notice:'저장했습니다.');
  }catch(e){toast(e.message,true);}finally{busy=false;}
}
function image(url,alt,cls=''){return `<img class="${cls}" src="${esc(url)}" alt="${esc(alt)}" loading="lazy" referrerpolicy="no-referrer">`;}
document.addEventListener('error',e=>{if(e.target.tagName==='IMG'&&!e.target.dataset.fallback){e.target.dataset.fallback='1';e.target.src='./assets/skill-placeholder.svg';}},true);
function masteries(c){return c.mastery.map(m=>({...m,id:aliases[norm(m.name)]})).filter(m=>m.id);}
function mastery(c,cid){return masteries(c).find(m=>m.id===cid)?.value??35;}
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
  const photo=media.assets[c.id],logo=media.assets[c.team_media_key];
  const selected=state.roster[c.role]===c.id,owned=state.owned.includes(c.id);
  const champ=draft?state.draft[c.role]:(masteries(c)[0]?.id??'Ahri');
  const cp=champs.champions[champ];
  let picker='';
  if(draft){
    const experienced=masteries(c),known=new Set(experienced.map(m=>m.id));
    picker=`<div class="champion-select">${image(cp.portrait,cp.name)}<select aria-label="${esc(c.name)} 챔피언 선택" data-draft="${c.role}" ${activeMatch()?'disabled':''}><optgroup label="공식 출전 기반 숙련 챔피언">${experienced.map(m=>`<option value="${m.id}" ${m.id===champ?'selected':''}>${esc(champs.champions[m.id].name)} · ${m.value}</option>`).join('')}</optgroup><optgroup label="미출전 챔피언 · 기본 숙련도 35">${Object.values(champs.champions).filter(ch=>!known.has(ch.id)).sort((a,b)=>a.name.localeCompare(b.name,'ko')).map(ch=>`<option value="${ch.id}" ${ch.id===champ?'selected':''}>${esc(ch.name)} · 35</option>`).join('')}</optgroup></select></div><div class="skills">${skills(champ)}</div><p class="mastery">숙련도 ${mastery(c,champ)}</p><button class="skill-library-link" data-abilities="${champ}">형태별 스킬 보기 ↗</button>`;
  }
  return `<article class="player-card"><div class="player-top" data-year="${c.year}"><span class="role">${c.role.toUpperCase()}</span><span class="ovr">${c.overall}<small>OVR</small></span>${image(photo?.display??'assets/player-placeholder.svg',`${c.name} ${c.year} 프로필 대체 이미지`)}<span class="photo-note">${photo?.verified&&photo?.display?.includes('/approved/')?'검증 이미지':'프로필 대체 이미지'}</span></div><div class="player-info"><div class="player-name">${esc(c.name)}</div><div class="player-sub" title="${esc(c.team)}">${image(logo?.display??'assets/team-placeholder.svg','팀 로고 대체 이미지')}${c.year} · ${esc(c.team)}</div><div class="ratings"><span>라인전 <b>${c.ratings.lane}</b></span><span>전투 <b>${c.ratings.combat}</b></span><span>시야 <b>${c.ratings.vision}</b></span><span>성장 <b>${c.ratings.farm}</b></span></div>${picker}${collection?`<div class="evidence">${esc(c.league)} · ${c.tier}군 리그 · ${c.games}회 출전<br>${esc(cp?.name)} 숙련 ${mastery(c,champ)}</div><button class="${selected?'ghost':'secondary'}" data-equip="${c.id}" ${(!owned||selected||activeMatch())?'disabled':''}>${selected?'선발 로스터':owned?'로스터 편성':'미보유'}</button><details class="evidence"><summary>출전 기록 확인</summary>${esc(c.evidence.first_date)}<br>${esc(c.evidence.first_game)}<br>마지막: ${esc(c.evidence.last_date)}<br>${esc(c.evidence.last_game)}</details>`:''}</div></article>`;
}
function opponent(){const s=state.season;if(s.phase==='complete')return null;if(s.phase!=='regular')return s.opponent;return s.schedule[s.round].find(p=>p.includes(0)).find(i=>i!==0);}
function startButton(){if(!state.starter.finished)return '<button class="primary" data-goto="home">시작 팩 열기 →</button>';return activeMatch()?'<button class="primary full" data-goto="arena">진행 중인 경기로 <span>↗</span></button>':state.season.phase==='complete'?'<button class="primary full" data-action="next_season">다음 시즌 시작 <span>→</span></button>':'<button class="primary full" data-action="start">경기 시작 <span class="arrow">→</span></button>';}
function home(){
  if(!state.starter.finished){starterHome();return;}
  const s=state.season,opp=opponent(),record=s.teams[0],round=Math.min(s.round+1,5),team=opp===null?'SEASON COMPLETE':s.teams[opp].name;
  $('#home').innerHTML=`<div class="hero"><div><span class="eyebrow"><i class="line"></i> BUILD YOUR LEGACY</span><h1>세대를 넘어,<br><em>하나의 팀</em>으로.</h1><p>기록 속의 선수들을 당신의 로스터로.<br>예측할 수 없는 전장에서, 다음 선택은 감독님의 몫입니다.</p><div class="hero-meta"><span><b>${num(catalog.coverage.cards)}</b> 선수 카드</span><span><b>${catalog.coverage.years.join(' / ')}</b> 아카이브</span><span><span class="status-dot"></span> 로컬 플레이</span></div></div><div class="match-preview"><div class="preview-top"><span>SEASON ${String(state.season_number).padStart(2,'0')} / MATCHDAY ${String(round).padStart(2,'0')}</span><span class="pill">${phaseKo[s.phase]}</span></div><div class="versus"><div class="team-block"><div class="team-mark home-mark">N</div><b>NEXUS CLUB</b><small>나의 드림팀</small></div><span class="vs">VS</span><div class="team-block"><div class="team-mark">${team[0]}</div><b>${team}</b><small>${opp===null?'수고하셨습니다':'전 세계 선수로 구성된 AI 구단'}</small></div></div>${startButton()}</div></div><div class="section-head"><div><h2>선발 로스터 <span class="muted">/ 05</span></h2><span class="eyebrow">YOUR STARTING FIVE</span></div><small>챔피언을 선택하고 나만의 조합을 완성하세요</small></div><div class="roster">${roles.map(r=>playerCard(cards[state.roster[r]],{draft:true})).join('')}</div><div class="bottom-grid"><div class="panel scout-panel"><div class="scout-art">?</div><div class="scout-content"><div class="eyebrow">SCOUTING ROOM</div><h3>다음 에이스를 만나보세요</h3><p>실제 출전 기록이 있는 선수만 영입합니다.<br>현금 결제 없이, 경기 보상으로 모으는 컬렉션.</p><div class="scout-actions"><select id="scout-role" aria-label="영입 포지션"><option value="any">전체 · 150 CR</option>${roles.map(r=>`<option value="${r}">${roleKo[r]} · 200 CR</option>`).join('')}</select><button class="primary" data-pull ${activeMatch()?'disabled':''}>선수 영입 <span>↗</span></button></div></div></div><div class="panel"><span class="eyebrow">CLUB OVERVIEW</span><div class="mini-stats"><b>${record.wins} — ${record.losses}<small>이번 시즌 승 · 패</small></b><b>${state.owned.length}<small>보유 선수 카드</small></b><b>${state.trophies}<small>우승 트로피</small></b></div><div class="hint">선택 이벤트가 발생하면 경기가 멈춥니다.<br>위험을 감수할지, 다음 기회를 만들지 결정하세요.</div></div></div>${state.last_pull?`<div class="notice" style="margin-top:18px">최근 영입: ${esc(cards[state.last_pull.id].name)} · ${cards[state.last_pull.id].year} · ${esc(cards[state.last_pull.id].team)} ${state.last_pull.duplicate?'(중복 · 90 CR 환급)':''} <button class="ghost" data-goto="collection">컬렉션에서 확인 →</button></div>`:''}`;
}
function mapSvg(m){
  const points={top:[[70,230],[70,160],[100,95]],mid:[[120,235],[175,180],[230,125]],bot:[[150,290],[220,290],[290,240]]};
  let towers='';
  for(let side=0;side<2;side++)for(const lane of ['top','mid','bot'])points[lane].forEach(([x,y],i)=>{if(side===1){x=360-x;y=360-y;}const alive=i<m.towers[side][lane];towers+=`<rect x="${x-5}" y="${y-5}" width="10" height="10" transform="rotate(45 ${x} ${y})" fill="${alive?(side===0?'#72d4d3':'#ef8987'):'#34494d'}" stroke="${side===0?'#72d4d3':'#ef8987'}" opacity="${alive?1:.3}"/>`;});
  return `<svg class="map-svg" viewBox="0 0 360 360" role="img" aria-label="양 팀 포탑과 넥서스 상태 지도"><defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#3b5a58" opacity=".17"/></pattern></defs><rect width="360" height="360" fill="url(#grid)"/><path d="M40 310V75Q40 40 75 40H310M40 310 310 40M40 310H275Q310 310 310 275V40" fill="none" stroke="#56716a" stroke-width="9" opacity=".45"/><path d="M45 145Q180 140 215 315M140 45Q180 200 315 215" fill="none" stroke="#396e78" stroke-width="14" opacity=".35"/><path d="m65 175 48-56 54-25-30 66-32 52ZM176 260l27-68 50-22 26 39-54 59Z" fill="#244f42" opacity=".8"/>${towers}<circle cx="40" cy="310" r="17" fill="#163e43" stroke="#72d4d3" stroke-width="2"/><path d="m40 296 9 14-9 14-9-14Z" fill="#72d4d3"/><circle cx="310" cy="40" r="17" fill="#462b32" stroke="#ef8987" stroke-width="2"/><path d="m310 26 9 14-9 14-9-14Z" fill="#ef8987"/><circle cx="122" cy="128" r="12" fill="#273341" stroke="#ac9bca"/><text x="122" y="132" fill="#c6bce1" font-size="10" text-anchor="middle">B</text><circle cx="236" cy="233" r="12" fill="#39351f" stroke="#cab075"/><text x="236" y="237" fill="#e2d09e" font-size="10" text-anchor="middle">D</text><text x="40" y="348" font-size="9" fill="#72d4d3" text-anchor="middle">OUR NEXUS</text><text x="310" y="12" font-size="9" fill="#ef8987" text-anchor="middle">ENEMY</text></svg>`;
}
function arena(){
  const m=state.match;
  if(!m){$('#arena').innerHTML=`<div class="page-heading"><div><span class="eyebrow">THE RIFT AWAITS</span><h1>첫 경기를 시작하세요.</h1></div></div><div class="empty"><p>로스터와 챔피언을 선택하면 준비 완료입니다.</p>${startButton()}</div>`;return;}
  const event=m.event,over=m.winner!==null;
  let eventHtml;
  if(event){eventHtml=`<div class="event-box"><span class="eyebrow"><span class="status-dot"></span> DECISION POINT · 경기 일시정지</span><h2>${esc(event.title)}</h2><div class="event-context">${esc(event.context)}</div><p class="event-story">${esc(event.story)}</p><div class="choices">${event.options.map((o,i)=>`<button class="choice" data-choice="${o.id}"><span class="chance">${Math.round(o.chance*100)}%</span><strong>${i+1}. ${esc(o.label)}</strong><small>${esc(o.detail)}</small></button>`).join('')}</div></div>`;}
  else if(over){eventHtml=`<div class="await-event"><span class="eyebrow">NEXUS DESTROYED</span><div class="result-word ${m.winner===1?'loss':''}">${m.winner===0?'VICTORY':'DEFEAT'}</div><p>${clock(m.time)} 동안 이어진 승부.<br>${m.decisions.length}번의 선택이 이번 경기를 만들었습니다.</p><div class="notice">${esc(state.notice)}</div>${startButton()}</div>`;}
  else{eventHtml=`<div class="await-event"><span class="eyebrow">${auto?'MATCH IN PROGRESS':'MATCH PAUSED'}</span><h2 style="margin-top:14px">${auto?'선수들이 기회를 만들고 있습니다.':'작전을 돌아볼 시간입니다.'}</h2><p>교전·회피·귀환은 선수들이 판단합니다.<br>중요한 전술 상황에서만 선택을 요청합니다.</p><div class="hint">우리 시야 ${m.vision[0]} · 상대 시야 ${m.vision[1]}<br>다음 드래곤: ${m.next_dragon>m.time?clock(m.next_dragon-m.time)+' 후':'등장'} · 바론: ${m.next_baron>m.time?clock(m.next_baron-m.time)+' 후':'등장'}</div></div>`;}
  $('#arena').innerHTML=`<div class="page-heading"><div><span class="eyebrow">LIVE MATCH CENTER</span><h1>승부는 지금부터.</h1></div><div class="arena-toolbar"><button class="ghost" data-auto ${over||event?'disabled':''}>${auto?'Ⅱ 일시정지':'▶ 자동 진행'}</button><button class="ghost" data-speed>속도 ${speed}×</button><button class="secondary" data-step ${over||event?'disabled':''}>1초 진행</button></div></div><div class="scoreboard"><div class="score-side"><span class="score-kills">${m.kills[0]}</span><div><div class="score-team">NEXUS CLUB</div><div class="score-gold">${num(m.gold[0])} G</div></div></div><div class="game-clock">${clock(m.time)}<small>${over?'FINISHED':event?'DECISION':'LIVE'}</small></div><div class="score-side red"><div><div class="score-team">${esc(m.opponent_name)}</div><div class="score-gold">${num(m.gold[1])} G</div></div><span class="score-kills">${m.kills[1]}</span></div></div><div class="arena-grid"><div><div class="map-panel"><div class="map-header"><span>TACTICAL OVERVIEW</span><span>${num(m.gold[0]-m.gold[1])} G</span></div>${mapSvg(m)}${visionPanel(m)}<div class="lane-values">${['top','mid','bot'].map(l=>`<span>${l.toUpperCase()}<b>${m.pressure[l]>0?'+':''}${m.pressure[l]}</b></span>`).join('')}</div></div><div class="objective-row"><div class="objective"><strong>${m.dragons[0]} : ${m.dragons[1]}</strong><small>드래곤</small></div><div class="objective"><strong>${m.barons[0]} : ${m.barons[1]}</strong><small>바론</small></div><div class="objective"><strong>${m.heralds[0]} : ${m.heralds[1]}</strong><small>전령</small></div></div><div class="nexus-bars"><div>우리 넥서스 · ${m.nexus[0]}<div class="bar"><i style="width:${m.nexus[0]/40}%"></i></div></div><div>상대 넥서스 · ${m.nexus[1]}<div class="bar red"><i style="width:${m.nexus[1]/40}%"></i></div></div></div></div><div>${eventHtml}<div class="log-panel"><div class="log-heading"><span>경기 중계</span><span class="live-tag">● MATCH FEED</span></div><div class="log-feed" tabindex="0" aria-label="최근 경기 중계">${[...m.log].reverse().slice(0,45).map(l=>`<div class="log-line log-${esc(l.kind)}"><time>${clock(l.time)}</time>${l.skill?image(l.skill.icon,l.skill.name):''}<span>${esc(l.text)}</span></div>`).join('')}</div></div></div></div><div class="lineups">${m.teams.map((team,side)=>`<div class="panel"><span class="eyebrow">${side===0?'NEXUS CLUB':esc(m.opponent_name)}</span>${team.map(u=>`<div class="lineup-row"><span class="lane">${u.role.toUpperCase()}</span>${image(champs.champions[u.champion].portrait,champs.champions[u.champion].name)}<b>${esc(u.name)}</b><span class="champ">${esc(champs.champions[u.champion].name)} · 숙련 ${u.mastery}<br>${unitAbilityStatus(u)}</span>${unitHealth(u,m.time)}</div>`).join('')}</div>`).join('')}</div><p class="evidence">경기 시드 ${m.seed} · 1×는 실제 1초당 경기 1초 · 공통 MVP 규칙 · 포탑 → 억제기 → 넥서스 순으로 진격합니다.</p>`;
}
function collection(){
  const f=collectionFilter;
  let pool=catalog.cards.filter(c=>(f.owned==='all'||state.owned.includes(c.id))&&(f.role==='any'||c.role===f.role)&&(f.year==='any'||String(c.year)===f.year)&&`${c.name} ${c.team} ${c.league}`.toLowerCase().includes(f.search.toLowerCase()));
  pool.sort((a,b)=>b.overall-a.overall||a.name.localeCompare(b.name));
  const focus=document.activeElement?.id==='collection-search',selection=document.activeElement?.selectionStart;
  $('#collection').innerHTML=`<div class="page-heading"><div><span class="eyebrow">THE PLAYER ARCHIVE</span><h1>당신만의 드림팀.</h1><p class="muted">보유 ${state.owned.length}장 / 전체 ${num(catalog.cards.length)}장 · 연도 제한 없이 편성하세요.</p></div><button class="secondary" data-goto="home">선수 영입 →</button></div><div class="filters"><input id="collection-search" placeholder="선수, 구단, 리그 검색" aria-label="선수 검색" value="${esc(f.search)}"><select data-filter="owned" aria-label="보유 여부"><option value="owned" ${f.owned==='owned'?'selected':''}>보유 카드</option><option value="all" ${f.owned==='all'?'selected':''}>모든 카드</option></select><select data-filter="role" aria-label="포지션"><option value="any">전체 포지션</option>${roles.map(r=>`<option value="${r}" ${f.role===r?'selected':''}>${roleKo[r]}</option>`).join('')}</select><select data-filter="year" aria-label="연도"><option value="any">모든 연도</option>${catalog.coverage.years.map(y=>`<option value="${y}" ${f.year===String(y)?'selected':''}>${y}</option>`).join('')}</select></div><div class="section-head"><small>${num(pool.length)}개의 카드</small><small>능력치순 · 출전 데이터 기반</small></div><div class="collection-grid">${pool.slice(0,f.limit).map(c=>playerCard(c,{collection:true})).join('')}</div>${pool.length===0?'<div class="empty">검색 조건에 맞는 카드가 없습니다.</div>':''}${pool.length>f.limit?'<button class="secondary load-more" data-more>카드 더 보기 ↓</button>':''}<div class="hint">전체 영입은 ${num(catalog.cards.length)}개 카드 각각 동일 확률(1/${num(catalog.cards.length)})입니다. 포지션 영입도 해당 포지션 내 동일 확률입니다. 중복 카드는 90 CR로 환급합니다. 선수 능력치는 실제 선수를 평가하는 공식 지표가 아닙니다.</div>`;
  if(focus){$('#collection-search').focus();$('#collection-search').setSelectionRange(selection,selection);}
}
function season(){
  if(!state.season){$('#season').innerHTML=`<div class="empty"><h2>드림팀을 먼저 완성하세요.</h2><p>다섯 포지션 팩을 열면 시즌이 시작됩니다.</p>${startButton()}</div>`;return;}
  const s=state.season;
  $('#season').innerHTML=`<div class="page-heading"><div><span class="eyebrow">SEASON ${state.season_number} / ROAD TO THE TITLE</span><h1>${phaseKo[s.phase]}</h1><p class="muted">6개 구단 · 5경기 정규시즌 · 상위 4팀 플레이오프</p></div>${s.phase==='complete'?'<button class="primary" data-action="next_season">다음 시즌 →</button>':'<button class="secondary" data-goto="home">로스터로 돌아가기 →</button>'}</div>${s.phase==='complete'?`<div class="notice">시즌 우승: ${esc(s.teams[s.champion]?.name??'결정 중')} · 선수 컬렉션과 크레딧은 다음 시즌으로 이어집니다.</div>`:''}<div class="season-grid"><div class="panel"><div class="section-head"><h2>리그 테이블</h2><small>${Math.min(s.round,5)} / 5 경기</small></div><table class="standings"><thead><tr><th>순위</th><th>구단</th><th>승</th><th>패</th></tr></thead><tbody>${s.standings.map((idx,i)=>`<tr class="${idx===0?'mine':''}"><td>${String(i+1).padStart(2,'0')}</td><td>${esc(s.teams[idx].name)} ${idx===0?'↖':''}</td><td>${s.teams[idx].wins}</td><td>${s.teams[idx].losses}</td></tr>`).join('')}</tbody></table><div class="hint">상위 4팀 진출. 동률이면 시즌 구단 번호순으로 결정합니다.<br>플레이오프는 3전 2선승제입니다.</div></div><div class="panel"><span class="eyebrow">MATCH HISTORY</span><h2 style="margin-top:10px">우리가 만든 기록</h2>${s.history.length?s.history.map(h=>`<div class="schedule-row"><span class="result ${h.won?'':'loss'}">${h.won?'W':'L'}</span><span>${esc(s.teams[h.opponent].name)}<br><small>${phaseKo[h.phase]} · +${h.reward} CR</small></span><small>${clock(h.duration)}</small></div>`).join(''):'<div class="empty">아직 경기를 치르지 않았습니다.</div>'}${['semifinal','final'].includes(s.phase)?`<div class="notice" style="margin-top:20px">현재 시리즈 ${s.series[0]} : ${s.series[1]}<br>상대 ${esc(s.teams[s.opponent].name)}</div>`:''}</div></div>`;
}
function sources(){
  $('#sources').innerHTML=`<div class="page-heading"><div><span class="eyebrow">BUILT ON REAL APPEARANCES</span><h1>기록에는 출처가 있습니다.</h1></div></div><div class="source-stats"><b>${num(catalog.coverage.cards)}<small>선수 / 연도 / 구단 / 포지션 카드</small></b><b>${num(catalog.coverage.appearances)}<small>중복 제거된 공식 출전 행</small></b><b>${Object.keys(champs.champions).length}<small>한국어 챔피언</small></b></div><div class="sources-grid"><div class="panel"><h3>Oracle's Elixir 경기 기록</h3><p>Oracle's Elixir / Tim Sevenhuysen의 ${catalog.coverage.years.join('·')} CSV 공개 보존본에서 추출했습니다. 명단에만 있는 선수는 생성하지 않으며, playerid·gameid·실제 경기 시간이 있는 출전만 사용합니다.</p><p>리그 허용 목록: ${esc(catalog.coverage.leagues.join(', '))}. 1군 ${num(catalog.coverage.tiers['1'])}장 / 2군 ${num(catalog.coverage.tiers['2'])}장. 2군은 대회 단계 기준으로 독립 팀도 포함합니다. 모든 지역·모든 연도의 완전 수록은 아닙니다.</p><a href="https://oracleselixir.com/tools/downloads" target="_blank" rel="noopener">원본 배포 안내 ↗</a><p>원본 접근 실패로 공개 CSV 보존본 사용. 원본과의 완전 일치 및 재배포 권한은 미검증입니다. 포함된 출전 행은 보존본 기준으로 검증했습니다.</p>${catalog.provenance.sources.map(s=>`<p><a href="${esc(s.snapshot_url)}" target="_blank" rel="noopener">${esc(s.filename)} 보존본 ↗</a><br><span class="evidence">SHA-256 ${esc(s.sha256.slice(0,20))}…</span></p>`).join('')}</div><div class="panel"><h3>챔피언 & 스킬</h3><p>Riot Data Dragon ${esc(champs.version)} · ko_KR<br>패시브/QWER 한국어 명칭·초상화·스킬 아이콘 주소를 수집합니다. 네트워크 오류 시 아이콘 대체 이미지를 표시합니다.</p><p>숙련도는 해당 카드의 공식 챔피언 출전 횟수와 승률로 추정합니다. 기본 스킬 태그는 한국어 설명에서 분류하며, 형태별 예외는 공식 상세 설명과 대조했습니다. ${champs.variant_audit?.reviewed_champions??173}종을 점검하고 ${champs.variant_audit?.families.length??0}종의 변신·무기·세부 주문·재시전 계열을 분리했습니다. 형태 전환 시간과 자원은 이 게임의 추상화이며 실제 LoL 수치와 다릅니다.</p><a href="https://developer.riotgames.com/docs/lol#data-dragon" target="_blank" rel="noopener">Data Dragon 문서 ↗</a><div class="warning">Riot 정책에 게임에서의 IP 사용 제한이 있어, 공개 배포 전 별도 권한 검토가 필요합니다. 비상업·무료라는 이유만으로 사용 권한이 확보되지는 않습니다.</div></div><div class="panel"><h3>연도별 사진 & 로고</h3><p>사진과 로고는 경기 데이터와 별도로 권한을 관리합니다. 출처·권리자·이용 근거·검증 날짜·선수/팀/연도가 확인된 로컬 파일만 적용합니다. 현재는 직접 제작한 대체 프로필·방패를 사용합니다.</p><p>검증되지 않은 사진을 그해 공식 유니폼 사진으로 표시하지 않습니다.</p></div><div class="panel"><h3>나의 저장 기록</h3><p>계정·서버·멀티플레이가 없습니다. 현재 브라우저에 저장되고, JSON 파일로 내보내거나 불러올 수 있습니다. 시드와 선택 기록이 같으면 결과도 같습니다.</p><p>시드: <b>${esc(state.seed)}</b><br>데이터 버전: ${esc(state.dataset)}<br>저장 상태: ${storageBlocked?'자동 저장 중지 · 파일로 내보내 주세요':'브라우저 자동 저장'}<br>기록 동작 ${state.save_actions} / 12,000</p><div class="settings"><button class="ghost" data-new>새 게임 / 시드 변경</button>${storedRecovery?'<button class="secondary" data-recovery>이전 세이브 복구 파일 받기</button>':''}</div></div></div>`;
}
function render(){
  if(!state)return;
  $('#loading').hidden=true;$('#coins').textContent=num(state.coins);$('#export').disabled=false;$('#import').disabled=false;$('#restart').disabled=false;
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==tab);
  ({home,arena,collection,season,sources})[tab]();
  const eventId=tab==='arena'?state.match?.event?.id:null;
  if(eventId&&eventId!==lastEventId){
    const first=$('.choice');first?.focus({preventScroll:true});
    if(window.innerWidth<900)$('.event-box')?.scrollIntoView({block:'center',behavior:'smooth'});
  }
  lastEventId=eventId;
}
function download(text,name){const url=URL.createObjectURL(new Blob([text],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);}
document.addEventListener('click',async(e)=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if(b.dataset.tab||b.dataset.goto){tab=b.dataset.tab||b.dataset.goto;window.scrollTo(0,0);render();return;}
  if(b.hasAttribute('data-auto')){auto=!auto;arena();return;}
  if(b.hasAttribute('data-speed')){speed=speed===1?3:speed===3?6:speed===6?12:speed===12?30:1;arena();return;}
  if(b.hasAttribute('data-step')){auto=false;await act({type:'tick',steps:1},{quiet:true});return;}
  if(b.dataset.choice){await act({type:'choose',option:b.dataset.choice},{quiet:true});return;}
  if(b.dataset.action){auto=true;await act({type:b.dataset.action},{switchTo:b.dataset.action==='start'?'arena':'home'});return;}
  if(b.dataset.starterOpen){b.disabled=true;await act({type:'starter_open',role:b.dataset.starterOpen},{quiet:true});if(!state.starter.packs[b.dataset.starterOpen].card)render();return;}
  if(b.dataset.abilities){showAbilities(b.dataset.abilities);return;}
  if(b.hasAttribute('data-pull')){await act({type:'pull',role:$('#scout-role').value});return;}
  if(b.dataset.equip){await act({type:'equip',card:b.dataset.equip});return;}
  if(b.hasAttribute('data-more')){collectionFilter.limit+=30;collection();return;}
  if(b.hasAttribute('data-new')){if(busy){toast('현재 동작이 끝난 뒤 다시 눌러주세요.');return;}resumeAfterNew=auto;auto=false;$('#seed-input').value=freshSeed();$('#new-dialog').showModal();if(tab==='arena')arena();return;}
  if(b.hasAttribute('data-recovery')){download(storedRecovery,'nexus-recovery.json');return;}
});
document.addEventListener('change',async(e)=>{
  if(e.target.dataset.starterFilter){const field=e.target.dataset.starterFilter,role=e.target.dataset.role;await act({type:'starter_filter',role,[field]:e.target.value},{quiet:true});document.querySelector(`[data-starter-filter="${field}"][data-role="${role}"]`)?.focus({preventScroll:true});return;}
  if(e.target.dataset.draft){await act({type:'draft',role:e.target.dataset.draft,champion:e.target.value});render();}
  if(e.target.dataset.filter){collectionFilter[e.target.dataset.filter]=e.target.value;collectionFilter.limit=30;collection();}
});
document.addEventListener('input',e=>{if(e.target.id==='collection-search'){collectionFilter.search=e.target.value;collectionFilter.limit=30;collection();}});
$('#export').onclick=()=>download(saveText,`nexus-season-${state.season_number}.json`);
$('#import').onclick=()=>$('#save-file').click();
$('#save-file').onchange=async(e)=>{const f=e.target.files[0];if(!f)return;if(f.size>4000000){toast('4MB 이하 세이브 파일을 선택하세요.',true);return;}auto=false;await act({type:'import',save:await f.text()},{switchTo:'home'});e.target.value='';};
$('#new-dialog').addEventListener('close',()=>{auto=resumeAfterNew;resumeAfterNew=false;if(state&&tab==='arena')arena();});
$('#confirm-new').onclick=async(e)=>{e.preventDefault();if(busy)return;const seed=$('#seed-input').value.trim();if(!seed){$('#seed-input').reportValidity();return;}resumeAfterNew=false;$('#new-dialog').close();auto=false;await act({type:'new',seed},{switchTo:'home'});};
document.addEventListener('keydown',e=>{if(!document.querySelector('dialog[open]')&&tab==='arena'&&state?.match?.event&&!['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)&&/^[1-4]$/.test(e.key)){const o=state.match.event.options[Number(e.key)-1];if(o){e.preventDefault();act({type:'choose',option:o.id},{quiet:true});}}});
setInterval(()=>{if(auto&&!busy&&activeMatch()&&!state.match.event)act({type:'tick',steps:speed},{quiet:true});},1000);
async function fetchJSON(path){const r=await fetch(new URL(path,import.meta.url),{cache:'no-cache'});if(!r.ok)throw new Error(`${path} 파일을 읽을 수 없습니다 (${r.status}).`);return r.json();}
async function boot(){
  try{
    [catalog,champs,media]=await Promise.all([fetchJSON('./data/cards.json'),fetchJSON('./data/champions.json'),fetchJSON('./data/media.json')]);
    cards=Object.fromEntries(catalog.cards.map(c=>[c.id,c]));aliases=Object.fromEntries(Object.keys(champs.champions).map(k=>[norm(k),k]));aliases.wukong='MonkeyKing';
    let saved;try{saved=localStorage.getItem(STORAGE);}catch{storageBlocked=true;}
    let result;
    if(saved){try{result=await rpc({type:'import',save:saved});}catch(e){storageBlocked=true;storedRecovery=saved;toast(`${e.message} 이전 저장은 유지했습니다.`,true);}}
    result=result??await rpc({type:'new',seed:freshSeed()});state=result.state;saveText=result.save;auto=false;persist();render();
  }catch(e){$('#load-status').textContent=e.message;$('.loading-track').hidden=true;toast('게임을 불러오지 못했습니다. README의 실행·네트워크 안내를 확인해 주세요.',true);}
}
boot();
