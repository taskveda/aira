import json
import re
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import tts
from . import voice
from .brain import Brain
from .config import AUDIO_DIR
from .executor import ToolExecutor

HOST, PORT = "127.0.0.1", 8756

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aira — Your AI</title>
<style>
:root{
 --bg:#0a0c12; --bg2:#0e1119; --panel:rgba(20,24,34,.72); --panel2:#161b28;
 --glass:rgba(255,255,255,.045); --glass2:rgba(255,255,255,.08);
 --border:rgba(255,255,255,.08); --border2:rgba(255,255,255,.14);
 --text:#eef1f8; --muted:#9aa3b8; --faint:#616a80;
 --acc:#4f7cff; --acc2:#8b5cf6; --ok:#34d399; --no:#f87171; --warn:#fbbf24;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Segoe UI',Roboto,Inter,sans-serif;
 background:
  radial-gradient(1100px 500px at 85% -5%,rgba(79,124,255,.14),transparent 60%),
  radial-gradient(800px 400px at -10% 110%,rgba(139,92,246,.10),transparent 60%),
  var(--bg);
 color:var(--text);display:flex;height:100vh;overflow:hidden;
 -webkit-font-smoothing:antialiased}
button{font-family:inherit}
/* ============ SIDEBAR ============ */
aside{width:300px;min-width:300px;display:flex;flex-direction:column;background:var(--bg2);
 border-right:1px solid var(--border)}
.sb-head{display:flex;align-items:center;gap:12px;padding:18px 18px 14px}
.logo{width:40px;height:40px;border-radius:12px;flex-shrink:0;display:flex;align-items:center;
 justify-content:center;background:linear-gradient(135deg,var(--acc),var(--acc2));
 font-size:18px;font-weight:800;color:#fff;box-shadow:0 6px 18px rgba(79,124,255,.35)}
.brand h1{font-size:16.5px;font-weight:700;letter-spacing:.2px}
.brand p{font-size:11.5px;color:var(--muted);margin-top:1px}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:10.5px;font-weight:600;color:var(--ok);
 background:rgba(52,211,153,.1);border:1px solid rgba(52,211,153,.25);padding:3px 9px;border-radius:99px;margin-top:5px}
.pill i{width:6px;height:6px;border-radius:50%;background:var(--ok);box-shadow:0 0 7px var(--ok)}
/* tabs */
.tabs{display:flex;margin:2px 14px 10px;background:var(--glass);border:1px solid var(--border);
 border-radius:11px;padding:3px}
.tabs button{flex:1;border:0;background:transparent;color:var(--muted);font-size:12.5px;font-weight:600;
 padding:7px 0;border-radius:8px;cursor:pointer;transition:.18s}
.tabs button.on{background:var(--glass2);color:var(--text);box-shadow:0 1px 4px rgba(0,0,0,.3)}
/* search */
.search{margin:0 14px 12px;position:relative}
.search input{width:100%;background:var(--glass);border:1px solid var(--border);border-radius:10px;
 padding:8px 12px 8px 34px;color:var(--text);font-size:12.5px;outline:none;transition:.18s}
.search input:focus{border-color:rgba(79,124,255,.5)}
.search span{position:absolute;left:11px;top:50%;transform:translateY(-50%);font-size:12px;color:var(--faint)}
/* schedule strip */
.sched{margin:0 14px 12px;padding:12px 14px;border-radius:14px;background:linear-gradient(135deg,rgba(79,124,255,.12),rgba(139,92,246,.08));
 border:1px solid rgba(79,124,255,.22)}
.sched h3{font-size:10.5px;text-transform:uppercase;letter-spacing:1.4px;color:var(--muted);margin-bottom:8px}
.meet{display:flex;align-items:center;gap:9px;font-size:12px;padding:4px 0;color:var(--text)}
.meet .t{color:var(--faint);font-variant-numeric:tabular-nums;width:44px;flex-shrink:0}
.meet .d{width:6px;height:6px;border-radius:50%;background:var(--acc);flex-shrink:0}
/* chat list */
.sb-scroll{flex:1;overflow-y:auto;padding:0 10px 10px}
.sb-scroll::-webkit-scrollbar{width:7px}.sb-scroll::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}
.conv{display:flex;align-items:center;gap:11px;padding:10px 10px;border-radius:11px;cursor:pointer;transition:.15s}
.conv:hover{background:var(--glass)}
.conv.on{background:rgba(79,124,255,.12);border:1px solid rgba(79,124,255,.25)}
.av{width:36px;height:36px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;
 font-size:13px;font-weight:700;color:#fff;background:linear-gradient(135deg,#475d8f,#2d3d63)}
.av.online{background:linear-gradient(135deg,var(--acc),var(--acc2))}
.av .st{position:absolute}
.cname{font-size:13px;font-weight:600}
.csub{font-size:11.5px;color:var(--muted);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px}
.ctime{margin-left:auto;font-size:10.5px;color:var(--faint);flex-shrink:0}
.sb-label{font-size:10.5px;text-transform:uppercase;letter-spacing:1.4px;color:var(--faint);padding:12px 12px 6px}
/* files tab */
.file{display:flex;align-items:center;gap:11px;padding:9px 10px;border-radius:11px;cursor:pointer;transition:.15s}
.file:hover{background:var(--glass)}
.fic{width:34px;height:34px;border-radius:9px;flex-shrink:0;display:flex;align-items:center;justify-content:center;
 font-size:15px;background:var(--glass2);border:1px solid var(--border)}
.fname{font-size:12.5px;font-weight:600;word-break:break-all}
.fmeta{font-size:11px;color:var(--faint);margin-top:2px}
/* about tab */
.card{background:var(--glass);border:1px solid var(--border);border-radius:14px;padding:13px 14px;margin-bottom:9px}
.card b{font-size:12.5px;display:block;margin-bottom:5px}
.card p{font-size:12px;color:var(--muted);line-height:1.55}
.card .tag{display:inline-block;font-size:10.5px;color:var(--acc);background:rgba(79,124,255,.12);
 border:1px solid rgba(79,124,255,.25);border-radius:99px;padding:2px 9px;margin:3px 3px 0 0}
aside footer{padding:12px 18px;border-top:1px solid var(--border);font-size:10.5px;color:var(--faint);line-height:1.7}
/* ============ MAIN ============ */
main{flex:1;display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;
 border-bottom:1px solid var(--border);background:rgba(14,17,25,.6);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}
.tb-l{display:flex;align-items:center;gap:12px}
.tb-av{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,var(--acc),var(--acc2));
 display:flex;align-items:center;justify-content:center;font-weight:800;font-size:15px;color:#fff;
 box-shadow:0 4px 14px rgba(79,124,255,.3)}
.tb-name{font-size:15px;font-weight:700}
.tb-sub{font-size:11.5px;color:var(--ok);display:flex;align-items:center;gap:5px;margin-top:1px}
.tb-sub i{width:6px;height:6px;border-radius:50%;background:var(--ok)}
.tb-r{display:flex;align-items:center;gap:9px}
.badge{font-size:11px;color:var(--muted);border:1px solid var(--border);padding:4px 11px;border-radius:99px;background:var(--glass)}
#voice{background:var(--glass);color:var(--muted);border:1px solid var(--border);border-radius:99px;
 padding:6px 13px;font-size:11.5px;cursor:pointer;display:flex;align-items:center;gap:6px;transition:.18s}
#voice:hover{color:var(--text)}
#voice.on{color:var(--acc);border-color:rgba(79,124,255,.45);background:rgba(79,124,255,.1)}
#voice .vdot{width:6px;height:6px;border-radius:50%;background:currentColor}
/* chat log */
#log{flex:1;overflow-y:auto;padding:26px 28px 12px;scroll-behavior:smooth}
#log::-webkit-scrollbar{width:8px}#log::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}
.row{display:flex;margin-bottom:15px;animation:fadein .2s ease}
@keyframes fadein{from{opacity:0;transform:translateY(5px)}to{opacity:1}}
.row.user{justify-content:flex-end}
.bubble{max-width:70%;padding:11px 15px;border-radius:16px;white-space:pre-wrap;word-break:break-word;
 font-size:13.5px;line-height:1.55;box-shadow:0 3px 14px rgba(0,0,0,.28)}
.row.user .bubble{background:linear-gradient(135deg,#3d5bf0,#5b46e0);color:#fff;
 border-bottom-right-radius:5px}
.row.aira .bubble{background:var(--panel2);border:1px solid var(--border);border-bottom-left-radius:5px}
.row.sys .bubble{background:rgba(251,191,36,.07);border:1px solid rgba(251,191,36,.25);color:#fcd34d;
 font-size:12px;max-width:92%}
.avatar{width:30px;height:30px;border-radius:50%;flex-shrink:0;margin-top:2px;display:flex;
 align-items:center;justify-content:center;font-size:12px;font-weight:700}
.row.aira .avatar{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;margin-right:10px}
.row.user .avatar{background:#2a3350;color:var(--muted);margin-left:10px;font-size:10.5px}
.typing{display:inline-flex;gap:5px;padding:6px 4px}
.typing i{width:7px;height:7px;border-radius:50%;background:var(--muted);animation:blink 1.1s infinite}
.typing i:nth-child(2){animation-delay:.18s}.typing i:nth-child(3){animation-delay:.36s}
@keyframes blink{0%,60%,100%{opacity:.25}30%{opacity:1}}
.approve{margin:10px 0 18px;padding:14px 16px;border-radius:14px;max-width:92%;
 background:rgba(251,191,36,.07);border:1px solid rgba(251,191,36,.3)}
.approve b{font-size:12.5px;color:var(--warn);display:block;margin-bottom:6px}
.approve .q{font-size:13px;color:var(--text);margin-bottom:12px;white-space:pre-wrap}
.btns{display:flex;gap:9px}
.btn{border:0;border-radius:9px;padding:8px 18px;font-size:12.5px;font-weight:600;cursor:pointer;color:#fff;transition:.15s}
.btn:active{transform:scale(.97)}
.btn.ok{background:var(--ok)}.btn.ok:hover{background:#3ee0a8}
.btn.no{background:var(--no)}.btn.no:hover{background:#fb8a8a}
/* composer */
.composer{padding:12px 28px 20px;background:linear-gradient(0deg,var(--bg) 55%,transparent)}
.cwrap{display:flex;align-items:flex-end;gap:9px;max-width:860px;margin:0 auto;
 background:var(--panel2);border:1px solid var(--border2);border-radius:15px;padding:7px 7px 7px 17px;
 box-shadow:0 8px 28px rgba(0,0,0,.4);transition:border-color .2s}
.cwrap:focus-within{border-color:rgba(79,124,255,.6);box-shadow:0 0 0 3px rgba(79,124,255,.12)}
textarea{flex:1;background:transparent;border:0;outline:0;color:var(--text);font:inherit;
 font-size:13.5px;resize:none;max-height:130px;padding:9px 0;line-height:1.5}
textarea::placeholder{color:var(--faint)}
.iconbtn{background:var(--glass);color:var(--text);border:1px solid var(--border);border-radius:11px;
 width:42px;height:42px;font-size:15px;cursor:pointer;display:flex;align-items:center;justify-content:center;
 transition:.15s;flex-shrink:0}
.iconbtn:hover{border-color:var(--acc)}
.iconbtn:active{transform:scale(.94)}
#send{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;border:0;border-radius:11px;
 width:42px;height:42px;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;
 transition:.15s;flex-shrink:0;box-shadow:0 4px 14px rgba(79,124,255,.3)}
#send:hover{filter:brightness(1.12)}#send:active{transform:scale(.94)}
#mic.on{background:linear-gradient(135deg,#ef4444,#f97316);border-color:transparent;color:#fff;animation:pulse 1.2s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.4)}50%{box-shadow:0 0 0 9px rgba(239,68,68,0)}}
.hint{text-align:center;font-size:10.5px;color:var(--faint);margin-top:8px}
@media(max-width:860px){aside{display:none}.bubble{max-width:88%}}
</style></head>
<body>
<aside>
  <div class="sb-head">
    <div class="logo">R</div>
    <div class="brand"><h1>Aira</h1><p>Your AI, on your Mac</p>
      <span class="pill"><i></i>Online · DeepSeek</span>
    </div>
  </div>
  <div class="tabs">
    <button id="tab-m" class="on">Messages</button>
    <button id="tab-f">Files</button>
    <button id="tab-a">About</button>
  </div>
  <div class="search"><span>⌕</span><input id="q" placeholder="Search…" autocomplete="off"></div>
  <div id="tab-m-wrap">
    <div class="sched">
      <h3>Today</h3>
      <div class="meet"><span class="t">09:00</span><span class="d"></span>Daily stand-up</div>
      <div class="meet"><span class="t">13:00</span><span class="d"></span>Meeting · NAM</div>
      <div class="meet"><span class="t">15:00</span><span class="d"></span>Customer support</div>
    </div>
    <div class="sb-label">Chats</div>
    <div class="conv on">
      <div class="av online">R</div>
      <div><div class="cname">Rohit</div><div class="csub">Your assistant, live</div></div>
      <span class="ctime">now</span>
    </div>
  </div>
  <div id="tab-f-wrap" style="display:none">
    <div class="sb-label">~/aira/data · output files</div>
    <div id="filelist"></div>
  </div>
  <div id="tab-a-wrap" style="display:none">
    <div class="card"><b>Aira — your friend &amp; growth co-pilot</b>
      <p>First a friend, then a founder's right hand. Lives on your Mac, thinks on DeepSeek, free.</p></div>
    <div class="card"><b>What I can do</b>
      <span class="tag">Open apps</span><span class="tag">Run shell</span><span class="tag">Read/write files</span>
      <span class="tag">Web research → CSV</span><span class="tag">LinkedIn rewrites</span><span class="tag">Email digest</span>
      <span class="tag">Voice replies</span><span class="tag">Scheduled jobs</span></div>
    <div class="card"><b>Safety</b>
      <p>Safe actions run instantly. Anything destructive pauses for your <b>Approve / Deny</b> — nothing runs without you.</p></div>
    <div class="card"><b>Brain</b>
      <p>DeepSeek via Cloudflare free tier · 10k neurons/day · multi-agent loop (Planner → Doer → Editor)</p></div>
  </div>
  <footer>localhost · 127.0.0.1:8756<br>Your data never leaves this Mac.</footer>
</aside>
<main>
  <div class="topbar">
    <div class="tb-l">
      <div class="tb-av">R</div>
      <div><div class="tb-name">Rohit</div>
        <div class="tb-sub"><i></i>Aira is listening</div></div>
    </div>
    <div class="tb-r">
      <button id="voice" title="Speak replies"><span class="vdot"></span>Voice</button>
      <span class="badge">localhost</span>
    </div>
  </div>
  <div id="log"></div>
  <div class="composer">
    <div class="cwrap">
      <textarea id="in" rows="1" placeholder="Message Aira… or press 🎙 and talk" autofocus></textarea>
      <button class="iconbtn" id="mic" title="Speak to Aira">🎙</button>
      <button id="send" title="Send">➤</button>
    </div>
    <div class="hint">"Hey Aira" · "open WhatsApp" · "research AI agents → CSV" · "rewrite this for LinkedIn"</div>
  </div>
</main>
<script>
const log=document.getElementById('log'),inp=document.getElementById('in');
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function bubble(text,cls){const row=document.createElement('div');row.className='row '+cls;
 let b='';
 if(cls==='aira')b+='<div class="avatar">R</div>';
 else if(cls==='user')b+='<div class="avatar">YOU</div>';
 row.innerHTML=b+'<div class="bubble"></div>';
 row.querySelector('.bubble').textContent=text;
 log.appendChild(row);log.scrollTop=log.scrollHeight;return row.querySelector('.bubble')}
function typing(row){row.querySelector('.bubble').innerHTML='<div class="typing"><i></i><i></i><i></i></div>'}
async function load(){const r=await fetch('/api/history');const h=await r.json();
 log.innerHTML='';h.forEach(m=>{if(m.role!=='system')bubble(m.content,m.role==='user'?'user':'aira')});checkPending()}
async function send(){const t=inp.value.trim();if(!t)return;inp.value='';inp.style.height='auto';
 bubble(t,'user');const row=document.createElement('div');row.className='row aira';
 row.innerHTML='<div class="avatar">R</div><div class="bubble"></div>';log.appendChild(row);typing(row);
 try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})});
 const j=await r.json();row.querySelector('.bubble').textContent=j.reply||'error'}
 catch(e){row.querySelector('.bubble').textContent='Aira is offline'}
 log.scrollTop=log.scrollHeight;checkPending()}
async function checkPending(){try{const r=await fetch('/api/pending');const j=await r.json();
 const old=document.querySelector('.approve');if(old)old.remove();
 if(j.question){const d=document.createElement('div');d.className='approve';
  d.innerHTML='<b>⚠ Approval needed</b><div class="q">'+esc(j.question)+'</div>'+
  '<div class="btns"><button class="btn ok" onclick="answer(1)">✓ Approve</button>'+
  '<button class="btn no" onclick="answer(0)">✕ Deny</button></div>';log.appendChild(d)}}catch(e){}}
async function answer(v){const r=await fetch('/api/pending',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approve:!!v})});
 await r.json();load()}
document.getElementById('send').onclick=send;
inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
inp.addEventListener('input',()=>{inp.style.height='auto';inp.style.height=Math.min(inp.scrollHeight,130)+'px'});
/* tabs */
const tab=(btn,wrap,on)=>{document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('on'));
 btn.classList.add('on');['tab-m-wrap','tab-f-wrap','tab-a-wrap'].forEach(id=>{document.getElementById(id).style.display='none'});
 document.getElementById(wrap).style.display='block';if(on)on()};
document.getElementById('tab-m').onclick=()=>tab(document.getElementById('tab-m'),'tab-m-wrap');
document.getElementById('tab-f').onclick=()=>tab(document.getElementById('tab-f'),'tab-f-wrap',loadFiles);
document.getElementById('tab-a').onclick=()=>tab(document.getElementById('tab-a'),'tab-a-wrap');
async function loadFiles(){try{const r=await fetch('/api/files');const j=await r.json();
 const el=document.getElementById('filelist');
 if(!j.files||!j.files.length){el.innerHTML='<div class="csub" style="padding:8px 12px">No output files yet.</div>';return}
 el.innerHTML='';
 j.files.forEach(f=>{const d=document.createElement('div');d.className='file';
  const icon=f.name.endsWith('.csv')?'📊':f.name.endsWith('.json')?'🧾':f.name.endsWith('.mp3')?'🎵':'📄';
  const sz=f.size>1048576?(f.size/1048576).toFixed(1)+' MB':f.size>1024?(f.size/1024).toFixed(1)+' KB':f.size+' B';
  const dt=new Date(f.modified*1000).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  d.innerHTML='<div class="fic">'+icon+'</div><div><div class="fname">'+esc(f.name)+'</div><div class="fmeta">'+sz+' · '+dt+'</div></div>';
  el.appendChild(d)})}catch(e){document.getElementById('filelist').innerHTML='<div class="csub" style="padding:8px 12px">Could not load files.</div>'}}
/* voice */
const mic=document.getElementById('mic'),voiceBtn=document.getElementById('voice');
let voiceOn=localStorage.getItem('rasVoice')==='1';
function setVoice(v){voiceOn=v;voiceBtn.classList.toggle('on',v);localStorage.setItem('rasVoice',v?'1':'0')}
setVoice(voiceOn);
function speak(text){
 if(!voiceOn||!('speechSynthesis' in window)||!text)return;
 speechSynthesis.cancel();
 const clean=text.replace(/```[\s\S]*?```/g,' ').replace(/[#*_>`~]/g,' ').replace(/\s+/g,' ').trim();
 if(!clean)return;
 const u=new SpeechSynthesisUtterance(clean);
 u.rate=1.02;u.pitch=1;u.lang='en-IN';
 const vs=speechSynthesis.getVoices().filter(v=>/en(-|_)?(IN|GB)/i.test(v.lang));
 if(vs.length)u.voice=vs[0];
 speechSynthesis.speak(u);
}
voiceBtn.onclick=()=>{setVoice(!voiceOn);if(!voiceOn)speechSynthesis.cancel()};
if('speechSynthesis' in window)speechSynthesis.onvoiceschanged=()=>speechSynthesis.getVoices();
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
if(SR){
 const rec=new SR();rec.lang='en-IN';rec.interimResults=true;rec.continuous=false;
 let listening=false;
 rec.onresult=e=>{
  let t='';
  for(let i=0;i<e.results.length;i++)t+=e.results[i][0].transcript;
  inp.value=t;inp.style.height='auto';inp.style.height=Math.min(inp.scrollHeight,130)+'px'};
 rec.onend=()=>{mic.classList.remove('on');listening=false;
  if(inp.value.trim())send()};
 rec.onerror=()=>{mic.classList.remove('on');listening=false};
 mic.onclick=()=>{
  if(listening){rec.stop();mic.classList.remove('on');return}
  try{rec.start();mic.classList.add('on');listening=true}
  catch(e){alert('Microphone blocked — allow mic access in the browser and try again')}};
}else mic.style.display='none';
setInterval(()=>{const bb=document.querySelector('.row.aira .bubble');
 if(voiceOn&&bb&&!bb.dataset.said){bb.dataset.said='1';speak(bb.textContent)}},1200);
load();setInterval(checkPending,1500);
</script></body></html>"""


class WebSession:
    def __init__(self):
        self.messages = []
        self.resolvers = {}
        self.pending_question = None

    def post_text(self, text, channel_override=None):
        self.messages.append({"role": "system", "content": text})

    def post_file(self, path, title="Aira output"):
        self.messages.append({"role": "system", "content": f"[file] {title}: {path}"})

    def ask_approval(self, question, force_auto=False):
        if force_auto:
            return True
        event = threading.Event()
        aid = f"web_{len(self.resolvers)}"
        self.resolvers[aid] = event
        self.pending_question = question
        answered = event.wait(timeout=600)
        self.resolvers.pop(aid, None)
        self.pending_question = None
        return answered and getattr(event, "approved", False)

    def resolve(self, approved):
        for event in self.resolvers.values():
            event.approved = approved
            event.set()


class Handler(BaseHTTPRequestHandler):
    session = WebSession()
    brain = None
    config = None
    summon_pending = False

    @classmethod
    def summon(cls):
        """Ask the popup to show itself (used when 'Hey Aira' wakes Aira)."""
        cls.summon_pending = True

    def log_message(self, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/history":
            public = [{"role": m["role"], "content": m["content"]} for m in Handler.session.messages if m["role"] != "system"]
            return self._json({"history": public})
        if self.path == "/api/summon":
            pending = Handler.summon_pending
            Handler.summon_pending = False
            return self._json({"summon": pending})
        if self.path == "/api/pending":
            return self._json({"question": Handler.session.pending_question})
        if self.path == "/api/files":
            data_dir = Path.home() / "aira" / "data"
            files = []
            if data_dir.exists():
                for p in sorted(data_dir.iterdir(), key=lambda p: -p.stat().st_mtime if p.is_file() else 0):
                    if p.is_file():
                        files.append({"name": p.name, "size": p.stat().st_size, "modified": p.stat().st_mtime})
            return self._json({"files": files[:60]})
        if self.path.startswith("/api/audio/"):
            name = urllib.parse.unquote(self.path.rsplit("/", 1)[-1])
            audio = (AUDIO_DIR / name).resolve()
            if not audio.is_file() or audio.parent != AUDIO_DIR.resolve():
                return self._json({"error": "not found"}, 404)
            body = audio.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        ctype = self.headers.get("Content-Type", "").lower()
        if self.path == "/api/stt" and "audio/wav" in ctype:
            return self._stt()
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/chat":
            message = payload.get("message", "")
            Handler.session.messages.append({"role": "user", "content": message})
            low = re.sub(r"[^a-z\s]", "", message.lower()).strip()
            if re.fullmatch(r"(hey\s+)?aira", low):
                reply = "Hi Rohit — Aira here. What are we building today?"
                Handler.session.messages.append({"role": "assistant", "content": reply})
                return self._json({"reply": reply})
            try:
                reply = Handler.brain.respond([{"role": "user", "content": message}] + [{"role": "user", "content": m["content"]} for m in Handler.session.messages if m["role"] == "user"][:-1])
            except Exception as exc:
                reply = f"Aira hit an error: {type(exc).__name__}: {exc}"
            Handler.session.messages.append({"role": "assistant", "content": reply})
            return self._json({"reply": reply})
        if self.path == "/api/pending":
            Handler.session.resolve(bool(payload.get("approve")))
            return self._json({"ok": True})
        if self.path == "/api/tts":
            text = (payload.get("text") or "").strip()
            if not text:
                return self._json({"error": "no text"}, 400)
            try:
                audio = tts.generate(text, voice=Handler.config.tts_voice())
            except Exception as exc:
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._json({"url": f"/api/audio/{audio.name}"})
        self._json({"error": "not found"}, 404)

    def _stt(self):
        length = int(self.headers.get("Content-Length", 0))
        wav_bytes = self.rfile.read(length)
        if len(wav_bytes) < 100:
            return self._json({"error": "clip too short"}, 400)
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        try:
            tmp.write_bytes(wav_bytes)
            result = voice.transcribe(tmp, Handler.config)
        except Exception as exc:
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        finally:
            tmp.unlink(missing_ok=True)
        if not result.get("ok"):
            return self._json({"error": result.get("error", "stt failed")}, 500)
        return self._json({"text": result.get("text", "")})


def make_server(config):
    """Build (but don't run) the server, wiring the shared session + brain so
    both the popup/web UI and the background 'Hey Aira' listener use the same
    conversation, approval flow, and agentic engine."""
    session = Handler.session
    executor = ToolExecutor(session, config)
    Handler.brain = Brain(config, executor)
    Handler.config = config
    return ThreadingHTTPServer((HOST, PORT), Handler)


def start_web(config, open_browser=True):
    server = make_server(config)
    if open_browser:
        import webbrowser
        threading.Timer(0.6, webbrowser.open, args=(f"http://{HOST}:{PORT}/",)).start()
    print(f"Aira web UI running at http://{HOST}:{PORT}")
    server.serve_forever()
