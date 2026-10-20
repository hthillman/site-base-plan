"""Server-rendered HTML for the public site: tool, about, sources, privacy."""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path

from .config import DISCLAIMER
from .geocode import STATES
from .plugins import testfit_available

SAMPLES = Path(__file__).resolve().parent / "data" / "samples.json"
TIP_URL = os.environ.get("TIP_URL", "")  # optional tip / donation link shown after a run and in the footer
TIP_FOOTER = f' · <a href="{escape(TIP_URL)}" target="_blank" rel="noopener">Chip in for hosting</a>' if TIP_URL else ""

CSS = """
:root{--bg:#fbfaf7;--ink:#1c1c1a;--muted:#6a6963;--faint:#9a988f;--line:#e4e1d8;--field:#fff;--accent:#2f5d50;--accent-ink:#fff;
--alert:#b3261e;--caution:#9a5800;--missing:#6a1b9a;--info:#4a5a62}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--ink:#ebeae4;--muted:#a3a19a;--faint:#76746d;--line:#2e2d29;--field:#1c1c1a;
--accent:#86c0ab;--accent-ink:#0f1f19;--alert:#f08a84;--caution:#e8a64c;--missing:#c9a0e6;--info:#a7b8c0}}
[hidden]{display:none!important}*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
a{color:var(--accent);text-underline-offset:2px}
.wrap{max-width:720px;margin:0 auto;padding:0 16px}
header .wrap{display:flex;align-items:baseline;gap:20px;padding-top:22px;padding-bottom:6px;flex-wrap:wrap}
.brand{font-weight:650;color:var(--ink);text-decoration:none;letter-spacing:-.01em;margin-right:auto}
header nav{display:flex;gap:18px}header nav a{color:var(--muted);text-decoration:none;font-size:14px}
header nav a:hover,header nav a.on{color:var(--ink)}
main{padding:40px 0 24px}
h1{font-size:28px;line-height:1.2;letter-spacing:-.02em;margin:0 0 10px;font-weight:650}
h2{font-size:17px;margin:32px 0 8px}
.lede{color:var(--muted);margin:0 0 28px;max-width:600px}
.search{display:flex;gap:8px}
.search input{flex:1;min-width:0;font-size:17px;padding:13px 14px}
input,select,textarea{font:inherit;color:var(--ink);background:var(--field);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:-1px;border-color:transparent}
button{font:inherit;font-weight:600;background:var(--accent);color:var(--accent-ink);border:0;border-radius:8px;padding:0 18px;cursor:pointer;white-space:nowrap}
.search button{padding:0 20px}
button:disabled{opacity:.55;cursor:default}
button.quiet{background:transparent;color:var(--accent);border:1px solid var(--line);padding:8px 14px}
.opts{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:center;margin-top:12px;font-size:14px;color:var(--muted)}
.opts label{display:flex;align-items:center;gap:6px}
.opts input,.opts select{padding:4px 8px;font-size:14px;border-radius:6px}
.opts input[type=number]{width:72px}
.opts .check{color:var(--ink)}
.example{font-size:14px;color:var(--muted);margin:18px 0 0}
#out{margin-top:28px}
.result{border-top:1px solid var(--line);padding-top:22px}
.result h3{margin:0 0 4px;font-size:18px}
.dl{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 18px}
.dl a.primary{background:var(--accent);color:var(--accent-ink);text-decoration:none;font-weight:600;padding:10px 16px;border-radius:8px}
.dl a.secondary{padding:10px 4px;font-weight:500}
.tip{margin:-6px 0 18px}
.contents{font-size:14px;color:var(--muted);margin:0 0 20px;padding:0;list-style:none;display:grid;gap:3px}
.contents b{color:var(--ink);font-weight:600}
pre{margin:0;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);white-space:pre-wrap}
.flags{margin:0;padding:0;list-style:none}
.flag{display:grid;grid-template-columns:76px 1fr;gap:10px;padding:8px 0;border-top:1px solid var(--line);font-size:14.5px}
.flag:first-child{border-top:0}
.lvl{font-size:11px;font-weight:700;letter-spacing:.05em;padding-top:2px}
.alert{color:var(--alert)}.caution{color:var(--caution)}.missing{color:var(--missing)}.info{color:var(--info)}
.err{color:var(--alert)}
footer{margin-top:56px;border-top:1px solid var(--line);padding:22px 0 48px;font-size:13.5px;color:var(--muted)}
footer p{margin:0 0 10px}
footer details{margin:0 0 10px}
footer summary{cursor:pointer;color:var(--accent);display:inline}
footer summary::-webkit-details-marker{display:none}
footer form{display:grid;gap:8px;margin:10px 0 4px;max-width:480px}
footer .inline{display:flex;gap:8px}footer .inline input{flex:1;min-width:0}
footer textarea{min-height:80px;resize:vertical}
footer .fine{color:var(--faint);font-size:12.5px}
.ok{color:var(--accent)}
.linkbtn{background:none;border:0;color:var(--accent);padding:6px 0 0;font-weight:500;font-size:14px;cursor:pointer}
#also .search{margin-top:8px}#also input{font-size:15px;padding:10px 12px}
#also button{background:transparent;color:var(--muted);border:1px solid var(--line);padding:0 12px}
.next{margin:4px 0 22px;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.next b{font-size:14.5px}.next .note{display:block;margin:2px 0 10px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:transparent;color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-weight:500;font-size:14px}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.nextdetail{display:flex;gap:8px;margin-top:10px;max-width:520px}.nextdetail input{flex:1;min-width:0;font-size:14px;padding:7px 10px}
.nextdetail button{padding:0 14px;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px 10px 8px 0;border-top:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:13px}
.tablewrap{overflow-x:auto}
ul{padding-left:20px}li{margin:5px 0}
.note{font-size:14px;color:var(--muted)}
.hp{position:absolute;left:-9999px}
@media(max-width:560px){h1{font-size:24px}.search{flex-direction:column}.search button{padding:13px}main{padding-top:28px}}
"""

NAV = [("/", "Base plan"), ("/about", "About"), ("/sources", "Sources"), ("/privacy", "Privacy")]


def layout(title: str, active: str, body: str, script: str = "") -> str:
    links = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{escape(t)}</a>' for h, t in NAV[1:])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="Free planning-level site base plans from any US address: contours, slopes, soils, flood zones, wetlands and aerial, as DXF, PDF, SketchUp terrain, LandXML and GIS files.">
<meta name="color-scheme" content="light dark">
<style>{CSS}</style>
<script>window.va=window.va||function(){{(window.vaq=window.vaq||[]).push(arguments)}};</script>
<script defer src="/_vercel/insights/script.js"></script>
</head><body>
<header><div class="wrap"><a class="brand" href="/">Site Base Plan</a><nav>{links}</nav></div></header>
<main><div class="wrap">{body}{"" if active == "/" or not TIP_URL else f'<footer><p class="fine">Free, no account. <a href="{escape(TIP_URL)}" target="_blank" rel="noopener">Chip in for hosting</a> if it helped.</p></footer>'}</div></main>
{script}
</body></html>"""


def _samples() -> dict:
    try:
        return json.loads(SAMPLES.read_text())
    except Exception:  # noqa: BLE001
        return {}


def index(parcel_states: list[str], needs_code: bool) -> str:
    states_sorted = sorted(STATES.items(), key=lambda kv: kv[1])
    opts = '<option value="">Auto</option>' + "".join(f'<option value="{k}">{escape(v)}</option>' for k, v in states_sorted)
    s = _samples()
    example = (f'<p class="example">See an example: <a href="{escape(s["pdf"])}" target="_blank" rel="noopener">PDF</a> · '
               f'<a href="{escape(s["zip"])}">all files</a> for a waterfront lot in Olympia, WA.</p>') if s else ""
    from .parcel import county_sources

    from .config import load_config

    _cfg = load_config()
    layer_lines = "\n".join(f"{st.name} = {st.name}" for k, st in _cfg.layers.items() if not k.startswith("tf_"))
    n = len(parcel_states)
    county_txt = "".join(f" plus {len(v)} {STATES.get(k, k)} counties" for k, v in sorted(county_sources().items()))
    body = f"""
<h1>A site base plan from any US address</h1>
<p class="lede">Parcel line, contours, slopes, soils, flood zones, wetlands and aerial, ready for AutoCAD, SketchUp, Civil 3D and GIS.
Takes about a minute. Free, no account.</p>

<form id="gate" hidden class="search">
<input name="code" type="password" autocomplete="current-password" placeholder="Access code" required aria-label="Access code">
<button>Continue</button>
</form>
<p id="gateerr" class="err" hidden>That code didn't work.</p>

<form id="f">
<div class="search">
<input name="query" placeholder="Street address or parcel number" required autofocus aria-label="Street address or parcel number" autocomplete="street-address">
<button id="go">Build base plan</button>
</div>
<div id="also"></div>
<button type="button" class="linkbtn" id="addparcel">+ Add another parcel (combine up to 5 into one site)</button>
<div id="layermap" hidden>
<label class="note" style="display:block;margin:12px 0 4px">Your layer names: edit the right side of each line. Saved in this browser.</label>
<textarea name="layer_map" rows="10" spellcheck="false" style="width:100%;font:12.5px/1.5 ui-monospace,Menlo,monospace">{escape(layer_lines)}</textarea>
</div>
<div class="opts">
<label>Buffer <input name="buffer" type="number" value="100" min="0" max="1000" step="10"> ft</label>
<label>Contours <select name="interval"><option value="1">1 ft</option><option value="2" selected>2 ft</option><option value="5">5 ft</option></select></label>
<label>State <select name="state" aria-label="State (needed for parcel numbers)">{opts}</select></label>
<label id="countywrap" hidden>County <input name="county" placeholder="if needed" style="width:120px"></label>
<label>Layers <select name="layers" aria-label="CAD layer names"><option value="default">Default (SITE-*)</option><option value="ncs">NCS-style (V-PROP-LINE…)</option><option value="custom">Custom…</option></select></label>
<label id="tfwrap" class="check" hidden><input type="checkbox" name="testfit"> Apartment test fit (experimental, Thurston Co. WA)</label>
</div>
</form>
{example}

<div id="out"></div>

<footer>
<p>Planning-level data from public sources, not a survey. Parcel lines are tax lines, not legal boundaries.
Parcel lines are available in <a href="/about#coverage">{n} states{county_txt}</a>; elsewhere the plan is drawn around the address.</p>
<details id="fbd"><summary>Send feedback</summary>
<form id="fb">
<textarea name="message" required maxlength="4000" placeholder="What worked, what didn't, what should come next?" aria-label="Feedback"></textarea>
<div class="inline"><input name="email" type="email" maxlength="254" placeholder="Email, if you'd like a reply" aria-label="Email (optional)"><button>Send</button></div>
<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<span class="fine" id="fbmsg"></span>
</form></details>

<p class="fine">No cookies, no account. Files are deleted after 2 days. <a href="/privacy">Privacy</a> · <a href="/sources">Data sources</a>{TIP_FOOTER}</p>
</footer>
"""
    script = """<script>
const f=document.getElementById('f'),out=document.getElementById('out'),go=document.getElementById('go');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NEEDS_CODE=__NEEDS_CODE__;
const TESTFIT=__TESTFIT__;
if(TESTFIT&&new URLSearchParams(location.search).has('beta'))document.getElementById('tfwrap').hidden=false;
const looksApn=v=>/^[0-9A-Za-z][0-9A-Za-z.\\- ]{4,}$/.test(v)&&!/[A-Za-z]{3,}/.test(v)&&/[0-9]{5}/.test(v.replace(/\\D/g,''));
const alsoBox=document.getElementById('also');
document.getElementById('addparcel').onclick=()=>{if(alsoBox.children.length>=4)return;
 const row=document.createElement('div');row.className='search';
 row.innerHTML='<input name="also" placeholder="Another address or parcel number (same state)" aria-label="Another parcel"><button type="button" aria-label="Remove">Remove</button>';
 row.querySelector('button').onclick=()=>row.remove();alsoBox.appendChild(row);row.querySelector('input').focus();
 if(alsoBox.children.length>=4)document.getElementById('addparcel').hidden=true;};
const lm=document.getElementById('layermap');
const LS={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}}};
if(LS.get('sitekit-layers'))f.layers.value=LS.get('sitekit-layers');
if(LS.get('sitekit-layermap'))f.layer_map.value=LS.get('sitekit-layermap');
const syncLayers=()=>{lm.hidden=f.layers.value!=='custom';LS.set('sitekit-layers',f.layers.value)};
f.layers.addEventListener('change',syncLayers);syncLayers();
f.layer_map.addEventListener('input',()=>LS.set('sitekit-layermap',f.layer_map.value));
f.query.addEventListener('input',()=>{document.getElementById('countywrap').hidden=!looksApn(f.query.value.trim())});
const gate=document.getElementById('gate');let CODE='';
const getStored=()=>{try{return localStorage.getItem('sitekit-code')||''}catch(e){return ''}};
const setStored=v=>{try{v?localStorage.setItem('sitekit-code',v):localStorage.removeItem('sitekit-code')}catch(e){}};
async function tryCode(c){const r=await fetch('/api/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:c})});return r.ok}
function unlock(c){CODE=c;setStored(c);gate.hidden=true;f.hidden=false}
if(NEEDS_CODE){f.hidden=true;const s=getStored();
 (s?tryCode(s):Promise.resolve(false)).then(ok=>{if(ok)unlock(s);else{setStored('');gate.hidden=false;gate.code.focus()}});
 gate.onsubmit=async e=>{e.preventDefault();const c=gate.code.value.trim();
  if(await tryCode(c))unlock(c);else document.getElementById('gateerr').hidden=false}}
f.onsubmit=async e=>{e.preventDefault();go.disabled=true;go.textContent='Working…';
 const body=Object.fromEntries(new FormData(f));body.testfit=f.testfit.checked;body.code=CODE;
 body.also=[...alsoBox.querySelectorAll('input')].map(i=>i.value.trim()).filter(Boolean);
 out.innerHTML='<div class="result"><pre id="log">Starting…</pre></div>';
 const log=document.getElementById('log');const lines=[];
 try{
  const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(r.status===429)throw new Error('Too many runs from your network in the last few minutes. Give it a moment and try again.');
  if(!r.ok){const j=await r.json().catch(()=>({error:'Request failed ('+r.status+')'}));throw new Error(j.error)}
  const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
  for(;;){const {done,value}=await rd.read();if(done)break;buf+=dec.decode(value,{stream:true});
   let i;while((i=buf.indexOf('\\n'))>=0){const ev=JSON.parse(buf.slice(0,i));buf=buf.slice(i+1);handle(ev)}}
 }catch(err){out.innerHTML='<div class="result"><p class="err"><b>Couldn\\'t build this site.</b> '+esc(err.message)+'</p></div>'}
 go.disabled=false;go.textContent='Build base plan';
 function handle(ev){
  if(ev.log){lines.push(ev.log);log.textContent=lines.join('\\n')}
  if(ev.error){throw new Error(ev.error)}
  if(ev.result)render(ev.result)}
};
function render(j){
 const order={missing:0,alert:1,caution:2,info:3};
 const flags=j.flags.slice().sort((a,b)=>order[a.level]-order[b.level]).map(x=>'<li class="flag"><span class="lvl '+x.level+'">'+x.level.toUpperCase()+'</span><span>'+esc(x.text)+'</span></li>').join('');
 const pdf=j.files.pdf?'<a class="secondary" href="'+esc(j.files.pdf)+'" target="_blank" rel="noopener">Open PDF</a>':'';
 out.innerHTML='<div class="result"><h3>Ready</h3><span class="note">Built in '+j.seconds+' s. Links last 2 days.</span>'+
 '<div class="dl"><a class="primary" href="'+esc(j.files.zip)+'">Download files (.zip)</a>'+pdf+'</div>'+
 (TIP_URL?'<p class="note tip">If this saved you some time, you can <a href="'+TIP_URL+'" target="_blank" rel="noopener">chip in for hosting</a>.</p>':'')+
 '<ul class="contents">'+
 '<li><b>AutoCAD / Civil 3D</b> · site.dxf (open it directly), surface.xml (LandXML surface)</li>'+
 '<li><b>SketchUp</b> · File › Import › terrain.dae for textured 3D ground; site-local.dxf for linework (SketchUp Pro)</li>'+
 '<li><b>Rhino, Blender</b> · terrain.obj</li>'+
 '<li><b>GIS</b> · gis/*.geojson, dem.tif</li>'+
 '<li><b>Google Earth</b> · site.kml</li>'+
 '<li><b>Everyone</b> · site-summary.pdf, provenance.md (sources and dates), and HOW-TO-OPEN.txt</li></ul>'+
 nextRow()+
 '<ul class="flags">'+flags+'</ul></div>';
 wireNext(j.state);}
const TIP_URL="__TIP_URL__";
const NEXT=[["zoning","Zoning test fit (setbacks, max units, parking layout)"],["county","Parcel lines for my county"],["batch","Run many sites at once"],
 ["titleblock","My firm's title block and CAD standards"],["massing","3D building massing for SketchUp"],["other","Something else"]];
const ASK={zoning:"Which city or county?",county:"Which county and state?",batch:"Roughly how many sites, how often?",titleblock:"Anything specific? (optional)",massing:"What would you use it for? (optional)",other:"What should it do?"};
function nextRow(){return '<div class="next" id="next"><b>What should it do next?</b><span class="note">One click helps decide what gets built. No sign-up.</span><div class="chips">'+
 NEXT.map(([k,l])=>'<button type="button" class="chip" data-k="'+k+'">'+esc(l)+'</button>').join('')+'</div>'+
 '<form class="nextdetail" id="nextdetail" hidden><input name="detail" maxlength="300"><button>Send</button></form><span class="fine" id="nextmsg"></span></div>';}
function wireNext(state){const box=document.getElementById('next');if(!box)return;let cur=null,vid=null;
 const send=(choice,detail)=>fetch('/api/interest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({choice,detail,state,vote_id:vid})});
 box.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{cur=b.dataset.k;vid=Math.random().toString(36).slice(2,12);
  b.classList.add('on');send(cur,'');const f=document.getElementById('nextdetail');f.hidden=false;f.detail.value='';f.detail.placeholder=ASK[cur];f.detail.focus();
  const m=document.getElementById('nextmsg');m.textContent='Thanks, counted. Add a detail if you like.';m.className='fine ok';});
 document.getElementById('nextdetail').onsubmit=e=>{e.preventDefault();const v=e.target.detail.value.trim();if(!v||!cur)return;
  send(cur,v);e.target.hidden=true;document.getElementById('nextmsg').textContent='Got it, thanks.';};}
async function post(form,url,msgEl){const d=Object.fromEntries(new FormData(form));if(url==='/api/feedback')d.query=f.query.value;
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));
 msgEl.textContent=r.ok?'Thanks, got it.':(j.error||'Something went wrong.');msgEl.className=r.ok?'fine ok':'fine err';if(r.ok)form.reset()}
document.getElementById('fb').onsubmit=e=>{e.preventDefault();post(e.target,'/api/feedback',document.getElementById('fbmsg'))};
</script>""".replace("__NEEDS_CODE__", "true" if needs_code else "false").replace("__TESTFIT__", "true" if testfit_available() else "false").replace("__TIP_URL__", escape(TIP_URL))
    return layout("Site Base Plan", "/", body, script)


TF_SECTION_HTML = """<h2>Experimental: apartment test fit</h2>
<p>For parcels in Thurston County, WA (Olympia, Lacey, Tumwater and surrounding areas), an experimental mode looks up the zoning, removes setbacks
and buffers, and proposes walk-up apartment and parking layouts that meet the district's density, parking, coverage and height rules. Its rule
sheets are AI-extracted from the codes and not yet reviewed, so it's off by default.</p>
"""


def about(parcel_states: list[str]) -> str:
    from .parcel import all_sources
    from .plugins import testfit_available

    TF_SECTION = TF_SECTION_HTML if testfit_available() else ""
    TF_EXCEPT = " (except the experimental Thurston County, WA test fit)" if testfit_available() else ""

    src = all_sources()
    rows = "".join(
        f"<tr><td>{escape(STATES.get(k, k))}</td><td>{escape(src[k].coverage or 'Statewide')}</td><td>{escape(src[k].vintage or '')}</td></tr>"
        for k in sorted(src, key=lambda k: STATES.get(k, k)))
    from .parcel import county_sources

    csrc = county_sources()
    rows += "".join(
        f"<tr><td>{escape(STATES.get(k, k))} (by county)</td><td>{escape(', '.join(sorted(s.county for s in v.values())))}</td><td>{escape(next(iter(v.values())).vintage or '')}</td></tr>"
        for k, v in sorted(csrc.items()))
    missing = [STATES[k] for k in sorted(STATES, key=lambda k: STATES[k]) if k not in src and k not in csrc]
    body = f"""
<h1>About & coverage</h1>
<p class="sub">Site Base Plan turns an address into the first sheet of a site design: what's on the ground, what's regulated, and where the
data came from. It's built for landscape architects, civil engineers, architects and developers doing early site work.</p>

<h2>What you get</h2>
<ul>
<li><b>Base plan</b> in State Plane feet: parcel line, neighbouring parcels (ID, and owner and deed/plat reference where the county publishes them), road centerlines and names, approximate right-of-way, contours (LiDAR where available), slope bands, soils, FEMA flood zones, NWI wetlands, aerial underlay.</li>
<li><b>Files:</b> DXF (true coordinates, and a copy moved near 0,0 for SketchUp), textured 3D terrain (COLLADA for SketchUp, OBJ for Rhino/Blender), LandXML surface for Civil 3D, GeoJSON layers and a GeoTIFF elevation model for GIS, KML for Google Earth.</li>
<li><b>PDF summary:</b> scaled sheets with north arrow, scale bar and legend, plus a findings sheet that flags floodplain, wetlands, steep slopes and problem soils in plain language.</li>
<li><b>Provenance log:</b> every layer's source, date, resolution and known limits. Layers that fail to load are marked as missing, never silently dropped.</li>
</ul>

<h2>What it isn't</h2>
<ul>
<li>Not a survey. Parcel lines are assessor tax lines, typically 5-50 ft from the legal boundary.</li>
<li>No zoning, setbacks, easements, utilities or local critical-area maps{TF_EXCEPT}. Right-of-way is approximated from the gaps between tax parcels, not taken from recorded plats.</li>
<li>Not a wetland delineation, geotechnical report or flood determination.</li>
</ul>
<p class="note">{escape(DISCLAIMER)}</p>

<h2 id="coverage">Coverage</h2>
<p>Topography, soils, flood zones, wetlands and imagery cover all 50 states. Parcel lines come from free statewide parcel layers, which
{len(src)} states publish:</p>
<div class="tablewrap"><table><tr><th>State</th><th>Parcel coverage</th><th>Data date</th></tr>{rows}</table></div>
<p class="note">No free statewide parcel layer yet (the plan is drawn around the address instead): {escape(", ".join(missing))}.</p>
<p class="note"><b>Elevation:</b> USGS 3DEP. Most of the country has 1 m LiDAR; where it doesn't, the elevation model is 3-10 m and the tool raises the
contour interval to what the data supports (5 ft at 10 m) and says so.</p>

{TF_SECTION}
"""
    return layout("About & coverage · Site Base Plan", "/about", body)


def sources() -> str:
    from .parcel import all_sources

    national = [
        ("Topography", "USGS 3D Elevation Program (3DEP)", "Public domain (USGS)"),
        ("Soils", "USDA NRCS SSURGO via Soil Data Access", "Public domain (USDA)"),
        ("Flood zones", "FEMA National Flood Hazard Layer", "Public domain (FEMA)"),
        ("Wetlands", "U.S. Fish & Wildlife Service National Wetlands Inventory", "Public domain (USFWS)"),
        ("Road centerlines and names", "U.S. Census Bureau TIGER/Line via TIGERweb", "Public domain (U.S. Census Bureau)"),
        ("Aerial imagery", "Esri World Imagery (Vantor/Maxar, Earthstar Geographics, local contributors); USDA NAIP fallback",
         "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community. NAIP: public domain (USDA)"),
        ("Geocoding", "Esri World Geocoder, U.S. Census Geocoder, OpenStreetMap Nominatim", "Esri terms; Census public domain; © OpenStreetMap contributors (ODbL)"),
        ("State Plane zones", "NOAA NGS State Plane Coordinate System of 1983 (zone boundaries via Esri)", "Public domain (NOAA)"),
    ]
    nrows = "".join(f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td></tr>" for a, b, c in national)
    src = all_sources()
    prows = "".join(
        f"<tr><td>{escape(STATES.get(k, k))}</td><td>{escape(s.publisher or s.name)}</td><td>{escape(s.coverage)}</td>"
        f"<td>{escape(s.terms)}</td><td>{escape(str((s.verified or {}).get('date', '')))}</td></tr>"
        for k, s in sorted(src.items(), key=lambda kv: STATES.get(kv[0], kv[0])))
    body = f"""
<h1>Data sources & credits</h1>
<p class="sub">Everything comes from public services, queried live for each site. Each output's provenance log records exactly which
services answered, when, and with what resolution and date.</p>
<h2>National layers</h2>
<div class="tablewrap"><table><tr><th>Layer</th><th>Source</th><th>Terms / credit</th></tr>{nrows}</table></div>
<h2>Statewide parcel layers</h2>
<div class="tablewrap"><table><tr><th>State</th><th>Publisher</th><th>Coverage</th><th>Terms</th><th>Last verified</th></tr>{prows}</table></div>
<p class="note">Parcel layers are assessor tax-parcel compilations, not legal boundaries. Where a publisher limits commercial use, the outputs say so.</p>
"""
    return layout("Data sources · Site Base Plan", "/sources", body)


def privacy() -> str:
    body = """
<h1>Privacy</h1>
<p class="sub">Short version: no accounts, nothing sold, files deleted after two days.</p>
<h2>What happens to an address you enter</h2>
<ul>
<li>It's sent to geocoding services (Esri, the U.S. Census Bureau, OpenStreetMap) to find the location, and to public GIS services (USGS, USDA, FEMA, USFWS, state parcel servers) to fetch data around it.</li>
<li>The finished files are stored at an unlisted web link for <b>2 days</b>, then deleted. Anyone you share a link with can open it in that time.</li>
<li>Each run leaves an anonymous usage record (state, whether a parcel was found, run time, which data sources failed) so we can see what's working. It never includes the address or any location finer than the state.</li>
</ul>
<h2>Analytics</h2>
<p>Page views are counted with Vercel Web Analytics, which doesn't use cookies or track you across sites.</p>
<h2>"What should it do next?"</h2>
<p>After a run you can click an option to say what you'd like built next. That records the option, anything you type in the box,
and the run's state. Nothing that identifies you.</p>
<h2>Feedback</h2>
<p>Feedback you send is stored privately and read by the person who runs this site. If you include an email, it's used only to reply.
Never shared or sold. Ask through the feedback form to have it deleted.</p>
<h2>Professional use</h2>
<p>Outputs are planning-level. Verify conditions in the field and with a licensed surveyor before relying on them.</p>
"""
    return layout("Privacy · Site Base Plan", "/privacy", body)
