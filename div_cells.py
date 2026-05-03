"""divAI Cells — live interactive popup windows opened from the CLI."""

import json
import os
import tempfile
import webbrowser

_CSS_BASE = """
:root{--bg:#08080e;--surface:#0f0f1a;--card:#13131f;--border:#1e1e2e;
  --accent:#00aaff;--accent-dim:#00aaff18;--text:#e0e0f0;--muted:#666688;
  --green:#22c55e;--yellow:#f59e0b;--red:#ef4444;--indigo:#818cf8;--radius:14px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',sans-serif;
  padding:28px;min-height:100vh}
"""


def _timer_html(p: dict) -> str:
    seconds = int(p.get("seconds", 300))
    label_raw = str(p.get("label", "Timer"))
    label_html = label_raw.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    label_js = json.dumps(label_raw)  # safely quoted for JS: handles apostrophes, backslashes, etc.
    circ = 502.655  # 2π×80
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>divAI · {label_html}</title>
<style>{_CSS_BASE}
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px}}
svg{{filter:drop-shadow(0 0 12px #00aaff66)}}
.ring-bg{{fill:none;stroke:var(--surface);stroke-width:10}}
.ring{{fill:none;stroke:var(--accent);stroke-width:10;stroke-linecap:round;
  stroke-dasharray:{circ:.3f};stroke-dashoffset:0;
  transform:rotate(-90deg);transform-origin:50% 50%;transition:stroke 0.4s}}
.ring.done{{stroke:var(--green)}}
.ring.urgent{{stroke:var(--red)}}
.time{{font-size:56px;font-weight:700;letter-spacing:-2px;color:var(--accent);
  font-variant-numeric:tabular-nums}}
.label{{font-size:16px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase}}
.btns{{display:flex;gap:12px;margin-top:8px}}
button{{background:var(--card);border:1px solid var(--border);color:var(--text);
  padding:10px 28px;border-radius:var(--radius);font-size:14px;cursor:pointer;
  transition:background .2s,border-color .2s}}
button:hover{{background:var(--surface);border-color:var(--accent)}}
.flash{{animation:flash 0.6s ease-in-out 4}}
@keyframes flash{{0%,100%{{opacity:1}}50%{{opacity:0.2}}}}
</style></head><body>
<svg width="200" height="200" viewBox="0 0 200 200">
  <circle class="ring-bg" cx="100" cy="100" r="80"/>
  <circle class="ring" id="ring" cx="100" cy="100" r="80"/>
</svg>
<div class="time" id="disp">--:--</div>
<div class="label">{label_html}</div>
<div class="btns">
  <button id="btn" onclick="toggle()">Pause</button>
  <button onclick="reset()">Reset</button>
</div>
<script>
const TOTAL={seconds},CIRC={circ:.3f},LABEL={label_js};
let rem=TOTAL,running=true,iv=null;
const ring=document.getElementById('ring');
const disp=document.getElementById('disp');
const btn=document.getElementById('btn');
function fmt(s){{let m=Math.floor(s/60);return String(m).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}}
function draw(){{
  let pct=rem/TOTAL;
  ring.style.strokeDashoffset=CIRC*(1-pct);
  disp.textContent=fmt(rem);
  ring.classList.toggle('urgent',rem<=30&&rem>0);
  ring.classList.toggle('done',rem===0);
}}
function tick(){{
  if(rem>0){{rem--;draw();}}
  else{{
    clearInterval(iv);running=false;btn.textContent='Done';
    document.title='⏰ Done · '+LABEL;
    disp.classList.add('flash');
  }}
}}
function toggle(){{if(rem===0)return;running=!running;btn.textContent=running?'Pause':'Resume';
  if(running)iv=setInterval(tick,1000);else clearInterval(iv);}}
function reset(){{clearInterval(iv);rem=TOTAL;running=true;btn.textContent='Pause';
  disp.classList.remove('flash');document.title='divAI · '+LABEL;draw();iv=setInterval(tick,1000);}}
draw();iv=setInterval(tick,1000);
</script></body></html>"""


def _checklist_html(p: dict) -> str:
    title = str(p.get("title", "Checklist")).replace('"', "&quot;")
    raw_items = p.get("items", [])
    items_json = json.dumps([
        {"text": str(it.get("text", it) if isinstance(it, dict) else it),
         "done": bool(it.get("done", False) if isinstance(it, dict) else False)}
        for it in raw_items
    ])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>divAI · {title}</title>
<style>{_CSS_BASE}
.header{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:20px}}
h1{{font-size:22px;font-weight:700}}
.counter{{font-size:13px;color:var(--muted)}}
.list{{display:flex;flex-direction:column;gap:10px}}
.item{{display:flex;align-items:center;gap:14px;padding:14px 16px;
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  cursor:pointer;transition:background .15s,border-color .15s;user-select:none}}
.item:hover{{background:var(--surface);border-color:var(--accent)}}
.item.done{{opacity:.5}}
.item.done .txt{{text-decoration:line-through;color:var(--muted)}}
.cb{{width:22px;height:22px;flex-shrink:0;border:2px solid var(--border);
  border-radius:6px;display:flex;align-items:center;justify-content:center;transition:.15s}}
.item.done .cb{{background:var(--green);border-color:var(--green)}}
.check-svg{{display:none}}
.item.done .check-svg{{display:block}}
.txt{{font-size:15px;line-height:1.4}}
</style></head><body>
<div class="header"><h1>{title}</h1><span class="counter" id="ctr"></span></div>
<div class="list" id="list"></div>
<script>
const ITEMS={items_json};
const list=document.getElementById('list');
const ctr=document.getElementById('ctr');
function updateCounter(){{
  const done=ITEMS.filter(i=>i.done).length;
  ctr.textContent=done+' / '+ITEMS.length+' done';
  document.title=(done===ITEMS.length?'✅ ':'')+'divAI · {title}';
}}
function render(){{
  list.innerHTML='';
  ITEMS.forEach((it,i)=>{{
    const div=document.createElement('div');
    div.className='item'+(it.done?' done':'');
    div.innerHTML=`<div class="cb"><svg class="check-svg" width="13" height="10" viewBox="0 0 13 10" fill="none">
      <path d="M1 5l3.5 3.5L12 1" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg></div><span class="txt">${{it.text}}</span>`;
    div.onclick=()=>{{ITEMS[i].done=!ITEMS[i].done;render();updateCounter();}};
    list.appendChild(div);
  }});
}}
render();updateCounter();
</script></body></html>"""


def _progress_html(p: dict) -> str:
    title = str(p.get("title", "Progress")).replace('"', "&quot;")
    items_json = json.dumps([
        {"label": str(it.get("label", "")),
         "value": float(it.get("value", 0)),
         "max":   float(it.get("max", 100))}
        for it in p.get("items", [])
    ])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>divAI · {title}</title>
<style>{_CSS_BASE}
h1{{font-size:22px;font-weight:700;margin-bottom:24px}}
.items{{display:flex;flex-direction:column;gap:18px}}
.row{{display:flex;flex-direction:column;gap:6px}}
.meta{{display:flex;justify-content:space-between;font-size:14px}}
.lbl{{color:var(--text)}}
.pct{{color:var(--muted)}}
.track{{height:10px;background:var(--surface);border-radius:99px;overflow:hidden;
  border:1px solid var(--border)}}
.fill{{height:100%;border-radius:99px;width:0;transition:width 0.9s cubic-bezier(.4,0,.2,1)}}
</style></head><body>
<h1>{title}</h1>
<div class="items" id="items"></div>
<script>
const ITEMS={items_json};
const container=document.getElementById('items');
ITEMS.forEach(it=>{{
  const pct=Math.round((it.value/it.max)*100);
  const color=pct>=80?'var(--green)':pct>=50?'var(--accent)':'var(--yellow)';
  const div=document.createElement('div');div.className='row';
  div.innerHTML=`<div class="meta"><span class="lbl">${{it.label}}</span><span class="pct">${{pct}}%</span></div>
    <div class="track"><div class="fill" id="f${{Math.random()}}" data-w="${{pct}}" style="background:${{color}}"></div></div>`;
  container.appendChild(div);
}});
requestAnimationFrame(()=>setTimeout(()=>{{
  document.querySelectorAll('.fill').forEach(f=>f.style.width=f.dataset.w+'%');
}},50));
</script></body></html>"""


def _schedule_html(p: dict) -> str:
    date = str(p.get("date", "Today")).replace('"', "&quot;")
    color_map = {
        "blue": "var(--accent)", "green": "var(--green)", "yellow": "var(--yellow)",
        "red": "var(--red)", "purple": "var(--indigo)", "grey": "var(--muted)",
        "gray": "var(--muted)",
    }
    blocks = []
    for b in p.get("blocks", []):
        color = color_map.get(str(b.get("color", "")).lower(), "var(--accent)")
        blocks.append({"time": str(b.get("time", "")), "label": str(b.get("label", "")), "color": color})
    blocks_json = json.dumps(blocks)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>divAI · {date}</title>
<style>{_CSS_BASE}
.date-header{{font-size:13px;text-transform:uppercase;letter-spacing:1px;
  color:var(--muted);margin-bottom:6px}}
h1{{font-size:24px;font-weight:700;margin-bottom:24px}}
.blocks{{display:flex;flex-direction:column;gap:10px}}
.block{{display:flex;align-items:center;gap:16px;padding:14px 16px;
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius)}}
.block.now{{border-color:var(--accent);background:var(--accent-dim)}}
.time-lbl{{font-size:13px;color:var(--muted);width:72px;flex-shrink:0;
  font-variant-numeric:tabular-nums}}
.pill{{flex:1;font-size:15px;font-weight:500}}
.dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.now-badge{{font-size:10px;text-transform:uppercase;letter-spacing:.5px;
  background:var(--accent);color:#000;padding:2px 7px;border-radius:99px;font-weight:700}}
</style></head><body>
<div class="date-header">Schedule</div>
<h1>{date}</h1>
<div class="blocks" id="blocks"></div>
<script>
const BLOCKS={blocks_json};
const now=new Date();
const nowMins=now.getHours()*60+now.getMinutes();
function parseMins(t){{
  const m=t.match(/(\\d+):(\\d+)\\s*(am|pm)?/i);
  if(!m)return-1;
  let h=parseInt(m[1]),mn=parseInt(m[2]);
  if(m[3]){{if(m[3].toLowerCase()==='pm'&&h!==12)h+=12;if(m[3].toLowerCase()==='am'&&h===12)h=0;}}
  return h*60+mn;
}}
const container=document.getElementById('blocks');
BLOCKS.forEach((b,i)=>{{
  const bMins=parseMins(b.time);
  const nextMins=i+1<BLOCKS.length?parseMins(BLOCKS[i+1].time):Infinity;
  const isNow=bMins>=0&&nowMins>=bMins&&nowMins<nextMins;
  const div=document.createElement('div');div.className='block'+(isNow?' now':'');
  div.innerHTML=`<span class="time-lbl">${{b.time}}</span>
    <div class="dot" style="background:${{b.color}}"></div>
    <span class="pill">${{b.label}}</span>
    ${{isNow?'<span class="now-badge">Now</span>':''}}`;
  container.appendChild(div);
}});
</script></body></html>"""


def _table_html(p: dict) -> str:
    title = str(p.get("title", "Table")).replace('"', "&quot;")
    headers = [str(h) for h in p.get("headers", [])]
    rows = [[str(c) for c in row] for row in p.get("rows", [])]
    ths = "".join(f"<th>{h}</th>" for h in headers)
    trs = ""
    for i, row in enumerate(rows):
        tds = "".join(f"<td>{c}</td>" for c in row)
        trs += f'<tr class="{"odd" if i%2==0 else "even"}">{tds}</tr>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>divAI · {title}</title>
<style>{_CSS_BASE}
h1{{font-size:22px;font-weight:700;margin-bottom:20px}}
.wrap{{overflow-x:auto;border-radius:var(--radius);border:1px solid var(--border)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
thead{{background:var(--accent)}}
th{{padding:12px 16px;text-align:left;color:#000;font-weight:700;font-size:13px;
  text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}}
td{{padding:12px 16px;border-bottom:1px solid var(--border)}}
tr.odd{{background:var(--card)}}
tr.even{{background:var(--surface)}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--border)}}
</style></head><body>
<h1>{title}</h1>
<div class="wrap"><table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>
</body></html>"""


def render_cell(cell_type: str, params: dict) -> str:
    generators = {
        "timer":     _timer_html,
        "checklist": _checklist_html,
        "progress":  _progress_html,
        "schedule":  _schedule_html,
        "table":     _table_html,
    }
    if cell_type not in generators:
        return f"Unknown cell type '{cell_type}'. Available: {', '.join(generators)}"
    try:
        html = generators[cell_type](params)
        path = os.path.join(tempfile.gettempdir(), f"divcell_{cell_type}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        url = "file:///" + path.replace("\\", "/")
        webbrowser.open_new(url)
        return f"[cell:{cell_type}] Opened in new window"
    except Exception as e:
        return f"Cell render error: {str(e)}"
