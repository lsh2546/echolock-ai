const $ = (selector) => document.querySelector(selector);
const verdictColor = {EXECUTE:"var(--mint)",ADAPT:"var(--cyan)",DEFER:"var(--amber)",REJECT:"var(--red)"};
let latestCertificate = null;

function fmt(value, suffix="") { return value === null || value === undefined ? "—" : `${Number(value).toFixed(2)}${suffix}`; }
function short(value, length=20) { return value ? `${value.slice(0,length)}…${value.slice(-8)}` : "—"; }

async function loadCatalog(){
  const scenarios = await fetch("/api/scenarios").then(r=>r.json());
  const grid = $("#scenario-grid");
  grid.innerHTML = scenarios.map((s,i)=>`<button class="scenario ${i===0?'active':''}" data-seed="${s.id}" data-verdict="${s.expected_verdict}"><span>${String(i+1).padStart(2,'0')} · ${s.id}</span><strong>${s.title}</strong><em>${s.expected_verdict}</em></button>`).join("");
  grid.addEventListener("click",e=>{const button=e.target.closest("button[data-seed]");if(!button)return;document.querySelectorAll('.scenario').forEach(x=>x.classList.remove('active'));button.classList.add('active');loadScenario(button.dataset.seed);});
}

function renderBranches(branches){
  const titles={FORCE_ORIGINAL:"Force original",REJECT_ENTIRELY:"Reject entirely",ECHOLOCK_VERIFIED:"EchoLock verified"};
  $("#branches").innerHTML=branches.map(b=>{const gps=b.safety_violations.length?`INELIGIBLE · raw ${fmt(b.goal_preservation_score)}`:fmt(b.goal_preservation_score);return `<article class="branch ${b.strategy==='ECHOLOCK_VERIFIED'?'echo':''}"><span class="tag">${b.strategy}</span><h3>${titles[b.strategy]}</h3><p class="violations ${b.safety_violations.length?'':'safe'}">${b.safety_violations.length?`⚠ ${b.safety_violations.join(', ')}`:'✓ NO SAFETY VIOLATIONS'}</p><dl><div><dt>Scientific value</dt><dd>${fmt(b.scientific_value*100,'%')}</dd></div><div><dt>Final battery</dt><dd>${fmt(b.final_battery_pct,'%')}</dd></div><div><dt>Maximum temp</dt><dd>${fmt(b.maximum_temp_c,'°C')}</dd></div><div><dt>Goal preservation eligibility</dt><dd>${gps}</dd></div></dl></article>`}).join("");
}

function renderPatch(patch, verdict){
  if(!patch){ $("#patch").textContent=verdict==='EXECUTE'?'No patch required — original command remains inside the Mission Intent Envelope.':'No authorised executable patch — fail closed.'; return; }
  const changes=[];
  if(patch.adapted_image_count)changes.push(`${patch.adapted_image_count} images`);
  if(patch.adapted_resolution)changes.push(`${patch.adapted_resolution} resolution`);
  if(patch.adapted_power_pct)changes.push(`${patch.adapted_power_pct}% power`);
  if(patch.delay_minutes)changes.push(`${patch.delay_minutes} min delay`);
  if(patch.compression_applied)changes.push('compression');
  $("#patch").textContent=`${patch.adaptation_types.join(' + ')} → ${changes.join(', ')}`;
}

async function loadScenario(seed){
  $("#scenario-label").textContent=`RUNNING ${seed} · ARRIVAL-TIME REVALIDATION`;
  const data=await fetch(`/api/scenarios/${seed}`).then(r=>{if(!r.ok)throw new Error('Scenario failed');return r.json()});
  latestCertificate=data.certificate;
  $("#scenario-label").textContent=`${data.scenario.id} · PRECEDENCE STEP ${data.precedence_step}`;
  $("#verdict").textContent=data.verdict; $("#verdict").style.color=verdictColor[data.verdict];
  $("#scenario-summary").textContent=data.scenario.summary;
  $("#battery").textContent=fmt(data.arrival_state.battery_soc,'%'); $("#battery-meter").value=data.arrival_state.battery_soc;
  $("#temperature").textContent=fmt(data.arrival_state.equipment_temp_c,'°C'); $("#temp-meter").value=data.arrival_state.equipment_temp_c;
  $("#comm").textContent=data.arrival_state.comm_window_status;
  $("#gps").textContent=data.goal_preservation_score===null?(data.verdict==='EXECUTE'?'1.00':'0.00'):fmt(data.goal_preservation_score);
  renderPatch(data.applied_patch,data.verdict); renderBranches(data.counterfactual.branches);
  $("#certificate-id").textContent=data.certificate.certificate_id;
  $("#decision-step").textContent=`${data.verdict} / STEP ${data.precedence_step}`;
  $("#certificate-hash").textContent=data.certificate.certificate_hash;
  $("#semantic-hash").textContent=data.certificate.semantic_replay_hash;
  $("#certificate-json").textContent=JSON.stringify(data.certificate,null,2);
  await loadAudit();
}

async function loadAudit(){
  const data=await fetch('/api/audit').then(r=>r.json());
  $("#chain-status").innerHTML=data.chain_valid?'<span class="safe">✓ CHAIN VERIFIED</span>':'<span class="violations">CHAIN INVALID</span>';
  $("#audit-list").innerHTML=data.entries.length?data.entries.slice().reverse().map(e=>`<div class="audit-entry"><span class="number">${e.sequence_number}</span><div><strong>${e.verdict} · certificate ${short(e.certificate_id,8)}</strong><code>${short(e.entry_hash,22)}</code></div><em>LINKED</em></div>`).join(''):'<p class="limitation">Run a scenario to create the first signed audit entry.</p>';
}

async function loadMetrics(){const m=await fetch('/api/evaluation').then(r=>r.json());const values=[m.scenario_count,`${m.unsafe_command_interception_recall*100}%*`,`${m.safety_violation_rate*100}%*`,`${m.deterministic_replay_consistency*100}%*`];document.querySelectorAll('#metrics strong').forEach((el,i)=>el.textContent=values[i]);}

$("#json-toggle").addEventListener("click",()=>{const pre=$("#certificate-json");pre.hidden=!pre.hidden;$("#json-toggle").textContent=pre.hidden?'View signed certificate JSON':'Hide signed certificate JSON';});
$("#refresh-audit").addEventListener("click",loadAudit);
Promise.all([loadCatalog(),loadMetrics()]).then(()=>loadScenario('NOMINAL')).catch(error=>{$("#scenario-summary").textContent=`Demo error: ${error.message}`;});
