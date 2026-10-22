"""Server-rendered HTML for the public site: tool, about, sources, privacy."""

from __future__ import annotations

import importlib.util
import json
import os
from html import escape
from pathlib import Path

from .config import NO_BOUNDARY_STATES
from .config import DISCLAIMER
from .geocode import STATES
from .plugins import testfit_available

SAMPLES = Path(__file__).resolve().parent / "data" / "samples.json"
TIP_URL = os.environ.get("TIP_URL", "")  # optional tip / donation link shown after a run and in the footer
TIP_FOOTER = f' · <a href="{escape(TIP_URL)}" target="_blank" rel="noopener" data-ev="tip_click">Chip in for hosting</a>' if TIP_URL else ""
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")  # hosted site only; kept out of the open-source code
TERMS_ON = importlib.util.find_spec("sitekit.terms") is not None and importlib.import_module("sitekit.terms").READY
TERMS_LINK = ' · <a href="/terms">Terms</a>' if TERMS_ON else ""
TERMS_VERSION = importlib.import_module("sitekit.terms").TERMS_VERSION if TERMS_ON else ""
GATE_VERSION = f"{TERMS_VERSION}.2" if TERMS_ON else ""  # bump to show the first-build checkbox again after its wording changes
TERMS_GATE_TEXT = 'Basesheet does not provide professional advice, and its maps are not surveys or certified site plans. Verify important information with surveyors and your jurisdiction before you rely on it for design, permitting, purchase, financing, construction or any other decision. (<a href="/terms" target="_blank">Terms</a>)'
CONTACT_HTML = f'<a href="mailto:{escape(CONTACT_EMAIL)}">{escape(CONTACT_EMAIL)}</a>' if CONTACT_EMAIL else ""
FIRMS_FOOTER = ' · <a href="/firms" data-ev="firms_click">Using this at a firm?</a>' if os.environ.get("FIRMS_PAGE", "") not in ("", "0", "false") else ""

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
header nav{align-items:center}header a.gh{display:inline-flex;align-items:center;padding:2px;color:var(--muted)}header a.gh:hover{color:var(--ink)}
header .hright{display:flex;align-items:center;gap:10px;align-self:center}
header .menu{display:none;background:none;border:0;padding:6px;margin:-6px -6px -6px 0;color:var(--ink);cursor:pointer;line-height:0}
header .menu:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
@media(max-width:560px){header .wrap{align-items:center}header .menu{display:block}
header nav{display:none;order:3;flex-basis:100%;flex-direction:column;align-items:stretch;gap:0;margin-top:8px;border-top:1px solid var(--line)}
header.open nav{display:flex}header nav a{font-size:16px;padding:12px 0;border-bottom:1px solid var(--line)}}
main{padding:40px 0 24px}
h1{font-size:28px;line-height:1.2;letter-spacing:-.02em;margin:0 0 10px;font-weight:650}
h2{font-size:17px;margin:32px 0 8px}
h3{font-size:15px;margin:20px 0 4px}
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
.example{font-size:14px;color:var(--muted);margin:10px 0 0}
.meta{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin-top:12px;font-size:14px}
.meta .linkbtn{padding:0;font-size:14px}
.meta .sep{color:var(--faint)}
.meta .note{font-size:14px}
.panel{margin-top:10px;padding:12px 14px;border:1px solid var(--line);border-radius:8px;background:var(--field)}
.panel .opts{margin-top:0}
#apnrow{margin-top:10px}
footer .actions{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline;margin:0 0 6px}
footer .actions .linkbtn{padding:0;font-size:13.5px;font-weight:400}
footer .actions a{text-decoration:none}
footer .actions a:hover,footer .actions .linkbtn:hover{text-decoration:underline}
footer #fb{margin-top:10px}
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
footer{margin-top:44px;border-top:1px solid var(--line);padding:18px 0 40px;font-size:13.5px;color:var(--muted)}
footer p{margin:0 0 10px}
footer details{margin:0 0 10px}
footer summary{cursor:pointer;color:var(--accent);display:inline}
footer summary::-webkit-details-marker{display:none}
footer form{display:grid;gap:8px;margin:10px 0 4px;max-width:480px}
footer .inline{display:flex;gap:8px}footer .inline input{flex:1;min-width:0}
footer textarea{min-height:80px;resize:vertical}
footer .fine{color:var(--faint);font-size:12.5px}
.ok{color:var(--accent)}
#ff{display:grid;gap:14px;max-width:580px}
#ff label{display:grid;gap:4px;font-size:14px;color:var(--muted)}
#ff input:not([type=checkbox]),#ff select,#ff textarea{width:100%}
#ff textarea{min-height:80px;resize:vertical}
#ff button{padding:11px 18px}
#ff fieldset.checks label{display:flex;flex-direction:row;align-items:center;gap:6px;color:var(--ink);font-size:14.5px}
fieldset.checks{border:1px solid var(--line);border-radius:8px;padding:10px 14px;display:flex;flex-wrap:wrap;gap:8px 20px;margin:0}
fieldset.checks legend{font-size:13px;color:var(--muted);padding:0 4px}
fieldset.checks label{display:flex;flex-direction:row;align-items:center;gap:6px;color:var(--ink);font-size:14.5px}
fieldset.checks input{width:auto}
.panel .incl{margin-top:12px;font-size:14px}.panel .incl legend{font-size:12.5px}
.linkbtn{background:none;border:0;color:var(--accent);padding:6px 0 0;font-weight:500;font-size:14px;cursor:pointer}
#also .search{margin-top:8px}#also input{font-size:15px;padding:10px 12px}
#also button{background:transparent;color:var(--muted);border:1px solid var(--line);padding:0 12px}
.next{margin:4px 0 22px;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.next b{font-size:14.5px}.next .note{display:block;margin:2px 0 10px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:transparent;color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-weight:500;font-size:14px}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.nextdetail{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;max-width:620px}.nextdetail input{flex:1 1 200px;min-width:0;font-size:14px;padding:7px 10px}
.nextdetail button{padding:0 14px;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px 10px 8px 0;border-top:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:13px}
.tablewrap{overflow-x:auto}
ul{padding-left:20px}li{margin:5px 0}
.note{font-size:14px;color:var(--muted)}
.hp{position:absolute;left:-9999px}
.errline{margin:0 0 4px}
.picker{margin-top:16px;display:grid;gap:8px}.picker .note{margin:0}
#pickmap{height:340px;border-radius:8px;border:1px solid var(--line);overflow:hidden}
.pickbar{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;justify-content:space-between}
.pickbar button{padding:10px 16px}.pickbar button:disabled{opacity:.5}
@media(max-width:560px){#pickmap{height:300px}}
.tipline{margin:0;font-size:14px;color:var(--muted)}.tipline a{font-weight:600}
.rhead{display:grid;gap:2px}.rhead h3{font-size:20px;margin:0}
.dlwarn{margin:8px 0;padding:10px 12px;border:1px solid var(--alert);border-radius:8px;font-size:14px}.dlwarn .btns{display:inline-block;margin-top:8px}
.nsurvey{margin:10px 0 0;padding:8px 12px;border-left:4px solid var(--alert);background:color-mix(in srgb,var(--alert) 7%,transparent);font-size:14px}
.rtop{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:18px;margin-top:14px;align-items:start}
.rtop.nopv{grid-template-columns:1fr}
@media(max-width:640px){.rtop{grid-template-columns:1fr}}
.preview{display:block;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}
.preview img{display:block;width:100%;height:auto}
.ract{display:flex;flex-direction:column;gap:10px;min-width:0}
.btnp{background:var(--accent);color:var(--accent-ink);text-decoration:none;font-weight:600;padding:12px 16px;border-radius:8px;text-align:center}
.btns{text-align:center;padding:10px 16px;border:1px solid var(--line);border-radius:8px;text-decoration:none;font-weight:500}
.ract .note{margin:0}.linkbtn.inl{padding:0;font-size:inherit}
.ract .contents{margin:0}
.keep{padding:12px;border:1px solid var(--line);border-radius:8px;font-size:14px;display:grid;gap:8px;color:var(--muted);background:var(--field)}
.keep .quiet{justify-self:start;padding:8px 14px}
.keep .savef{display:flex;gap:8px;flex-wrap:wrap}
.sh{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:26px 0 8px;font-weight:600}
.callouts{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.callouts .co{padding:10px 12px;border-radius:8px;border:1px solid var(--line);border-left:3px solid var(--caution);background:var(--field);font-size:14.5px;color:var(--ink)}
.callouts .co.alert{border-left-color:var(--alert)}.callouts .co.missing{border-left-color:var(--missing)}
.facts{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
@media(max-width:560px){.facts{grid-template-columns:1fr 1fr}.fact{padding:9px 10px}.fact .fv{font-size:14.5px}}
.fact{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--field);display:grid;gap:2px;min-width:0}
.fact .fl{font-size:12px;color:var(--muted)}.fact .fv{font-weight:600;font-size:15.5px;overflow-wrap:anywhere}.fact .fs{font-size:12.5px;color:var(--faint)}
.fact.ok .fv{color:var(--accent)}.fact.warn .fv{color:var(--caution)}.fact.alert .fv{color:var(--alert)}
.more{margin-top:20px}.zrules .zone{margin-top:10px}.more summary{cursor:pointer;color:var(--accent);font-size:14px}.more .flags{margin-top:8px}
.rfoot{margin-top:30px;padding-top:16px;border-top:1px solid var(--line);display:grid;gap:12px}
.rfoot .vote{margin:0;padding:0;border:0}.rfoot .firmline{margin:0}.rfoot .note{margin:0}
.rsec{margin-top:26px}.rsec h4{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 6px;font-weight:600}
.flag.plain{grid-template-columns:1fr;color:var(--ink)}
.zone{border:1px solid var(--line);border-radius:8px;padding:12px 14px;background:var(--field);margin-bottom:8px}
.zone .zt{font-weight:600}.zone .zj{color:var(--muted);font-size:14px}
.zone ul{margin:6px 0 4px;padding-left:18px;font-size:14.5px}.zone li{margin:2px 0}
.zone .src{font-size:12.5px;color:var(--faint);margin:6px 0 0}
details.files summary{cursor:pointer;color:var(--accent);font-size:14px;margin-bottom:8px}
.firmline{margin:18px 0 0}
#savebox{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;flex-basis:100%}
.dl #savebox:empty{display:none}
.savef{display:flex;gap:8px;flex-wrap:wrap}.savef input:not(.hp){flex:1 1 220px;font-size:15px}.savef button{padding:9px 14px}
.plan{display:grid;gap:4px;padding:14px 0;border-top:1px solid var(--line)}
.caps{font-size:12.5px;line-height:1.55}
.tgate{margin:10px 0 0;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:14px}.tgate label{align-items:flex-start;gap:8px}.tgate input{margin-top:3px;flex:none}
.procard{border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:18px 0}.procard .price{font-size:22px;font-weight:700;margin:0 0 6px}
.btab{width:100%;border-collapse:collapse;font-size:13px;display:block;overflow-x:auto;margin-top:8px}.btab th,.btab td{text-align:left;padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}
.firmf{display:grid;gap:10px;max-width:560px}.firmf label{display:grid;gap:4px;font-size:14px}.firmf input,.firmf textarea,.firmf select{font-size:15px}
#logoprev{max-height:64px;max-width:200px;display:block;margin-top:4px}
.probar{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:14px 0;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.plan:first-child{border-top:0}
.plan .t{font-weight:600}.plan .acts{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;font-size:14px}
.plan .acts button{background:none;border:0;padding:0;color:var(--muted);font-weight:500;font-size:14px;cursor:pointer}
.plan .acts button.really{color:var(--alert)}
.vote{margin-top:28px;padding-top:16px;border-top:1px solid var(--line);font-size:14px}.vote .chips{margin-top:8px}
.vote .chip{font-size:13px;padding:5px 11px}
.answer{font-size:17px;line-height:1.6;margin:0 0 8px}
.crumbs{font-size:13.5px;margin:0 0 8px}.crumbs a{color:var(--muted)}
ol{padding-left:22px}
code{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
.cta{margin:32px 0 8px;padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--field)}
.cta p{margin:0 0 12px}.cta .btn{display:inline-block;background:var(--accent);color:var(--accent-ink);text-decoration:none;font-weight:600;padding:9px 16px;border-radius:8px}
th[scope],.tablewrap th{white-space:nowrap}
@media(max-width:560px){.meta .sep,footer .actions .sep{display:none}.meta,footer .actions{gap:6px 16px}h1{font-size:24px}.search{flex-direction:column}.search button{padding:13px}main{padding-top:28px}}
"""

REPO_URL = "https://github.com/hthillman/site-base-plan"
GITHUB_ICON = (f'<a class="gh" href="{REPO_URL}" target="_blank" rel="noopener" aria-label="Source code on GitHub" title="Open source on GitHub">'
               '<svg viewBox="0 0 16 16" width="17" height="17" aria-hidden="true" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 '
               '5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 '
               '1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 '
               '0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 '
               '3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg></a>')

NAV = [("/", "Base plan"), ("/about", "About"), ("/sources", "Sources"), ("/privacy", "Privacy")]


SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")  # canonical origin, e.g. https://basesheet.site
def zoning_counts() -> dict | None:
    """{"jurisdictions", "with_rules", "states"} where the hosted zoning registry is present, else None."""
    try:
        from .zoning.coverage_page import counts
    except ImportError:
        return None
    return counts()


def _zoning_phrase() -> str:
    z = zoning_counts()
    return f' Free zoning lookup in <a href="/zoning">{z["jurisdictions"]} cities and counties</a>.' if z else ""


ZONING_LINK = ' · <a href="/zoning">Zoning by city</a>' if importlib.util.find_spec("sitekit.zoning") else ""  # hosted build only

DEFAULT_DESCRIPTION = ("Free planning-level site context from public data for any US address: parcel lines, LiDAR contours, slopes, soils, "
                       "FEMA flood zones, wetlands and aerial, as DXF, SketchUp terrain, LandXML, GIS and PDF.")


def layout(title: str, active: str, body: str, script: str = "", description: str = DEFAULT_DESCRIPTION,
           jsonld: list[dict] | None = None) -> str:
    from .accounts import current_email

    from .accounts import can_sign_up

    nav = NAV[1:] + ([("/plans", "My plans")] if current_email() else [("/plans", "Sign in")] if can_sign_up() else [])
    links = "".join(f'<a href="{h}" class="{"on" if h == active else ""}">{escape(t)}</a>' for h, t in nav)
    url = f"{SITE_URL}{active}" if SITE_URL else active
    og_img = f"{SITE_URL}/og.png" if SITE_URL else "/og.png"
    ld = "".join(f'<script type="application/ld+json">{json.dumps(j, separators=(",", ":"))}</script>' for j in (jsonld or []))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<link rel="canonical" href="{escape(url)}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website"><meta property="og:site_name" content="Basesheet">
<meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(description)}">
<meta property="og:url" content="{escape(url)}"><meta property="og:image" content="{escape(og_img)}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="color-scheme" content="light dark">
<style>{CSS}</style>
{ld}
<script>window.va=window.va||function(){{(window.vaq=window.vaq||[]).push(arguments)}};</script>
<script defer src="/_vercel/insights/script.js"></script>
</head><body>
<header><div class="wrap"><a class="brand" href="/">Basesheet</a><nav id="sitenav" aria-label="Site">{links}</nav><div class="hright">{GITHUB_ICON}<button type="button" class="menu" aria-expanded="false" aria-controls="sitenav" aria-label="Menu" onclick="var h=this.closest('header'),o=h.classList.toggle('open');this.setAttribute('aria-expanded',o)"><svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true"><path d="M3 5.5h14M3 10h14M3 14.5h14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg></button></div></div></header>
<main><div class="wrap">{body}{"" if active == "/" else '<footer><p class="fine"><a href="/guides">Guides</a> · <a href="/parcels">Parcel data by state</a>' + ZONING_LINK + TERMS_LINK + (f' · Contact: {CONTACT_HTML}' if CONTACT_HTML else '') + '</p><p class="fine">Free, no account.' + (f' <a href="{escape(TIP_URL)}" target="_blank" rel="noopener" data-ev="tip_click">Chip in for hosting</a> if it helped.' if TIP_URL else "") + FIRMS_FOOTER + '</p></footer>'}</div></main>
{script}
</body></html>"""


def _samples() -> dict:
    try:
        return json.loads(SAMPLES.read_text())
    except Exception:  # noqa: BLE001
        return {}


def index(parcel_states: list[str], needs_code: bool, preload: dict | None = None) -> str:
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
    _cs = county_sources()
    county_txt = f" + {sum(len(v) for v in _cs.values())} counties in {len(_cs)} more" if _cs else ""
    actions = ['<button type="button" class="linkbtn" id="fbtoggle" aria-expanded="false" aria-controls="fb">Send feedback</button>']
    if FIRMS_PAGE:
        actions.append('<a href="/firms" data-ev="firms_click">Using this at a firm?</a>')
    if TIP_URL:
        actions.append(f'<a href="{escape(TIP_URL)}" target="_blank" rel="noopener" data-ev="tip_click">Chip in for hosting</a>')
    body = f"""
<h1>Site context from any US address</h1>
<p class="lede">Parcel lines, contours, slopes, soils, flood zones, wetlands, aerial and 3D massing from public data, ready for AutoCAD, SketchUp, Civil 3D and GIS.{_zoning_phrase()}
Not a survey. Free, no account.</p>

<form id="gate" hidden class="search">
<input name="code" type="password" autocomplete="current-password" placeholder="Access code" required aria-label="Access code">
<button>Continue</button>
</form>
<p id="gateerr" class="err" hidden>That code didn't work.</p>

<form id="f">
<div class="search">
<input name="query" placeholder="Street address, parcel number or coordinates" required autofocus aria-label="Street address, parcel number or coordinates" autocomplete="street-address">
<button id="go">Build base plan</button>
</div>
<div id="also"></div>
<div id="apnrow" class="opts" hidden>
<label>State <select name="state" aria-label="State (needed for parcel numbers)">{opts}</select></label>
<label>County <input name="county" placeholder="if needed" style="width:130px"></label>
</div>
<div class="meta">
<button type="button" class="linkbtn" id="addparcel">+ Add parcel</button>
<span class="sep" aria-hidden="true">·</span>
<span id="optsum" class="note"></span>
<button type="button" class="linkbtn" id="optbtn" aria-expanded="false" aria-controls="optpanel">Change</button>
</div>
{('<div id="tgate" class="tgate" hidden><label class="check"><input type="checkbox" id="tgcheck"> ' + TERMS_GATE_TEXT + '</label></div>') if TERMS_ON else ''}
<div id="optpanel" class="panel" hidden>
<div class="opts">
<label>Buffer <input name="buffer" type="number" value="100" min="0" max="1000" step="10"> ft</label>
<label>Contours <select name="interval"><option value="1">1 ft</option><option value="2" selected>2 ft</option><option value="5">5 ft</option></select></label>
<label>Layers <select name="layers" aria-label="CAD layer names"><option value="default">Default (SITE-*)</option><option value="ncs">NCS-style (V-PROP-LINE…)</option><option value="custom">Custom…</option></select></label>
<label id="tfwrap" class="check" hidden><input type="checkbox" name="testfit"> Apartment test fit <span id="tftag">(experimental, Thurston Co. WA)</span></label>
<p id="tfnote" class="note" hidden>Test fits are part of <a href="/pro">Basesheet Pro</a>.</p>
</div>
<fieldset class="checks incl"><legend>Include (fewer layers can be faster)</legend>
<label><input type="checkbox" id="inc-aerial" data-k="aerial" checked> Aerial</label>
<label><input type="checkbox" id="inc-soils" data-k="soils" checked> Soils</label>
<label><input type="checkbox" id="inc-flood" data-k="flood" checked> Flood zones</label>
<label><input type="checkbox" id="inc-wetland" data-k="wetland" checked> Wetlands</label>
<label><input type="checkbox" id="inc-massing" data-k="massing" checked> 3D massing</label>
</fieldset>
<div id="layermap" hidden>
<label class="note" style="display:block;margin:12px 0 4px">Your layer names: edit the right side of each line. Saved in this browser.</label>
<textarea name="layer_map" rows="10" spellcheck="false" style="width:100%;font:12.5px/1.5 ui-monospace,Menlo,monospace">{escape(layer_lines)}</textarea>
</div>
</div>
</form>
{example}

<div id="out"></div>

<footer>
<p class="fine">Planning-level public data, not a survey. Parcel lines in <a href="/about#coverage">{n} states{county_txt}</a>.</p>
<p class="fine"><a href="/guides">Guides</a> · <a href="/parcels">Parcel data by state</a>{ZONING_LINK}{TERMS_LINK}{(" · Contact: " + CONTACT_HTML) if CONTACT_HTML else ""}</p>
<p class="actions">{" <span class=\"sep\" aria-hidden=\"true\">·</span> ".join(actions)}</p>
<form id="fb" hidden>
<textarea name="message" required maxlength="4000" placeholder="What worked, what didn't, what should come next?" aria-label="Feedback"></textarea>
<div class="inline"><input name="email" type="email" maxlength="254" placeholder="Email, if you'd like a reply" aria-label="Email (optional)"><button>Send</button></div>
<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<span class="fine" id="fbmsg"></span>
</form>
</footer>
"""
    script = """<script>
const f=document.getElementById('f'),out=document.getElementById('out'),go=document.getElementById('go');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NEEDS_CODE=__NEEDS_CODE__;
const TESTFIT=__TESTFIT__;
const PRO_LIVE=__PROLIVE__;let IS_PRO=false;
if(TESTFIT&&(PRO_LIVE||new URLSearchParams(location.search).has('beta')))document.getElementById('tfwrap').hidden=false;
if(TESTFIT&&PRO_LIVE){document.getElementById('tftag').textContent='(Pro · Thurston Co. WA for now)';
 fetch('/api/billing/status').then(r=>r.json()).then(s=>{IS_PRO=!!s.pro}).catch(()=>{});
 f.testfit.addEventListener('change',()=>{if(f.testfit.checked&&!IS_PRO){f.testfit.checked=false;document.getElementById('tfnote').hidden=false}})}
const looksApn=v=>/^[0-9A-Za-z][0-9A-Za-z.\\- ]{4,}$/.test(v)&&!/[A-Za-z]{3,}/.test(v)&&/[0-9]{5}/.test(v.replace(/\\D/g,''));
const alsoBox=document.getElementById('also');
document.getElementById('addparcel').onclick=()=>{if(alsoBox.children.length>=4)return;
 const row=document.createElement('div');row.className='search';
 row.innerHTML='<input name="also" placeholder="Another parcel to combine into one site (same state, up to 5)" aria-label="Another parcel"><button type="button" aria-label="Remove">Remove</button>';
 row.querySelector('button').onclick=()=>row.remove();alsoBox.appendChild(row);row.querySelector('input').focus();
 if(alsoBox.children.length>=4)document.getElementById('addparcel').hidden=true;};
// Options: one summary line; the controls open in place. Non-default choices are remembered.
const sum=document.getElementById('optsum'),panel=document.getElementById('optpanel'),optbtn=document.getElementById('optbtn');
const LAYER_LABEL={default:'SITE-* layers',ncs:'NCS-style layers',custom:'custom layers'};
['buffer','interval'].forEach(n=>{const v=(()=>{try{return localStorage.getItem('sitekit-'+n)}catch(e){return null}})();if(v)f[n].value=v;});
const INC=[...document.querySelectorAll('.incl input')],INC_LABEL={aerial:'aerial',soils:'soils',flood:'flood',wetland:'wetlands',massing:'massing'};
try{(JSON.parse(localStorage.getItem('sitekit-skip')||'[]')).forEach(k=>{const c=INC.find(i=>i.dataset.k===k);if(c)c.checked=false})}catch(e){}
const skipped=()=>INC.filter(i=>!i.checked).map(i=>i.dataset.k);
INC.forEach(i=>i.addEventListener('change',()=>{updSum();try{localStorage.setItem('sitekit-skip',JSON.stringify(skipped()))}catch(e){}}));
function updSum(){const sk=skipped();sum.textContent=(f.buffer.value||0)+' ft buffer · '+f.interval.value+' ft contours · '+LAYER_LABEL[f.layers.value]+(sk.length?' · no '+sk.map(k=>INC_LABEL[k]).join(', '):'');}
['buffer','interval','layers'].forEach(n=>f[n].addEventListener('change',()=>{updSum();if(n!=='layers'){try{localStorage.setItem('sitekit-'+n,f[n].value)}catch(e){}}}));
f.buffer.addEventListener('input',updSum);
optbtn.onclick=()=>{const open=panel.hidden;panel.hidden=!open;optbtn.textContent=open?'Done':'Change';optbtn.setAttribute('aria-expanded',open)};
const fbt=document.getElementById('fbtoggle');
fbt.onclick=()=>{const fb=document.getElementById('fb');fb.hidden=!fb.hidden;fbt.setAttribute('aria-expanded',!fb.hidden);if(!fb.hidden)fb.message.focus()};
const lm=document.getElementById('layermap');
const LS={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}}};
if(LS.get('sitekit-layers'))f.layers.value=LS.get('sitekit-layers');
if(LS.get('sitekit-layermap'))f.layer_map.value=LS.get('sitekit-layermap');
const syncLayers=()=>{lm.hidden=f.layers.value!=='custom';LS.set('sitekit-layers',f.layers.value)};
f.layers.addEventListener('change',syncLayers);syncLayers();updSum();
f.layer_map.addEventListener('input',()=>LS.set('sitekit-layermap',f.layer_map.value));
f.query.addEventListener('input',()=>{document.getElementById('apnrow').hidden=!looksApn(f.query.value.trim())});
const gate=document.getElementById('gate');let CODE='';
const getStored=()=>{try{return localStorage.getItem('sitekit-code')||''}catch(e){return ''}};
const setStored=v=>{try{v?localStorage.setItem('sitekit-code',v):localStorage.removeItem('sitekit-code')}catch(e){}};
async function tryCode(c){const r=await fetch('/api/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:c})});return r.ok}
function unlock(c){CODE=c;setStored(c);gate.hidden=true;f.hidden=false}
if(NEEDS_CODE){f.hidden=true;const s=getStored();
 (s?tryCode(s):Promise.resolve(false)).then(ok=>{if(ok)unlock(s);else{setStored('');gate.hidden=false;gate.code.focus()}});
 gate.onsubmit=async e=>{e.preventDefault();const c=gate.code.value.trim();
  if(await tryCode(c))unlock(c);else document.getElementById('gateerr').hidden=false}}
// First build: a one-time checkbox (remembered per Terms version) before anything runs.
const TV='__TERMS_VERSION__',tgate=document.getElementById('tgate');let TOK=!TV||LS.get('sitekit-terms')===TV;
if(tgate)document.getElementById('tgcheck').onchange=e=>{if(!e.target.checked)return;TOK=true;LS.set('sitekit-terms',TV);tgate.hidden=true;f.requestSubmit()};
f.onsubmit=async e=>{e.preventDefault();if(!TOK){tgate.hidden=false;document.getElementById('tgcheck').focus();return}
 go.disabled=true;go.textContent='Working…';
 const body=Object.fromEntries(new FormData(f));body.testfit=f.testfit.checked;body.code=CODE;body.skip=skipped();track('run_start');
 const first=LS.get('sitekit-first');body.prior=+(LS.get('sitekit-plans')||0);body.since=first?Math.max(0,Math.round((Date.now()-Date.parse(first))/864e5)):null;
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
 }catch(err){track('run_error');out.innerHTML='<div class="result"><p class="errline"><b class="err">Couldn\\'t build this site.</b> '+esc(err.message)+'</p>'+
  ((err.suggestions||[]).length?'<div class="chips">'+err.suggestions.map(s=>'<button type="button" class="chip sugg">'+esc(s)+'</button>').join('')+'</div>':'')+
  (err.pick?'<div class="picker"><p class="note"><b>Can’t find it?</b> Click the site on the map, then build.</p><div id="pickmap" role="application" aria-label="Map: click to choose the site"></div>'+
   '<div class="pickbar"><span id="pickll" class="note">No point chosen yet.</span><button type="button" id="pickgo" disabled>Build base plan here</button></div></div>':'')+'</div>';
  out.querySelectorAll('.sugg').forEach(b=>b.onclick=()=>{f.query.value=b.textContent;f.requestSubmit()});
  if(err.pick)openPicker(err.near)}
 go.disabled=false;go.textContent='Build base plan';
 function handle(ev){
  if(ev.log){lines.push(ev.log);log.textContent=lines.join('\\n')}
  if(ev.error){const e=new Error(ev.error);e.suggestions=ev.suggestions||[];e.near=ev.near||null;e.pick=!!ev.pick;throw e}
  if(ev.result){LS.set('sitekit-plans',String(+(LS.get('sitekit-plans')||0)+1));if(!LS.get('sitekit-first'))LS.set('sitekit-first',new Date().toISOString().slice(0,10));render(ev.result)}}
};
function render(j){
 const order={missing:0,alert:1,caution:2,info:3};
 const zcovered=j.zoning&&j.zoning.details&&j.zoning.details.length;
 const fl=j.flags.filter(x=>x.kind!=='zoning'||!zcovered);
 const warn=fl.filter(x=>x.level!=='info').sort((a,b)=>order[a.level]-order[b.level]);
 const info=fl.filter(x=>x.level==='info');
 const pv=j.files.preview,pdf=j.files.pdf;
 const facts=(j.facts||[]).map(f=>'<div class="fact '+esc(f.tone)+'"><span class="fl">'+esc(f.label)+'</span><span class="fv">'+esc(f.value)+'</span>'+(f.sub?'<span class="fs">'+esc(f.sub)+'</span>':'')+'</div>').join('');
 out.innerHTML='<div class="result">'+
 '<div class="rhead"><h3>Base plan ready</h3><span class="note">'+esc(j.title||'')+' · built in '+j.seconds+' s</span></div>'+
  '<p class="nsurvey"><b>Not a survey or a certified site plan. Not for permit submission.</b> Parcel lines are assessor tax lines, not property boundaries, and areas are approximate. Before relying on any line, area or elevation, <a href="/guides/when-you-need-a-surveyor">hire a licensed land surveyor</a>, and confirm zoning and flood zones with the jurisdiction.</p>'+
 '<div class="rtop'+(pv?'':' nopv')+'">'+
  (pv?'<a class="preview" href="'+esc(pdf||pv)+'" target="_blank" rel="noopener" title="Open the PDF" data-ev="open_pdf"><img src="'+esc(pv)+'" alt="Preview of the base plan sheet"></a>':'')+
  '<div class="ract">'+
   '<a class="btnp" href="'+esc(j.files.zip)+'" data-ev="download_zip">Download files (.zip)</a>'+
   '<p class="dlwarn" id="dlwarn" hidden><b>Before you download:</b> these CAD and GIS files are not survey data or a certified site plan. Lines and areas come from public GIS and can be tens of feet off. Get a survey before design, fencing, grading or permits that depend on them. <a class="btns" id="dlgo" href="'+esc(j.files.zip)+'">I understand, download</a></p>'+
   (pdf?'<a class="btns" href="'+esc(pdf)+'" target="_blank" rel="noopener" data-ev="open_pdf">Open the PDF</a>':'')+
   (TIP_URL?'<p class="tipline">Saved you an hour? <a href="'+TIP_URL+'" target="_blank" rel="noopener" data-ev="tip_click">Chip in for hosting</a></p>':'')+
   '<p class="note">CAD, SketchUp, Civil 3D, GIS and PDF in one zip. <button type="button" class="linkbtn inl" id="whatsin" aria-expanded="false" aria-controls="contents">What’s inside</button></p>'+
   '<ul class="contents" id="contents" hidden>'+
   '<li><b>AutoCAD / Civil 3D</b> · site.dxf, surface.xml (LandXML)</li>'+
   '<li><b>SketchUp</b> · File › Import › terrain.dae; site-local.dxf for linework</li>'+
   '<li><b>Rhino, Blender</b> · terrain.obj</li>'+
   '<li><b>GIS</b> · gis/*.geojson, dem.tif</li>'+
   '<li><b>Google Earth</b> · site.kml</li>'+
   '<li><b>Everyone</b> · site-summary.pdf, provenance.md, HOW-TO-OPEN.txt</li></ul>'+
   '<div class="keep" id="savebox"><span>Download links expire in 2 days.</span></div>'+
  '</div></div>'+
 (warn.length?'<h4 class="sh">Needs a look</h4><ul class="callouts">'+warn.map(x=>'<li class="co '+x.level+'">'+esc(x.text)+'</li>').join('')+'</ul>':'')+
 (facts?'<h4 class="sh">At a glance</h4><div class="facts">'+facts+'</div>':'')+
 zoningBox(j.zoning)+
 '<details class="more"><summary>All findings and sources ('+info.length+')</summary><ul class="flags">'+
  info.map(x=>'<li class="flag plain"><span>'+esc(x.text)+'</span></li>').join('')+
  '</ul><p class="note">Every layer’s source, date and limits are in provenance.md inside the zip.</p></details>'+
 '<div class="rfoot">'+nextRow(j.zoning)+
  (PRO?'<p class="note firmline">Using this at a firm? I’m working with a few offices on test fits, title blocks and batch runs. <a href="/firms" data-ev="firms_click">Tell me what you need</a>.</p>':'')+
 '</div></div>';
 const wi=document.getElementById('whatsin');wi.onclick=()=>{const c=document.getElementById('contents');c.hidden=!c.hidden;wi.setAttribute('aria-expanded',!c.hidden)};
 RUN_STATE=j.state||'';track('run_done');
 wireNext(j.state);wireSave(j);wireDl();
 try{out.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'})}catch(e){}}
const TIP_URL="__TIP_URL__";
function loadLeaflet(){if(window.L)return Promise.resolve();return new Promise((ok,bad)=>{
 const c=document.createElement('link');c.rel='stylesheet';c.href='https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';document.head.appendChild(c);
 const s=document.createElement('script');s.src='https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';s.onload=ok;s.onerror=bad;document.head.appendChild(s)})}
async function openPicker(near){
 try{await loadLeaflet()}catch(e){document.getElementById('pickll').textContent='The map didn’t load. Paste coordinates (lat, lon) from any map instead.';return}
 const m=L.map('pickmap',{scrollWheelZoom:true}).setView(near?[near.lat,near.lon]:[39.5,-98.35],near?Math.min(near.zoom,18):4);
 const E='https://server.arcgisonline.com/ArcGIS/rest/services/';
 L.tileLayer(E+'World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Imagery: Esri, Vantor, Earthstar Geographics'}).addTo(m);
 L.tileLayer(E+'Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(m);
 L.tileLayer(E+'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',{maxZoom:19}).addTo(m);
 let mk=null,pt=null;const go=document.getElementById('pickgo'),ll=document.getElementById('pickll');
 m.on('click',e=>{pt=e.latlng;if(mk)mk.setLatLng(pt);else mk=L.circleMarker(pt,{radius:8,color:'#fff',weight:2,fillColor:'#d6262a',fillOpacity:1}).addTo(m);
  ll.textContent=pt.lat.toFixed(5)+', '+pt.lng.toFixed(5);go.disabled=false});
 go.onclick=()=>{if(!pt)return;track('map_pick');f.query.value=pt.lat.toFixed(6)+', '+pt.lng.toFixed(6);f.requestSubmit()};
 setTimeout(()=>m.invalidateSize(),50)}
let RUN_STATE='';
function track(name,extra){const data={state:RUN_STATE,...(extra||{})};
 try{window.va&&window.va('event',{name,data})}catch(e){}
 try{const b=JSON.stringify({e:name,...data});navigator.sendBeacon?navigator.sendBeacon('/api/event',new Blob([b],{type:'application/json'})):fetch('/api/event',{method:'POST',headers:{'Content-Type':'application/json'},body:b,keepalive:true})}catch(e){}}
document.addEventListener('click',e=>{const a=e.target.closest('[data-ev]');if(a)track(a.dataset.ev)},true);
const PRO=__PRO__;
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
function wireDl(){const a=out.querySelector('[data-ev=download_zip]'),w=document.getElementById('dlwarn'),go=document.getElementById('dlgo');if(!a||!w||!go)return;
 a.addEventListener('click',e=>{if(LS.get('sitekit-dlwarn'))return;e.preventDefault();e.stopImmediatePropagation();w.hidden=false;go.focus()},true);
 go.addEventListener('click',()=>{LS.set('sitekit-dlwarn','1');w.hidden=true})}
async function wireSave(j){const box=document.getElementById('savebox');if(!box||!j.run_id)return;
 let me={};try{me=await (await fetch('/api/me')).json()}catch(e){return}
 if(!me.email&&!me.can_sign_up)return;
 const plan={run_id:j.run_id,title:j.title,files:j.files,state:j.state};
 box.innerHTML='<span>Download links expire in 2 days. Save the plan to keep its files.</span><button type="button" class="quiet" id="savebtn">Save to my plans</button>';
 document.getElementById('savebtn').onclick=async()=>{track('save_click');
  if(me.email){box.textContent='Saving…';
   const r=await fetch('/api/plans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(plan)});const k=await r.json().catch(()=>({}));
   box.innerHTML=r.ok?'<span class="ok">Saved.</span> <a href="/plans">My plans</a>':'<span class="err">'+esc(k.error||'Couldn\\'t save.')+'</span>';return}
  box.innerHTML='<form id="sf" class="savef"><input type="email" name="email" required maxlength="254" placeholder="Your email" aria-label="Email"><input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true"><button>Email me a link</button></form>'+
   '<span class="fine" id="sfmsg">Click the link in the email and this plan is saved. No password.</span>';
  const sf=document.getElementById('sf');sf.email.focus();
  sf.onsubmit=async e=>{e.preventDefault();const m=document.getElementById('sfmsg');
   const r=await fetch('/api/auth/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:sf.email.value,website:sf.website.value,save:plan})});
   const k=await r.json().catch(()=>({}));
   if(r.ok){track('save_link_sent');sf.hidden=true;m.className='fine ok';m.innerHTML='Check your email for the sign-in link. It works for 30 minutes.'+(k.dev_link?' <a href="'+esc(k.dev_link)+'">Dev: open link</a>':'')}
   else{m.className='fine err';m.textContent=k.error||'Something went wrong.'}};};}
function zoningBox(z){if(!z||!(z.details||[]).length)return '';
 const zs=z.details.map(d=>'<div class="zone"><div><span class="zt">'+esc(d.zone)+' '+esc(d.name||'')+'</span> <span class="zj">· '+esc(d.jurisdiction)+
  (d.share?' · '+Math.round(d.share*100)+'% of parcel':'')+(d.at_point?' · at the address point':'')+'</span></div>'+
  (d.facts.length?'<ul>'+d.facts.map(f=>'<li>'+esc(cap(f))+'</li>').join('')+'</ul>':'<p class="note">No rule sheet for this district yet.</p>')+
  (d.source?'<p class="src">'+esc(d.source)+' Base district only; overlays and recent amendments can change these. Confirm with the jurisdiction.</p>':'')+'</div>').join('');
 return '<details class="more zrules"><summary>Zoning rules: '+esc(z.details.map(d=>d.zone).join(', '))+'</summary>'+zs+'</details>';}
const NEXT=[["zoning","Zoning test fit (setbacks, max units, parking layout)"],["county","Parcel lines for my county"],["batch","Run many sites at once"],
 ["titleblock","My firm's title block and CAD standards"],["massing","3D building massing for SketchUp"],["other","Something else"]];
const ASK={zoning:"Which city or county?",county:"Which county and state?",batch:"Roughly how many sites, how often?",titleblock:"Anything specific? (optional)",massing:"What would you use it for? (optional)",other:"What should it do?"};
function nextRow(z){const covered=z&&(z.details||[]).some(d=>d.facts.length);
 return '<div class="vote" id="next"><b>What features should we add next?</b><div class="chips">'+
 NEXT.filter(([k])=>!(covered&&k==='zoning')).map(([k,l])=>'<button type="button" class="chip" data-k="'+k+'">'+esc(l)+'</button>').join('')+'</div>'+
 '<form class="nextdetail" id="nextdetail" hidden><input name="detail" maxlength="300" aria-label="Detail"><input name="email" type="email" maxlength="254" placeholder="Email me when it ships (optional)" aria-label="Email me when it ships (optional)"><button>Send</button></form><span class="fine" id="nextmsg"></span></div>';}
function wireNext(state){const box=document.getElementById('next');if(!box)return;let cur=null,vid=null;
 const send=(choice,detail,email)=>fetch('/api/interest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({choice,detail,email:email||'',state,vote_id:vid})});
 box.querySelectorAll('.chip').forEach(b=>b.onclick=()=>{cur=b.dataset.k;vid=Math.random().toString(36).slice(2,12);
  b.classList.add('on');send(cur,'');track('vote',{choice:cur});const f=document.getElementById('nextdetail');f.hidden=false;f.detail.value='';f.detail.placeholder=ASK[cur];f.detail.focus();
  const m=document.getElementById('nextmsg');m.textContent='Thanks, counted. Add a detail if you like.';m.className='fine ok';});
 document.getElementById('nextdetail').onsubmit=async e=>{e.preventDefault();const v=e.target.detail.value.trim(),em=e.target.email.value.trim();if((!v&&!em)||!cur)return;
  const r=await send(cur,v,em);const k=await r.json().catch(()=>({}));const m=document.getElementById('nextmsg');
  if(!r.ok){m.textContent=k.error||'Something went wrong.';m.className='fine err';return}
  if(em)track('vote_email',{choice:cur});e.target.hidden=true;m.className='fine ok';m.textContent=em?'Got it. I’ll email you when it ships.':'Got it, thanks.';};}
async function post(form,url,msgEl){const d=Object.fromEntries(new FormData(form));if(url==='/api/feedback')d.query=f.query.value;
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));
 msgEl.textContent=r.ok?'Thanks, got it.':(j.error||'Something went wrong.');msgEl.className=r.ok?'fine ok':'fine err';if(r.ok)form.reset()}
document.getElementById('fb').onsubmit=e=>{e.preventDefault();post(e.target,'/api/feedback',document.getElementById('fbmsg'))};
const PRELOAD=__PRELOAD__;
if(PRELOAD){if(PRELOAD.expired){out.innerHTML='<div class="result"><p class="errline"><b>This base plan has expired.</b> Files are kept for 2 days. Enter the address above to build it again; it takes about 30 seconds.</p></div>'}
 else{f.query.value=PRELOAD.title||'';render(PRELOAD)}}
</script>""".replace("__TERMS_VERSION__", GATE_VERSION).replace("__PRELOAD__", json.dumps(preload).replace("</", "<\\/") if preload else "null").replace("__NEEDS_CODE__", "true" if needs_code else "false").replace("__TESTFIT__", "true" if testfit_available() else "false").replace("__TIP_URL__", escape(TIP_URL)).replace("__PRO__", "true" if FIRMS_PAGE else "false").replace("__PROLIVE__", "true" if pro_live() else "false")
    app_ld = {
        "@context": "https://schema.org", "@type": "WebApplication", "name": "Basesheet",
        "url": SITE_URL or "/", "applicationCategory": "DesignApplication", "operatingSystem": "Web browser",
        "description": DEFAULT_DESCRIPTION, "isAccessibleForFree": True,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "featureList": ["Parcel lines from statewide and county parcel data", "LiDAR contours and slope analysis",
                        "NRCS soils, FEMA flood zones and NWI wetlands", "Road centerlines, adjacent parcels and approximate right-of-way",
                        "DXF for AutoCAD, COLLADA terrain for SketchUp, LandXML for Civil 3D, GeoJSON and GeoTIFF for GIS, KML, PDF",
                        "Multi-parcel sites and custom CAD layer names"],
        "author": {"@type": "Person", "name": "Hunter Hillman"},
        "license": "https://opensource.org/licenses/MIT", "sameAs": [REPO_URL],
    }
    return layout("Basesheet: free site context from any US address (DXF, SketchUp, Civil 3D, GIS)", "/", body, script,
                  jsonld=[app_ld, {"@context": "https://schema.org", "@type": "WebSite", "name": "Basesheet", "url": SITE_URL or "/"}])


TF_SECTION_HTML = """<h2>Experimental: apartment test fit</h2>
<p>For parcels in Thurston County, WA (Olympia, Lacey, Tumwater and surrounding areas), an experimental mode looks up the zoning, removes setbacks
and buffers, and proposes walk-up apartment and parking layouts that meet the district's density, parking, coverage and height rules. Its rule
sheets are AI-extracted from the codes and not yet reviewed, so it's off by default.</p>
"""


def faq_items() -> list[tuple[str, str]]:
    """Visible FAQ on the About page; the FAQPage JSON-LD is built from the same list."""
    from .parcel import all_sources, county_sources

    n = len(all_sources())
    counties = sum(len(v) for v in county_sources().values())
    cstates = len(county_sources())
    return [
        ("How do I get a base plan for a property?",
         "Type the street address (or a parcel number and state) on the home page and select Build base plan. In about 15 to 30 "
         "seconds you get a zip with CAD, 3D, GIS and PDF files for the parcel plus a buffer around it (100 ft by default)."),
        ("What files do I get?",
         "A DXF in State Plane feet for AutoCAD and Civil 3D, a copy moved near 0,0 for SketchUp, textured 3D terrain (COLLADA "
         "and OBJ), a LandXML surface, GeoJSON layers and a GeoTIFF elevation model for GIS, a KML for Google Earth, and a PDF "
         "with scaled sheets and plain-language findings about floodplain, wetlands, steep slopes and soils."),
        ("Where does the data come from?",
         "Public sources, queried live for each site: USGS 3DEP LiDAR for topography, USDA NRCS SSURGO for soils, the FEMA "
         "National Flood Hazard Layer, the USFWS National Wetlands Inventory, Census TIGER roads, Esri World Imagery, and "
         f"free statewide or county parcel layers. Every download includes a provenance file with each layer's source, date and resolution."),
        ("Is this a survey?",
         "No. It's planning-level data for early site work. Parcel lines are assessor tax lines, often 5 to 50 ft from the legal "
         "boundary, and wetlands and flood zones are screening maps. Use a licensed land surveyor and the appropriate specialists "
         "before design decisions that depend on exact boundaries or conditions."),
        ("Why doesn't it show property lines in California?", NO_BOUNDARY_STATES["CA"]),
        ("Can I use it for a permit application?",
         "No. Basesheet doesn't make site plans for permits, and its files are marked not for permit submission. Where a permit "
         "needs a site plan, use a survey or a plan from the licensed professional your jurisdiction requires. Basesheet is for "
         "early design, feasibility and context before that work."),
        ("Which states have parcel lines?",
         f"{n} states publish a free statewide parcel layer it can use. In {cstates} more states it uses county layers: "
         f"{counties} counties so far, mostly the larger metro areas. Elsewhere the plan is drawn around the address without a "
         "parcel line; everything else still works. The coverage table above lists each state and county."),
        ("How accurate are the contours?",
         "They come from the best USGS 3DEP elevation data at the site: usually 1 m LiDAR, sometimes older 3 m LiDAR or a 10 m "
         "model where there's no LiDAR. The tool raises the contour interval to what the data supports (5 ft at 10 m) and says so."),
        ("Can I use it with SketchUp?",
         "Yes. In SketchUp, use File, Import, choose COLLADA (.dae) and pick terrain.dae for textured 3D ground with the parcel "
         "line on it and the existing buildings as simple 3D blocks (plus the zoning envelope where zoning rules exist). "
         "site-local.dxf has the linework in the same coordinates for SketchUp Pro."),
        ("Does it cost anything? Is it open source?",
         "It's free with no account. The base plan code and parcel source list are open source under the MIT license on GitHub."),
    ]


def faq_jsonld() -> dict:
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq_items()]}


def _about_zoning() -> str:
    z = zoning_counts()
    if not z:
        return ""
    return (f'<p class="note"><b>Zoning:</b> the zoning district for addresses in {z["jurisdictions"]} cities and counties across {z["states"]} states, '
            f'from each jurisdiction\'s own zoning map, with a rule summary (setbacks, height, density, parking) in {z["with_rules"]} of them. '
            f'Rule sheets cite the code and are marked draft until checked by a professional. <a href="/zoning">Full list</a>.</p>')


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
        f"<tr><td>{escape(STATES.get(k, k))} (by county)</td><td>{escape(', '.join(sorted(s.county for s in v.values())))}</td><td>Varies by county</td></tr>"
        for k, v in sorted(csrc.items(), key=lambda kv: STATES.get(kv[0], kv[0])))
    missing = [STATES[k] for k in sorted(STATES, key=lambda k: STATES[k]) if k not in src and k not in csrc]
    body = f"""
<h1>About & coverage</h1>
<p class="sub">Basesheet turns an address into the first sheet of a site design: what's on the ground, what's regulated, and where the
data came from. It's built for landscape architects, civil engineers, architects and developers doing early site work.</p>

<h2>What you get</h2>
<ul>
<li><b>Base plan</b> in State Plane feet: parcel line, neighboring parcels (ID, and owner and deed/plat reference where the county publishes them), road centerlines and names, approximate right-of-way, existing building footprints, contours (LiDAR where available), slope bands, soils, FEMA flood zones, NWI wetlands, aerial underlay.</li>
<li><b>3D massing:</b> existing buildings as flat-roofed blocks at estimated heights, sitting on the LiDAR terrain, in the SketchUp, OBJ, DXF and KML files. Where zoning rules exist (Thurston County, WA so far), the zoning envelope too: the buildable area after setbacks, up to the height limit.</li>
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

<h2>Open source</h2>
<p>The base plan code and the parcel source list are open source (MIT) at
<a href="https://github.com/hthillman/site-base-plan">github.com/hthillman/site-base-plan</a>. If your county publishes parcels
and isn't covered, you can add it: it's one small file. See the contributing guide there.</p>

<h2 id="assistants">Use it from ChatGPT or Claude</h2>
<p>Basesheet is also an MCP server, so AI assistants can build a base plan for you in the chat and hand you the link to the files.
The server address is <code>{SITE_URL or ""}/mcp</code>.</p>
<ul>
<li><b>Claude:</b> Settings → Connectors → Add custom connector, and paste the address. Then ask something like "Build a base plan for 123 Main St, Springfield, IL".</li>
<li><b>Other MCP clients</b> (Cursor, VS Code and others): add it as a remote MCP server over HTTP. No sign-in or key needed.</li>
</ul>

<h2 id="coverage">Coverage</h2>
<p>Topography, soils, flood zones, wetlands and imagery cover all 50 states. Parcel lines come from free statewide parcel layers, which
{len(src)} states publish:</p>
<div class="tablewrap"><table><tr><th>State</th><th>Parcel coverage</th><th>Data date</th></tr>{rows}</table></div>
<p class="note">No free statewide parcel layer yet (the plan is drawn around the address instead): {escape(", ".join(missing))}.</p>
<p class="note"><b>Elevation:</b> USGS 3DEP. Most of the country has 1 m LiDAR; where it doesn't, the elevation model is 3-10 m and the tool raises the
contour interval to what the data supports (5 ft at 10 m) and says so.</p>
{_about_zoning()}

{TF_SECTION}

{f'<h2 id="contact">Contact</h2><p>Questions, a bug, or a county whose parcels you want added: email {CONTACT_HTML}, or use Send feedback on the home page.</p>' if CONTACT_HTML else ''}
<h2 id="faq">Common questions</h2>
{"".join(f'<h3>{escape(q)}</h3><p>{escape(ans)}</p>' for q, ans in faq_items())}
"""
    return layout("About, coverage and FAQ · Basesheet", "/about", body,
                  description="What Basesheet makes, what it isn't, which states have parcel lines, and answers to common questions about data sources, accuracy and file formats.",
                  jsonld=[faq_jsonld()])


def sources() -> str:
    from .guides import state_slug
    from .parcel import all_sources

    national = [
        ("Topography", "USGS 3D Elevation Program (3DEP)", "Public domain (USGS)"),
        ("Soils", "USDA NRCS SSURGO via Soil Data Access", "Public domain (USDA)"),
        ("Flood zones", "FEMA National Flood Hazard Layer", "Public domain (FEMA)"),
        ("Wetlands", "U.S. Fish & Wildlife Service National Wetlands Inventory", "Public domain (USFWS)"),
        ("Road centerlines and names", "U.S. Census Bureau TIGER/Line via TIGERweb", "Public domain (U.S. Census Bureau)"),
        ("Topography backup (when 3DEP doesn't answer)", "AWS Terrain Tiles (Mapzen terrarium), built mostly from USGS NED", "Public; credit Mapzen and USGS"),
        ("Building outlines", "County and city planimetric layers where published (list on each state page); elsewhere Microsoft US Building Footprints, via Esri", "Per publisher; Microsoft data under ODbL 1.0"),
        ("Building heights", "FEMA / Oak Ridge National Laboratory USA Structures, via Esri, where the local layer has none", "CC BY 4.0; credit FEMA, ORNL, Esri"),
        ("Aerial imagery", "Esri World Imagery (Vantor/Maxar, Earthstar Geographics, local contributors); USDA NAIP fallback",
         "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community. NAIP: public domain (USDA)"),
        ("Geocoding", "Esri World Geocoder, U.S. Census Geocoder, OpenStreetMap Nominatim", "Esri terms; Census public domain; © OpenStreetMap contributors (ODbL)"),
        ("State Plane zones", "NOAA NGS State Plane Coordinate System of 1983 (zone boundaries via Esri)", "Public domain (NOAA)"),
    ]
    nrows = "".join(f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td></tr>" for a, b, c in national)
    from .parcel import county_sources

    crows = "".join(f'<tr><td><a href="/parcels/{state_slug(k)}">{escape(STATES.get(k, k))}</a></td><td>{len(v)}: {escape(", ".join(sorted(c.county for c in v.values())))}</td></tr>'
                    for k, v in sorted(county_sources().items(), key=lambda kv: STATES.get(kv[0], kv[0])))
    from .footprints import all_sources as building_sources

    brows = "".join(
        f"<tr><td>{escape(STATES.get(st, st) + (', ' + b.county if b.county else ' (statewide)'))}</td><td>{escape(b.publisher or b.name)}</td>"
        f"<td>{escape(b.method or '')}</td><td>{'From the layer' if (b.height_field or b.top_elev_field) else ('From stories' if b.stories_field else 'Matched from USA Structures')}</td></tr>"
        for st, b in sorted(building_sources(), key=lambda x: (STATES.get(x[0], x[0]), x[1].county)))
    src = all_sources()
    prows = "".join(
        f'<tr><td><a href="/parcels/{state_slug(k)}">{escape(STATES.get(k, k))}</a></td><td>{escape(s.publisher or s.name)}</td>' f"<td>{escape(s.coverage)}</td>"
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
<h2>Building outlines</h2>
<p>Where a county, city or state publishes surveyed or LiDAR-derived building outlines, Basesheet uses them. Everywhere else it uses
Microsoft's machine-traced footprints, with heights from FEMA USA Structures. These are the local layers in use now:</p>
<div class="tablewrap"><table><tr><th>Where</th><th>Publisher</th><th>Method</th><th>Heights</th></tr>{brows}</table></div>
<h2>County parcel layers</h2>
<p>In states without a free statewide layer, Basesheet uses county layers. Each state page lists every county source, its terms and when it was last verified.</p>
<div class="tablewrap"><table><tr><th>State</th><th>Counties</th></tr>{crows}</table></div>
<p class="note">Parcel layers are assessor tax-parcel compilations, not legal boundaries. Where a publisher limits commercial use, the outputs say so.</p>
"""
    return layout("Data sources and credits · Basesheet", "/sources", body,
                  description="Every public data source behind Basesheet: USGS 3DEP LiDAR, NRCS SSURGO soils, FEMA flood zones, USFWS wetlands, Census TIGER roads, Esri imagery and statewide and county parcel layers, with terms.")


def privacy() -> str:
    body = """
<h1>Privacy</h1>
<p class="sub">Short version: no accounts, nothing sold, files deleted after two days.</p>
<h2>What happens to an address you enter</h2>
<ul>
<li>It's sent to geocoding services (Esri, the U.S. Census Bureau, OpenStreetMap) to find the location, and to public GIS services (USGS, USDA, FEMA, USFWS, state parcel servers) to fetch data around it.</li>
<li>The finished files are stored at an unlisted web link for <b>2 days</b>, then deleted. Anyone you share a link with can open it in that time.</li>
<li>Each run leaves an anonymous usage record (state, whether a parcel was found, whether we had zoning for it, run time, which data sources failed) so we can see what's working. It never includes the address or any location finer than the state.</li>
<li>Your browser keeps a count of the plans you've made and the date of your first one. Each run sends just those two numbers, so we can tell whether people come back. There's no ID and nothing that identifies you or your browser; clearing site data resets the count.</li>
</ul>
<h2>Analytics</h2>
<p>Page views are counted with Vercel Web Analytics, which doesn't use cookies or track you across sites.</p>
<h2>"What should it do next?"</h2>
<p>After a run you can click an option to say what you'd like built next. That records the option, anything you type in the box,
and the run's state. Nothing that identifies you.</p>
<h2>Firms</h2>
<p>If you tell me about your firm on the For firms page, your firm, role, answers and email are stored privately and used only to follow up
about it. Never shared or sold; ask to have them deleted any time.</p>
<h2>Feature votes and clicks</h2>
<p>If you vote for a feature you can leave an email to hear when it ships; it's used only for that, never shared or sold. The site
also counts clicks on buttons like Download and Save, with the state of the site and nothing else, to see what's useful.</p>
<h2>Saved plans</h2>
<p>Saving is optional. If you sign in to save a plan, your email address and the plans you save (address, files and date) are
stored privately and kept until you delete them. Accounts and saved-plan records are held by Supabase (our database provider)
and sign-in emails are sent through Resend. Your email is used only to send sign-in links. Never shared or sold. Delete a
plan from My plans any time; ask through the feedback form to have your account removed.</p>
<h2>Feedback</h2>
<p>Feedback you send is stored privately and read by the person who runs this site. If you include an email, it's used only to reply.
Never shared or sold. Ask through the feedback form to have it deleted.</p>
<h2>Professional use</h2>
<p>Outputs are planning-level. Verify conditions in the field and with a licensed surveyor before relying on them.</p>
"""
    return layout("Privacy · Basesheet", "/privacy", body,
                  description="What happens to an address you enter: which services see it, how long files are kept (2 days), and what anonymous usage data is recorded.")


def plans() -> str:
    body = """
<h1>My plans</h1>
<p class="lede" id="plede">Base plans you've saved, up to 25. Files stay here until you delete them.</p>
<div id="pmsg" class="note" aria-live="polite"></div>
<div id="plist"></div>
<form id="signin" class="savef" hidden><input type="email" name="email" required maxlength="254" placeholder="Your email" aria-label="Email">
<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true"><button>Email me a sign-in link</button></form>
<div id="probar" class="probar" hidden></div>
<section id="office" hidden>
<h2>Your office</h2>
<p class="note">Used on every base plan you build while signed in: your title block on each PDF sheet, and your CAD layer names.</p>
<form id="firmf" class="firmf">
<label>Firm name <input name="name" maxlength="80"></label>
<label>Address, phone, website (up to 4 lines) <textarea name="lines" rows="3" maxlength="400"></textarea></label>
<label>Prepared by <input name="prepared_by" maxlength="80" placeholder="Name or initials"></label>
<label>Logo (PNG or JPG, under 600 KB) <input type="file" name="logo" accept="image/png,image/jpeg"><img id="logoprev" alt="" hidden></label>
<label class="check" id="rmlogo-row" hidden><input type="checkbox" name="remove_logo"> Remove logo</label>
<label>CAD layer names <select name="layer_preset"><option value="default">Default (SITE-*)</option><option value="ncs">NCS-style (V-PROP-LINE…)</option><option value="custom">Custom…</option></select></label>
<label id="lmrow" hidden>Your layer names, one per line: <code>SITE-PARCEL = L-PROP-LINE</code> <textarea name="layer_map" rows="6" style="font-family:ui-monospace,monospace"></textarea></label>
<div><button>Save office settings</button> <span id="firmmsg" class="note" aria-live="polite"></span></div>
</form>
</section>
<p class="fine" id="signout-row" hidden><span id="who"></span> · <button type="button" class="linkbtn" id="signout" style="padding:0">Sign out</button></p>
"""
    script = """<script>
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const msg=document.getElementById('pmsg'),list=document.getElementById('plist'),signin=document.getElementById('signin');
const q=new URLSearchParams(location.search);
if(q.get('saved')==='1')msg.innerHTML='<span class="ok">Saved to your plans.</span>';
if(q.get('saved')==='0')msg.innerHTML='<span class="err">Signed in, but that plan couldn\\'t be saved. Its files may have expired; build it again and save.</span>';
if(q.get('link')==='expired')msg.innerHTML='<span class="err">That sign-in link has expired. Enter your email for a new one.</span>';
if(q.get('link')==='bad')msg.innerHTML='<span class="err">That sign-in link didn\\'t work. Enter your email for a new one.</span>';
async function load(){
 const me=await (await fetch('/api/me')).json().catch(()=>({}));
 if(!me.email){document.getElementById('plede').textContent=me.can_sign_up?'Sign in with your email to see the plans you\\'ve saved. No password: we email you a link.':'Saving plans isn\\'t available yet.';signin.hidden=!me.can_sign_up;return}
 document.getElementById('signout-row').hidden=false;document.getElementById('who').textContent='Signed in as '+me.email;
 const r=await fetch('/api/plans');const d=await r.json().catch(()=>({plans:[]}));
 if(!d.plans||!d.plans.length){list.innerHTML='<p class="note">No saved plans yet. Build a base plan on the <a href="/">home page</a> and choose Save to my plans.</p>';return}
 list.innerHTML=d.plans.map(p=>'<div class="plan" data-id="'+esc(p.id)+'"><span class="t">'+esc(p.title)+'</span><span class="note">Saved '+esc((p.saved_at||'').slice(0,10))+'</span>'+
  '<span class="acts"><a href="'+esc(p.files.zip)+'">Download files (.zip)</a>'+(p.files.pdf?'<a href="'+esc(p.files.pdf)+'" target="_blank" rel="noopener">Open PDF</a>':'')+
  '<button type="button" class="del">Delete</button></span></div>').join('');
 list.querySelectorAll('.del').forEach(b=>b.onclick=async()=>{
  if(!b.classList.contains('really')){b.classList.add('really');b.textContent='Delete for good?';setTimeout(()=>{b.classList.remove('really');b.textContent='Delete'},4000);return}
  const row=b.closest('.plan');b.textContent='Deleting…';
  const r=await fetch('/api/plans/'+encodeURIComponent(row.dataset.id),{method:'DELETE'});
  if(r.ok){row.remove();if(!list.children.length)load()}else{b.textContent='Couldn\\'t delete'}});}
signin.onsubmit=async e=>{e.preventDefault();
 const r=await fetch('/api/auth/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:signin.email.value,website:signin.website.value})});
 const k=await r.json().catch(()=>({}));
 if(r.ok){signin.hidden=true;msg.innerHTML='<span class="ok">Check your email for the sign-in link. It works for 30 minutes.</span>'+(k.dev_link?' <a href="'+esc(k.dev_link)+'">Dev: open link</a>':'')}
 else{msg.innerHTML='<span class="err">'+esc(k.error||'Something went wrong.')+'</span>'}};
document.getElementById('signout').onclick=async()=>{await fetch('/api/auth/logout',{method:'POST'});location.href='/plans'};
load();
const bar=document.getElementById('probar');
async function proBar(tries){
 const s=await (await fetch('/api/billing/status')).json().catch(()=>({}));
 if(!s.signed_in||(!s.live&&!s.pro&&!s.has_billing))return;
 const when=s.period_end?new Date(s.period_end*1000).toLocaleDateString():'';
 if(s.pro){bar.innerHTML='<b>Basesheet Pro</b><span class="note">'+(s.cancel_at_period_end?'ends ':'renews ')+esc(when)+'</span>'+
   '<a href="/batch">Batch runs</a><a href="#office">Office settings</a><button type="button" class="linkbtn" id="billing">Manage billing</button>';bar.hidden=false;office();
  document.getElementById('billing').onclick=async()=>{const r=await fetch('/api/billing/portal',{method:'POST'});const k=await r.json().catch(()=>({}));if(k.url)location.href=k.url;else msg.innerHTML='<span class="err">'+esc(k.error||'Billing isn\\'t reachable right now.')+'</span>'};
  document.getElementById('plede').textContent='Base plans you\\'ve saved, up to 500 with Pro. Files stay here until you delete them.';
  if(q.get('pro')==='1')msg.innerHTML='<span class="ok">Welcome to Pro. Test fits, batch runs and office settings are on.</span>';return}
 if(q.get('pro')==='1'&&tries<6){bar.innerHTML='<span class="note">Payment received. Turning on Pro…</span>';bar.hidden=false;setTimeout(()=>proBar(tries+1),2000);return}
 if(s.live){bar.innerHTML='<b>Get Pro'+(s.price?' · '+esc(s.price.label):'')+'</b><span class="note">Zoning test fits, office standards, batch runs, 500 saved plans.</span>'+
   '<a href="/pro">Details</a><label class="check fine"><input type="checkbox" id="agree"> I agree to the <a href="/terms" target="_blank">Terms</a> and will have everything checked by a licensed surveyor and the jurisdiction</label><button type="button" id="getpro">Get Pro</button>';bar.hidden=false;
  document.getElementById('getpro').onclick=async()=>{if(!document.getElementById('agree').checked){msg.innerHTML='<span class="err">Please tick the box to accept the Terms first.</span>';return}
   const r=await fetch('/api/billing/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({accept_terms:s.terms_version})});const k=await r.json().catch(()=>({}));if(k.url)location.href=k.url;else msg.innerHTML='<span class="err">'+esc(k.error||'Checkout isn\\'t working right now.')+'</span>'}}}
async function office(){const sec=document.getElementById('office'),ff=document.getElementById('firmf'),fm=document.getElementById('firmmsg');
 const r=await fetch('/api/firm');if(!r.ok)return;const p=await r.json();sec.hidden=false;
 ff.name.value=p.name||'';ff.lines.value=(p.lines||[]).join('\\n');ff.prepared_by.value=p.prepared_by||'';ff.layer_preset.value=p.layer_preset||'default';ff.layer_map.value=p.layer_map||'';
 const prev=document.getElementById('logoprev'),syncLm=()=>{document.getElementById('lmrow').hidden=ff.layer_preset.value!=='custom'};syncLm();ff.layer_preset.onchange=syncLm;
 if(p.has_logo){prev.src='/api/firm/logo?'+Date.now();prev.hidden=false;document.getElementById('rmlogo-row').hidden=false}
 let logo=null;ff.logo.onchange=()=>{const f=ff.logo.files[0];if(!f)return;if(f.size>600000){fm.innerHTML='<span class="err">That logo is over 600 KB.</span>';ff.logo.value='';return}
  const rd=new FileReader();rd.onload=()=>{logo=rd.result;prev.src=logo;prev.hidden=false};rd.readAsDataURL(f)};
 ff.onsubmit=async e=>{e.preventDefault();fm.textContent='Saving…';
  const body={name:ff.name.value,lines:ff.lines.value,prepared_by:ff.prepared_by.value,layer_preset:ff.layer_preset.value,layer_map:ff.layer_map.value,remove_logo:ff.remove_logo.checked,...(logo?{logo}:{})};
  const r=await fetch('/api/firm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const k=await r.json().catch(()=>({}));
  fm.innerHTML=r.ok?'<span class="ok">Saved. Your next base plan will use it.</span>':'<span class="err">'+esc(k.error||'Couldn\\'t save.')+'</span>';
  if(r.ok){logo=null;if(!k.has_logo){prev.hidden=true;document.getElementById('rmlogo-row').hidden=true}else document.getElementById('rmlogo-row').hidden=false;ff.remove_logo.checked=false}}}
proBar(0);
</script>"""
    return layout("My plans · Basesheet", "/plans", body, script, description="Your saved Basesheet base plans.")


FIRMS_PAGE = os.environ.get("FIRMS_PAGE", "") not in ("", "0", "false")  # hosted site only


def pro_live() -> bool:
    try:
        from .billing import live
    except ImportError:
        return False
    return live()


def pro(price: dict | None) -> str:
    label = escape(price["label"]) if price else ""
    body = f"""
<h1>Basesheet Pro</h1>
<p class="lede">Base plans stay free for everyone. Pro is for offices that run regular site studies: it adds the features
that take real work to build and keep accurate, and it pays for the zoning research behind them.</p>
<div class="procard">
<p class="price">{label or "Monthly"}<span class="note"> · cancel any time</span></p>
<ul>
<li><b>Zoning test fits:</b> buildable area after setbacks and buffers, maximum units, parking, and a building and parking
layout you can open in CAD. Thurston County, WA today; more jurisdictions are being added every week, and you can ask for yours.</li>
<li><b>Your office standards:</b> your firm name, address and logo in a title block on every PDF sheet, and your CAD layer names on every run.</li>
<li><b>Batch runs:</b> up to 50 sites at once, with a summary table (parcel size, flood zone, slope, wetlands, soils, zoning) and every plan in one download.</li>
<li><b>500 saved plans</b> instead of 25.</li>
</ul>
<div id="probox"><label class="check"><input type="checkbox" id="agree"> I've read the <a href="/terms" target="_blank">Terms</a>. I understand that test fits and everything else Basesheet makes are unverified, planning-level information, and I'll have them checked by a licensed surveyor and the jurisdiction before relying on them.</label>
<p><button type="button" id="subscribe">Get Pro</button></p></div>
<p id="promsg" class="note" aria-live="polite"></p>
</div>
<h2>Fine print</h2>
<ul>
<li>Test fits are planning-level, from rule sheets that cite the zoning code. Each one says whether it's been checked by a professional. Confirm with the jurisdiction before relying on it.</li>
<li>Payments are handled by Stripe; Basesheet never sees your card. Pro renews monthly; cancel any time from My plans and it ends at the end of the period you've paid for. See the <a href="/terms">Terms</a>.</li>
<li>Questions or a firm with several people? {CONTACT_HTML}</li>
</ul>
"""
    script = """<script>
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const box=document.getElementById('probox'),msg=document.getElementById('promsg');
if(new URLSearchParams(location.search).has('cancelled'))msg.textContent='Checkout cancelled. Nothing was charged.';
fetch('/api/billing/status').then(r=>r.json()).then(s=>{
 if(s.pro){box.innerHTML='<p class="ok">You have Pro.</p> <a href="/plans">My plans and billing</a>';return}
 if(!s.signed_in){box.innerHTML='<form id="pin" class="savef"><input type="email" name="email" required maxlength="254" placeholder="Your email" aria-label="Email">'+
  '<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true"><button>Email me a sign-in link</button></form><p class="fine">Sign in first (no password), then choose Get Pro on My plans.</p>';
  const pin=document.getElementById('pin');pin.onsubmit=async e=>{e.preventDefault();
   const r=await fetch('/api/auth/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:pin.email.value,website:pin.website.value})});
   const k=await r.json().catch(()=>({}));msg.innerHTML=r.ok?'<span class="ok">Check your email for the sign-in link.</span>'+(k.dev_link?' <a href="'+esc(k.dev_link)+'">Dev: open link</a>':''):'<span class="err">'+esc(k.error||'Something went wrong.')+'</span>'};return}
 TV=s.terms_version;document.getElementById('subscribe').onclick=startCheckout});
let TV='';
async function startCheckout(){if(!document.getElementById('agree').checked){msg.innerHTML='<span class="err">Please tick the box to accept the Terms first.</span>';return}
 msg.textContent='Opening checkout…';
 const r=await fetch('/api/billing/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({accept_terms:TV})});const k=await r.json().catch(()=>({}));
 if(k.url)location.href=k.url;else msg.innerHTML='<span class="err">'+esc(k.error||'Checkout isn\\'t working right now.')+'</span>'}
</script>"""
    return layout("Basesheet Pro", "/pro", body, script,
                  description="Basesheet Pro: zoning test fits, your office title block and CAD standards, and batch runs, on top of the free base plan tool.")


def firms() -> str:
    body = f"""
<h1>For firms</h1>
<p class="lede">Basesheet is free and <a href="{REPO_URL}">open source</a>, and it stays that way. A few offices that run regular
site studies have asked for firm-specific features, so I'm working with them to improve the tool for professional usage.</p>

<form id="ff" class="ffshort">
<label>Email<input name="email" type="email" required maxlength="254" placeholder="you@office.com"></label>
<label>What would you use it for? (optional)<input name="use" maxlength="300" placeholder="e.g. quick test fits for multifamily sites in Columbus"></label>
<fieldset class="checks"><legend>Interested in (optional)</legend>
<label><input type="checkbox" name="want" value="zoning"> Test fits for my jurisdictions</label>
<label><input type="checkbox" name="want" value="standards"> Our title block and CAD layers</label>
<label><input type="checkbox" name="want" value="batch"> Batch runs</label>
<label><input type="checkbox" name="want" value="coverage"> Parcel lines where I work</label>
</fieldset>
<input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<div><button>Get early access</button> <span class="fine" id="ffmsg"></span></div>
<p class="fine">I'll only use this to reply to you. See <a href="/privacy">Privacy</a>.</p>
</form>

<h2>Free forever</h2>
<ul>
<li>Base plans from any US address: parcel, neighbors, roads, contours, slope, soils, flood, wetlands, aerial.</li>
<li>Every export: DXF, SketchUp terrain, LandXML, GIS, KML and the PDF summary.</li>
<li>Multi-parcel sites, your own CAD layer names, and the zoning lookup where it's available.</li>
</ul>

<h2>What I'm working on with firms</h2>
<ul>
<li><b>Test fits for the places you work:</b> buildable area after setbacks and buffers, maximum units, parking, and a building and parking layout you can open in CAD, from zoning rules checked for your jurisdictions.</li>
<li><b>Your office standards on every output:</b> your title block and logo on the PDF, your CAD layer standard set up once for the whole office.</li>
<li><b>Batch runs:</b> many sites at once, for feasibility studies and site selection.</li>
<li><b>Parcel lines where you work,</b> including counties the free tool doesn't cover yet.</li>
</ul>

"""
    script = """<script>
document.getElementById('ff').onsubmit=async e=>{e.preventDefault();const f=e.target,m=document.getElementById('ffmsg');
 const d=Object.fromEntries(new FormData(f));d.want=[...f.querySelectorAll('input[name=want]:checked')].map(x=>x.value);
 const r=await fetch('/api/firms',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
 const j=await r.json().catch(()=>({}));
 if(r.ok){f.innerHTML='<p class="ok"><b>Thanks, got it.</b> I\\'ll be in touch by email.</p>'}else{m.textContent=j.error||'Something went wrong.';m.className='fine err'}};
</script>"""
    return layout("For firms · Basesheet", "/firms", body, script,
                  description="Basesheet is free and stays free. For offices that run regular site studies: test fits for your jurisdictions, your title block and CAD standards, and batch runs, built with early firms.")
