"""Single-page live mus table (served by live_server.py). No dependencies:
vanilla JS over Server-Sent Events, dark casino-table look."""

INDEX_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mus en vivo — mus_bench</title>
<style>
:root{
  --bg:#0c0f14; --felt:#123524; --felt2:#0e2a1d; --panel:#151a22; --panel2:#1b2230;
  --line:#2a3242; --txt:#e8e6df; --dim:#98a2b3; --gold:#d9a441; --red:#e05252;
  --blue:#5b8dd9; --green:#43a05c; --teamA:#e0b34d; --teamB:#5f9fe0;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;font-size:14px}
button{font:inherit;cursor:pointer}
h3{margin:0 0 8px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
a{color:var(--gold)}

#app{display:grid;grid-template-rows:auto 1fr auto;height:100vh}

/* ---------- header ---------- */
header{display:flex;align-items:center;gap:14px;padding:8px 16px;
  background:var(--panel);border-bottom:1px solid var(--line)}
header .title{font-weight:700;letter-spacing:.18em;color:var(--gold)}
header .title small{display:block;font-size:10px;color:var(--dim);letter-spacing:.05em}
.scorechip{display:flex;align-items:center;gap:8px;background:var(--panel2);
  border:1px solid var(--line);border-radius:8px;padding:4px 12px}
.scorechip .lbl{font-size:11px;color:var(--dim)}
.scorechip .pts{font-size:22px;font-weight:700}
.scorechip .vacas{font-size:11px;color:var(--dim)}
.vdots{display:inline-flex;gap:2px;vertical-align:middle}
.vdots i{width:8px;height:8px;border-radius:2px;background:#2a3242;display:inline-block}
.vdots i.on{background:var(--gold)}
#status{font-size:11px;color:var(--dim);margin-left:auto}
#newmatch{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
  border-radius:8px;padding:6px 12px}
#newmatch:hover{border-color:var(--gold)}

/* ---------- main ---------- */
main{display:grid;grid-template-columns:1fr 360px;min-height:0}

/* the table */
#tablewrap{position:relative;overflow:auto;
  background:
    radial-gradient(ellipse at 50% 45%, #1a5c3c 0%, var(--felt) 45%, var(--felt2) 100%);
  border-right:1px solid var(--line)}
#board{position:relative;min-height:560px;height:100%}

.seat{position:absolute;width:240px;background:rgba(10,14,10,.82);
  border:1px solid var(--line);border-radius:12px;padding:8px 10px;
  transition:box-shadow .3s}
.seat.me{width:300px}
.seat.s0{bottom:14px;left:50%;transform:translateX(-50%)}
.seat.s1{top:50%;right:12px;transform:translateY(-58%)}
.seat.s2{top:12px;left:50%;transform:translateX(-50%)}
.seat.s3{top:50%;left:12px;transform:translateY(-58%)}
.seat.turn{box-shadow:0 0 0 2px var(--gold), 0 0 22px rgba(217,164,65,.35)}
.seat .head{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.seat .name{font-weight:600}
.seat .badge{font-size:10px;padding:1px 6px;border-radius:6px;
  border:1px solid var(--line);color:var(--dim)}
.seat .badge.mano{color:#111;background:var(--gold);border-color:var(--gold);font-weight:700}
.seat .badge.tA{border-color:var(--teamA);color:var(--teamA)}
.seat .badge.tB{border-color:var(--teamB);color:var(--teamB)}
.seat .badge.out{border-color:var(--red);color:var(--red)}
.thinking{font-size:10px;color:var(--gold);animation:pulse 1.1s infinite}
@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
.hole{display:flex;gap:5px;margin-top:8px;justify-content:center}
.hole .card{opacity:.92}
.facedown{width:34px;height:48px;border-radius:5px;
  background:repeating-linear-gradient(45deg,#274472 0 6px,#1d3555 6px 12px);
  border:1px solid #3a5c94}

/* cards */
.card{position:relative;width:52px;height:74px;border-radius:6px;background:#f4efe4;
  color:#222;box-shadow:0 2px 5px rgba(0,0,0,.45);flex:none;user-select:none}
.card .r{position:absolute;top:3px;left:6px;font-weight:700;font-size:15px}
.card .s{position:absolute;bottom:4px;right:6px;font-weight:700;font-size:13px;
  width:20px;height:20px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;color:#fff;font-size:11px}
.card .big{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:19px;font-weight:700;opacity:.85}
.card.oros .s{background:var(--gold)} .card.copas .s{background:#c0392b}
.card.espadas .s{background:#34495e} .card.bastos .s{background:#27ae60}
.card.sel{outline:3px solid var(--gold);transform:translateY(-8px)}
#mycards{display:flex;gap:8px;margin-top:8px;justify-content:center}

.sena-bubble{position:absolute;top:-14px;right:-10px;background:#111;
  border:1px solid var(--gold);color:var(--gold);border-radius:8px;
  font-size:10px;padding:3px 7px;max-width:190px;animation:pop .25s}
.sena-bubble .m{color:var(--dim);display:block}
@keyframes pop{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}

/* center of table */
#center{position:absolute;left:50%;top:46%;transform:translate(-50%,-50%);
  text-align:center;pointer-events:none;width:340px}
#phase{font-size:12px;letter-spacing:.22em;color:#f5e9c8;text-transform:uppercase;
  text-shadow:0 1px 3px #000}
#lance{font-size:22px;font-weight:700;color:#fff;text-shadow:0 2px 6px #000}
#enviteline{margin-top:6px;font-size:12px;color:#cfd8cf}
#enviteline b{color:var(--gold)}
.deckpile{margin:10px auto 0;width:58px;height:82px;border-radius:7px;position:relative}
.deckpile{background:repeating-linear-gradient(45deg,#274472 0 7px,#1d3557 7px 14px);
  border:2px solid #8a6d3b;box-shadow:2px 2px 0 #6b5327,4px 4px 0 #4e3d1d,0 6px 14px rgba(0,0,0,.5)}
#caughtline{margin-top:10px;font-size:12px;color:var(--gold);min-height:18px}
#caughtline .chip{background:#111;border:1px solid var(--gold);border-radius:8px;
  padding:3px 8px;display:inline-block;margin:2px}

/* ---------- sidebar ---------- */
aside{display:flex;flex-direction:column;min-height:0;background:var(--panel)}
.tabs{display:flex;border-bottom:1px solid var(--line)}
.tabs button{flex:1;background:none;border:none;color:var(--dim);padding:9px 4px;
  border-bottom:2px solid transparent;font-size:12px}
.tabs button.on{color:var(--txt);border-bottom-color:var(--gold)}
.tabpane{flex:1;overflow:auto;padding:10px;display:none;min-height:0}
.tabpane.on{display:block}
#feed{display:flex;flex-direction:column;gap:4px;font-size:12px}
#feed .ev{padding:4px 8px;border-radius:6px;background:var(--panel2);
  border-left:3px solid var(--line);color:var(--dim)}
#feed .ev .hh{color:#556;font-size:10px;margin-right:5px}
#feed .ev.k-chat{border-left-color:var(--blue);color:var(--txt)}
#feed .ev.k-sena{border-left-color:var(--gold);color:var(--gold)}
#feed .ev.k-sena .gest{color:#111;background:var(--gold);border-radius:5px;
  padding:0 4px;font-weight:600}
#feed .ev.k-sena_caught{border-left-color:var(--gold);color:var(--gold)}
#feed .ev.k-vaca{border-left-color:var(--gold);color:var(--gold);font-weight:700}
#feed .ev.k-hand_end,#feed .ev.k-hand_start{border-left-color:var(--green);color:var(--txt)}
#feed .ev.k-rejected,#feed .ev.k-api_error,#feed .ev.k-timeout,#feed .ev.k-error
  {border-left-color:var(--red);color:var(--red)}
#feed .ev.k-match,#feed .ev.k-match_end{border-left-color:var(--gold);color:var(--txt);font-weight:600}

.sena-grid{display:grid;grid-template-columns:1fr;gap:5px}
.sena-btn{display:flex;flex-direction:column;align-items:flex-start;gap:1px;
  background:var(--panel2);border:1px solid var(--line);border-radius:8px;
  padding:7px 10px;color:var(--txt);text-align:left}
.sena-btn:hover{border-color:var(--gold)}
.sena-btn .g{font-weight:600;color:var(--gold)}
.sena-btn .m{font-size:11px;color:var(--dim)}
#mysenas{margin-top:12px;font-size:12px;color:var(--dim)}
#mysenas .row{display:flex;justify-content:space-between;padding:3px 6px;
  border-bottom:1px dashed var(--line)}
.tr-y{color:var(--green)} .tr-n{color:var(--red)}

.hist-block{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:10px}
.hist-block .hd{display:flex;justify-content:space-between;color:var(--dim);font-size:12px}
.hist-block .jug{font-size:12px;margin-top:4px;line-height:1.5}
.jug .wA{color:var(--teamA)} .jug .wB{color:var(--teamB)}
.hist-block .hcards{font-size:11px;color:var(--dim);margin-top:4px;line-height:1.5}
.hist-block .th{font-size:11px;color:var(--dim);margin-top:6px;padding-left:8px;
  border-left:2px solid var(--line);white-space:pre-wrap}
.rules p{font-size:12px;color:var(--dim);line-height:1.55;margin:0 0 8px}
.rules table{width:100%;font-size:11px;border-collapse:collapse}
.rules td{border-top:1px solid var(--line);padding:3px 4px;vertical-align:top}
.rules td:first-child{color:var(--gold);white-space:nowrap}

/* bench tab */
.btable{width:100%;font-size:11px;border-collapse:collapse;margin-bottom:10px}
.btable th{color:var(--dim);font-weight:600;text-align:left;padding:4px 6px;
  border-bottom:1px solid var(--line);white-space:nowrap}
.btable td{padding:4px 6px;border-top:1px solid var(--line);white-space:nowrap}
.btable td.num{text-align:right;font-variant-numeric:tabular-nums}
.btable tr:first-child td{color:var(--gold)}
.bmatch{border:1px solid var(--line);border-radius:8px;padding:7px 10px;margin-bottom:8px;font-size:12px}
.bmatch .hd{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
.bmatch .hd b{color:var(--txt)}
.bmatch .sub{color:var(--dim);font-size:11px;margin-top:3px;line-height:1.5}
.bmatch.fail{border-left:3px solid var(--red)}
.bmatch.done{border-left:3px solid var(--green)}
.bmatch.degraded{border-left:3px solid #c90}
.badge-st{font-size:10px;padding:1px 6px;border-radius:6px;border:1px solid var(--line);color:var(--dim)}
.badge-st.done{color:var(--green);border-color:var(--green)}
.badge-st.degraded{color:#c90;border-color:#c90}
.badge-st.failed{color:var(--red);border-color:var(--red)}
.va{color:var(--teamA);font-weight:700}.vb{color:var(--teamB);font-weight:700}

/* ---------- action bar ---------- */
#actionbar{min-height:64px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:10px 14px;background:var(--panel);border-top:1px solid var(--line)}
#actionbar .wait{color:var(--dim);font-size:13px}
.abtn{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
  border-radius:10px;padding:10px 18px;font-size:15px;font-weight:600}
.abtn:hover{border-color:var(--gold);color:var(--gold)}
.abtn.primary{border-color:var(--gold);color:var(--gold)}
.abtn.danger{border-color:var(--red);color:var(--red)}
.abtn:disabled{opacity:.4;cursor:default}
#chatline{display:flex;gap:6px;align-items:center;margin-left:auto}
#chatinput{width:200px;background:#0d1117;border:1px solid var(--line);
  color:var(--txt);border-radius:8px;padding:7px 10px}
#sendchat{background:var(--panel2);border:1px solid var(--line);color:var(--dim);
  border-radius:8px;padding:7px 10px}
#errbanner{display:none;background:#3a1414;border:1px solid var(--red);
  color:#f2b8b8;border-radius:8px;padding:6px 12px;font-size:12px}

/* reveal overlay */
#overlay{position:fixed;inset:0;background:rgba(5,8,6,.86);display:none;
  z-index:50;padding:24px;overflow:auto}
#overlay.on{display:block}
#reveal{max-width:860px;margin:0 auto;background:var(--panel);
  border:1px solid var(--gold);border-radius:14px;padding:20px}
#reveal h2{margin:0 0 4px;color:var(--gold);font-size:18px}
#reveal .sub{color:var(--dim);font-size:12px;margin-bottom:14px}
.revhands{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.revseat{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px}
.revseat .cards{display:flex;gap:6px;margin:8px 0}
.thbox{font-size:11px;color:var(--dim);border-left:2px solid var(--line);
  padding-left:8px;margin-top:6px;white-space:pre-wrap}
#revclose{float:right;background:none;border:1px solid var(--line);color:var(--dim);
  border-radius:8px;padding:4px 10px}
.juglist{font-size:12px;line-height:1.7;margin-top:6px}
</style>
</head>
<body>
<div id="app">
  <header>
    <div class="title">MUS EN VIVO<small>mus_bench · mesa en tiempo real</small></div>
    <div class="scorechip"><span class="lbl">EQUIPO A</span>
      <span class="pts" id="pa">0</span>
      <span class="vacas">vacas <span class="vdots" id="va"></span></span></div>
    <div class="scorechip"><span class="lbl">EQUIPO B</span>
      <span class="pts" id="pb">0</span>
      <span class="vacas">vacas <span class="vdots" id="vb"></span></span></div>
    <div id="status">conectando…</div>
    <button id="newmatch" title="Empieza otra partida con los mismos jugadores">Nueva partida</button>
  </header>

  <main>
    <div id="tablewrap"><div id="board">
      <div class="seat s3" id="seat3"></div>
      <div class="seat s1" id="seat1"></div>
      <div class="seat s2" id="seat2"></div>
      <div class="seat s0" id="seat0"></div>
      <div id="center">
        <div id="phase">—</div>
        <div id="lance">esperando…</div>
        <div id="enviteline"></div>
        <div class="deckpile deck" id="deck"></div>
        <div id="caughtline"></div>
      </div>
    </div></div>

    <aside>
      <div class="tabs">
        <button data-t="feed" class="on">Mesa</button>
        <button data-t="senas">Señas</button>
        <button data-t="hist">Historial</button>
        <button data-t="bench">Bench</button>
        <button data-t="rules">Reglas</button>
      </div>
      <div class="tabpane on" id="tab-feed"><div id="feed"></div></div>
      <div class="tabpane" id="tab-senas">
        <h3>Haz una seña a tu compañero</h3>
        <div style="font-size:11px;color:var(--dim);margin-bottom:8px">
          Gestos reglamentarios, significado fijo. Llegan en la <b>próxima</b>
          decisión de tu compañero (caducan si tarda). Los rivales no las ven.</div>
        <div class="sena-grid" id="senagrid"></div>
        <div id="mysenas"></div>
      </div>
      <div class="tabpane" id="tab-hist"><div id="hist"></div></div>
      <div class="tabpane" id="tab-bench">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h3>Resultados del bench</h3>
          <button id="benchrefresh" style="background:var(--panel2);
            border:1px solid var(--line);color:var(--dim);border-radius:8px;
            padding:4px 10px;font-size:11px">refrescar</button>
        </div>
        <div id="benchmeta" style="font-size:11px;color:var(--dim);margin-bottom:8px"></div>
        <div id="benchlb"></div>
        <h3 style="margin-top:14px">Partidas</h3>
        <div id="benchmatches"></div>
      </div>
      <div class="tabpane rules" id="tab-rules">
        <p><b>Mus</b>: si todos dicen «mus», se descarta de 1 a 4 cartas y se repite.
        Un solo «no» fuerza a jugar con lo que hay.</p>
        <p><b>Lances en orden</b>: Grande, Chica, Pares, Juego. Pares y Juego abren
        con declaración veraz (tengo / no-tengo). Sin pares no hay envite de pares;
        sin juego en ninguna mesa, se juega al punto.</p>
        <p><b>Envites</b>: envido=2, «y yo»=+2, reenvido=dobla, quiero=fija la
        apuesta (se cobra al enseñar), no-quiero=el que cantó cobra la apuesta
        anterior (o 1 de envido) y el valor de la jugada. Órdago: todo el juego
        (40 piedras) a la comparación de las jugadas.</p>
        <p><b>Valores</b>: rey=tres=10 (valen lo mismo), sota=caballo=10 para el
        juego, as=dos=1. Juego: 31 &gt; 32 &gt; 40 &gt; 39 &gt; … &gt; 33. <b>Vaca</b>: 40 piedras.</p>
        <p><b>Señas</b> (Fournier + Don Naipe), significado único:</p>
        <table id="senatable"></table>
      </div>
    </aside>
  </main>

  <div id="actionbar">
    <span id="waitmsg"></span>
    <div id="btns" style="display:flex;gap:8px;flex-wrap:wrap"></div>
    <div id="errbanner"></div>
    <div id="chatline">
      <input id="chatinput" placeholder="habla en la mesa (sin cartas)…" maxlength="120">
      <button id="sendchat">Decir</button>
    </div>
  </div>
</div>

<div id="overlay"><div id="reveal">
  <h2 id="revtitle">Fin de la mano</h2>
  <div class="sub">Cartas y razonamientos privados, revelados al acabar la mano</div>
  <button id="revclose" style="float:right">cerrar</button>
  <div class="revhands" id="revhands"></div>
  <div class="juglist" id="revjug"></div>
</div></div>

<script>
'use strict';
const params = new URLSearchParams(location.search);
const TOKEN = params.get('token') || null;
const $ = id => document.getElementById(id);
let S = null;            // last snapshot
let selected = new Set();// cards selected for discard
let lastRev = null;
let lastSena = {};       // seat -> recent sena bubble

const RANKS = {as:'As', dos:'2', tres:'3', cuatro:'4', cinco:'5', seis:'6',
  siete:'7', sota:'Sota', caballo:'Cab', rey:'Rey'};
const SUIT = {oros:'O', copas:'C', espadas:'E', bastos:'B'};

function cardEl(name, clickable, selectedSet){
  const m = name.match(/^(\w+) de (\w+)$/); if(!m) return null;
  const d = document.createElement('div');
  d.className = 'card ' + m[2];
  d.innerHTML = '<span class="r">'+(RANKS[m[1]]||m[1])+'</span>'+
                '<span class="s">'+(SUIT[m[2]]||'?')+'</span>';
  if(clickable){
    d.style.cursor='pointer';
    d.onclick = () => {
      if(selectedSet.has(name)) {selectedSet.delete(name); d.classList.remove('sel');}
      else {selectedSet.add(name); d.classList.add('sel');}
      syncDiscardBtn();
    };
  }
  return d;
}
function cardHtml(name){
  const m = name.match(/^(\w+) de (\w+)$/); if(!m) return name;
  return '<span style="color:'+({oros:'var(--gold)',copas:'#e07070',espadas:'#8fb6e8',bastos:'#7ed49a'}[m[2]])+'">'+
    (RANKS[m[1]]||m[1])+(SUIT[m[2]]||'')+'</span>';
}

/* ---------- seats ---------- */
function renderSeat(el, s){
  const turn = S.turn === s.seat && S.status === 'running';
  el.className = 'seat s'+s.seat+(s.seat===(S.you?S.you.seat:-1)?' me':'')+
                 (turn?' turn':'');
  const decl = s.declared===true?'<span class="badge">¡tengo!</span>':
               s.declared===false?'<span class="badge">no tengo</span>':'';
  const mano = s.seat===S.mano?'<span class="badge mano">MANO</span>':'';
  let bubble = '';
  const bub = lastSena[s.seat];
  if(bub && Date.now()-bub.at < 6000){
    bubble = '<div class="sena-bubble">'+(bub.gesture?esc(bub.gesture):'hizo un gesto')+
             (bub.meaning?'<span class="m">'+esc(bub.meaning)+'</span>':'')+'</div>';
  }
  let body='';
  if(S.you && S.you.seat===s.seat){
    body = '<div id="mycards" class="hole"></div>';
  } else if(S.reveal && S.reveal.hands[s.seat]){
    body = '<div class="hole">'+S.reveal.hands[s.seat].map(c=>{
      const e=cardEl(c,false); return e?e.outerHTML:'';}).join('')+'</div>';
  } else {
    body = '<div class="hole">'+'<div class="facedown"></div>'.repeat(4)+'</div>';
  }
  el.innerHTML = '<div class="head"><span class="name">'+esc(s.name)+'</span>'+
    '<span class="badge t'+(s.team?'B':'A')+'">'+(s.team?'B':'A')+'</span>'+
    '<span class="badge">'+esc(s.model)+'</span>'+mano+decl+
    (s.folded?'<span class="badge out">fuera</span>':'')+
    (s.thinking?'<span class="thinking">pensando…</span>':'')+
    '</div>'+body+bubble;
  if(S.you && S.you.seat===s.seat){
    const mc = el.querySelector('#mycards');
    (S.you.hand||[]).forEach(c=>{
      const e=cardEl(c, (S.you.legal||[]).includes('discard'));
      if(e) mc.appendChild(e);
    });
  }
}

/* ---------- board ---------- */
function renderBoard(){
  const L = {MUS_REQUEST:'MUS', MUS_DRAW:'MUS — descartes', DECLARE:'DECLARACIÓN',
             ENVITE:'ENVITE', ORDAGO_RESPONSE:'ÓRDAGO', DONE:'FIN DE MANO'};
  $('phase').textContent = L[S.phase]||S.phase;
  $('lance').textContent = S.lance ? S.lance : (S.phase==='DONE'?'mano terminada':'—');
  let env='';
  if(S.envite && S.envite.current>0){
    env = 'apuesta pendiente <b>'+S.envite.current+'</b>'+
          (S.envite.previous>0?' (anterior '+S.envite.previous+')':'')+
          (S.envite.holder?(' · la tiene el asiento '+S.envite.holder+' (equipo '+
            (S.envite.holder.team?'B':'A')+')'):'')+
          (S.envite.folded.length?(' · fuera: '+S.envite.folded.join(', ')):'')+
          (S.envite.locked?' · <b>aceptada</b>':'');
  } else if(S.ordago){
    env = '¡<b>ÓRDAGO</b> del asiento '+S.ordago.caller+'! quiero = el juego entero.';
  } else if(S.phase==='MUS_REQUEST'){
    env = '¿mus o no hay mus?'+(S.mus_round?(' · ronda de descarte '+S.mus_round):'');
  } else if(S.phase==='DECLARE'){
    env = 'cada asiento canta tengo / no-tengo';
  } else if(S.phase==='MUS_DRAW'){
    env = 'los que pidieron mus descartan';
  }
  $('enviteline').innerHTML = env;
  $('pa').textContent = S.scores.points_a; $('pb').textContent = S.scores.points_b;
  $('va').innerHTML = vdots(S.scores.vacas_a); $('vb').innerHTML = vdots(S.scores.vacas_b);
  const cl = $('caughtline');
  if(S.you && S.you.caught && S.you.caught.length){
    cl.innerHTML = 'señas de tu compañero: '+S.you.caught.map(c=>
      '<span class="chip" title="'+esc(c.meaning)+'">'+esc(c.gesture)+'</span>').join(' ');
  } else cl.textContent='';
}
function vdots(n){
  let out=''; for(let i=0;i<Math.min(n,8);i++) out+='<i class="on"></i>';
  if(n>8) out += '+'+(n-8); return out;
}

/* ---------- feed ---------- */
function renderFeed(){
  const f = $('feed');
  const items = (S.feed||[]).slice(-160).reverse();
  f.replaceChildren(...items.map(ev=>{
    const d = document.createElement('div');
    d.className = 'ev k-'+ev.kind;
    let txt = esc(ev.text);
    if(ev.gesture) txt += ' <span class="chip" style="color:#111;background:var(--gold);border-radius:5px;padding:0 4px;font-weight:600">'
      + esc(ev.gesture) + '</span>';
    d.innerHTML = '<span class="hh">'+ev.hand+'</span>'+txt;
    return d;
  }));
}
function updateBubbles(){
  lastSena = {};
  (S.feed||[]).forEach(ev=>{
    if(ev.kind==='sena' && ev.gesture!==undefined && ev.gesture!==null){
      lastSena[ev.seat] = {gesture:ev.gesture, meaning:(S.senas_vocab||{})[ev.gesture]||'', at:Date.now()};
    }
  });
}

/* ---------- action bar ---------- */
const LABELS = {mus:'Mus', no:'No hay mus', ordago:'¡Órdago!', tengo:'¡Tengo!',
  'no-tengo':'No tengo', paso:'Paso', envido:'Envido (2)', 'y-yo':'¡Y yo! (+2)',
  reenvido:'Reenvido (×2)', quiero:'¡Quiero!', 'no-quiero':'No quiero',
  discard:'Descartar', __default:'Acción por defecto'};
function renderActions(){
  const bar=$('btns'); bar.replaceChildren();
  $('errbanner').style.display='none';
  $('waitmsg').textContent='';
  const y = S.you;
  if(!y){ $('waitmsg').textContent='modo espectador (sin asiento)'; return; }
  const myTurn = !!(y.legal && y.legal.length);
  if(!myTurn){
    const t = S.seats[S.turn];
    $('waitmsg').textContent = S.status==='running'
      ? 'turno de '+t.name+(t.thinking?' (pensando…)':'…') : '';
    return;
  }
  if(y.error){ $('errbanner').style.display='block'; $('errbanner').textContent='ACCIÓN RECHAZADA: '+y.error; }
  const legals = y.legal||[];
  if(legals.includes('discard')){
    const info=document.createElement('span');
    info.style.color='var(--dim)';
    info.textContent='Elige 1–4 cartas para descartar (se roban nuevas):';
    bar.appendChild(info);
    const btn=document.createElement('button'); btn.className='abtn primary';
    btn.id='discardbtn'; btn.textContent='Descartar (0)';
    btn.disabled=true;
    btn.onclick=()=>sendAction({action:'discard', cards:[...selected]});
    bar.appendChild(btn);
    const all=document.createElement('button'); all.className='abtn';
    all.textContent='Descartar las 4';
    all.onclick=()=>sendAction({action:'discard', cards:[...y.hand]});
    bar.appendChild(all);
  } else {
    legals.forEach(a=>{
      const b=document.createElement('button'); b.className='abtn';
      if(a==='ordago') b.classList.add('primary');
      b.textContent=LABELS[a]||a;
      b.onclick=()=>{ if(a==='ordago' && !confirm('¿Cantas ÓRDAGO? Todo el juego se decide con las jugadas.')) return;
        sendAction({action:a}); };
      bar.appendChild(b);
    });
  }
  const d=document.createElement('button'); d.className='abtn';
  d.title='Te sugerimos la acción legal por defecto (cuenta como fallback)';
  d.textContent='Pasar (auto)'; d.onclick=()=>sendAction({action:'__default__'});
  bar.appendChild(d);
}
function syncDiscardBtn(){
  const b=$('discardbtn'); if(!b) return;
  const n=selected.size; b.textContent='Descartar ('+n+')'; b.disabled=n<1;
}

/* ---------- send ---------- */
function sendAction(obj){
  fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:TOKEN, ...obj})})
   .then(r=>r.json()).then(d=>{ if(!d.ok) flash(d.error||'error'); });
}
function flash(t){ const e=$('errbanner'); e.style.display='block'; e.textContent=t;
  setTimeout(()=>{e.style.display='none';},4000); }
$('sendchat').onclick=()=>{
  const v=$('chatinput').value.trim(); if(!v) return;
  fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:TOKEN, text:v})}).then(()=>$('chatinput').value='');
};
$('chatinput').addEventListener('keydown',e=>{ if(e.key==='Enter') $('sendchat').onclick(); });
$('newmatch').onclick=()=>{
  const hands = prompt('¿Cuántas manos?', String((S.config&&S.config.hands)||12));
  if(!hands) return;
  fetch('/api/new',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:TOKEN, hands:parseInt(hands,10)})});
};

/* ---------- senas tab ---------- */
function renderSenas(){
  const g=$('senagrid'); if(g.childElementCount) return;
  Object.entries(S.senas_vocab||{}).forEach(([g2,m])=>{
    const b=document.createElement('button'); b.className='sena-btn';
    b.innerHTML='<span class="g">'+esc(g2)+'</span><span class="m">'+esc(m)+'</span>';
    b.onclick=()=>{
      fetch('/api/sena',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({token:TOKEN, gesture:g2})})
       .then(r=>r.json()).then(d=>{ if(!d.ok) flash(d.error); });
    };
    g.appendChild(b);
  });
  const t=$('senatable'); t.replaceChildren();
  Object.entries(S.senas_vocab||{}).forEach(([g2,m])=>{
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+esc(g2)+'</td><td>'+esc(m)+'</td>';
    t.appendChild(tr);
  });
  if(S.you && S.you.my_senas){
    $('mysenas').innerHTML='<h3>Tus señas (esta partida)</h3>'+
      S.you.my_senas.map(s=>'<div class="row"><span>'+esc(s.gesture)+
      (s.truthful?'<span class="tr-y"> · veraz</span>':'<span class="tr-n"> · bluff</span>')+
      '</span></div>').join('');
  }
}

/* ---------- bench results tab ---------- */
let benchData = null;
let benchTimer = null;
function loadBench(){
  return fetch('/api/results',{cache:'no-store'}).then(r=>r.json()).then(d=>{
    benchData = d; renderBench();
  }).catch(()=>{});
}
function fmtSenas(s){ if(!s) return '—'; return (s.published||0)+' pub · '+(s.caught||0)+' cap'; }
function renderBench(){
  const d = benchData; if(!d) return;
  $('benchmeta').textContent = (d.sources&&d.sources.length)
    ? ('fuentes: '+d.sources.join(' · ')) : 'aún no hay resultados en el directorio de resultados';
  const lb = $('benchlb');
  if(!(d.leaderboard||[]).length){
    lb.innerHTML = '<i style="color:var(--dim)">sin partidas completadas todavía — lanza run_tournament.py o run_llm_vs_baseline.py</i>';
  } else {
    const rows = d.leaderboard.map((k,i)=>{
      const share = (k.vacas_for+k.vacas_against)>0
        ? (100*k.vacas_for/(k.vacas_for+k.vacas_against)).toFixed(0)+'%' : '—';
      return '<tr><td>'+(i+1)+'</td><td>'+esc(k.model)+'</td>'+
        '<td class="num">'+k.matches+'</td>'+
        '<td class="num">'+k.wins+'-'+k.losses+'-'+k.ties+'</td>'+
        '<td class="num"><span class="va">'+k.vacas_for+'</span> / <span class="vb">'+k.vacas_against+'</span></td>'+
        '<td class="num">'+share+'</td>'+
        '<td class="num">'+k.senas_published+' / '+k.senas_caught+'</td>'+
        '<td class="num">'+k.bluffs+'</td>'+
        '<td class="num">'+k.fallbacks+'</td></tr>';
    }).join('');
    lb.innerHTML = '<table class="btable"><thead><tr>'+
      '<th>#</th><th>modelo</th><th>part.</th><th>V-D-E</th>'+
      '<th>vacas a fav / contra</th><th>share</th><th>señas p/c</th>'+
      '<th>bluffs</th><th>fb</th></tr></thead><tbody>'+rows+'</tbody></table>';
  }
  const bm = $('benchmatches');
  if(!(d.matches||[]).length){
    bm.innerHTML = '<i style="color:var(--dim)">sin partidas registradas</i>';
  } else {
    bm.replaceChildren(...d.matches.slice().reverse().map(m=>{
      const el=document.createElement('div');
      el.className='bmatch '+(m.status==='done'?'done':(m.status==='degraded'?'degraded':'fail'));
      const va = m.vacas_a==null?'—':'<span class="va">'+m.vacas_a+'</span>';
      const vb = m.vacas_b==null?'—':'<span class="vb">'+m.vacas_b+'</span>';
      let sub = 'seed '+m.seed+(m.hands!=null?(' · '+m.hands+' manos'):'')
        +(m.hand_wins!=null?(' · manos '+m.hand_wins):'')
        +(m.senas&&m.senas.published!=null&&m.senas.published!==0
          ? (' · señas '+fmtSenas(m.senas)) : '')
        +(m.fallbacks?(' · fallbacks '+m.fallbacks):'')
        +(m.elapsed!=null?(' · '+m.elapsed+'s'):'');
      el.innerHTML='<div class="hd"><b>'+esc(m.label)+'</b>'+
        '<span>'+va+' — '+vb+
        ' <span class="badge-st '+esc(m.status)+'">'+esc(m.status)+'</span></span></div>'+
        '<div class="sub">'+esc(sub)+'</div>';
      return el;
    }));
  }
}
$('benchrefresh').onclick=loadBench;
document.querySelector('[data-t="bench"]').addEventListener('click',()=>{
  loadBench();
  if(benchTimer) clearInterval(benchTimer);
  benchTimer = setInterval(()=>{ if(document.querySelector('[data-t="bench"]').classList.contains('on')) loadBench(); }, 20000);
});

/* ---------- history + reveal ---------- */
function teamName(t){ return t===0?'Equipo A':'Equipo B'; }
function renderHist(){
  const h=$('hist'); h.replaceChildren();
  (S.history||[]).slice().reverse().forEach(m=>{
    const d=document.createElement('div'); d.className='hist-block';
    const j=m.jugadas.map(j=>'<span class="'+(j.winner===0?'wA':j.winner===1?'wB':'')+'">'+
      j.name+(j.winner!=null?': '+teamName(j.winner):' (sin resolver)')+'</span>').join(' · ');
    d.innerHTML='<div class="hd"><b>Mano '+m.hand+'</b><span>+'+m.gain_a+' A / +'+m.gain_b+' B</span></div>'+
      '<div class="jug">'+j+'</div>'+
      '<div class="hcards">'+[0,1,2,3].map(s=>'<b>A'+s+'</b> '+m.hands[s].join(', ')).join('<br>')+'</div>';
    h.appendChild(d);
  });
  if(!(S.history||[]).length) h.innerHTML='<i style="color:var(--dim)">aún no hay manos terminadas</i>';
}
function renderReveal(){
  if(!S.reveal){ return; }
  if(S.reveal === lastRev) return;
  const justFinished = S.reveal.hand === S.scores.hands_played;
  lastRev = S.reveal;
  const r=S.reveal, ov=$('overlay');
  $('revtitle').textContent='Mano '+r.hand+' — revelación';
  const names=(S.seats||[]).map(s=>s.name);
  $('revhands').replaceChildren(...[0,1,2,3].map(s=>{
    const d=document.createElement('div'); d.className='revseat';
    d.innerHTML='<b>'+esc(names[s])+'</b> <span style="color:var(--dim)">(asiento '+s+' · equipo '+(s%2?'B':'A')+')</span>'+
      '<div class="cards">'+r.hands[s].map(c=>{
        const e=cardEl(c,false); return e?e.outerHTML:esc(c);}).join('')+'</div>'+
      ((r.thoughts||{})[s]||[]).slice(-1).map(t=>'<div class="th">pensó: '+esc(t)+'</div>').join('');
    return d;
  }));
  const jug=r.jugadas.map(j=>'<div>'+j.name+': <b class="'+(j.winner===0?'wA':j.winner===1?'wB':'')+'">'+
    (j.winner===null?'empate':teamName(j.winner))+'</b></div>').join('');
  $('revjug').innerHTML='<div class="juglist"><b>Jugadas:</b><br>'+jug+
    (r.senas&&r.senas.length?('<br><b>Señas de la mano:</b> '+r.senas.map(s=>
      'A'+s.from+'→A'+s.to+' '+esc(s.gesture)+(s.truthful?'':' (¡mentira!)')+
      (s.delivered?' ✓':' ✗no vista')).join(' · ')):'')+'</div>';
  if(justFinished) ov.classList.add('on');
}
$('revclose').onclick=()=>$('overlay').classList.remove('on');
$('overlay').onclick=e=>{ if(e.target.id==='overlay') $('overlay').classList.remove('on'); };

/* ---------- render loop ---------- */
function render(){
  if(!S) return;
  updateBubbles();
  [0,1,2,3].forEach(i=>renderSeat($('seat'+i), S.seats[i]));
  renderBoard(); renderFeed(); renderActions(); renderSenas(); renderHist(); renderReveal();
  $('status').textContent = S.status==='running'
    ? ('mano '+(S.scores.hands_played||0)+'/'+S.config.hands+' · v'+S.version)
    : S.status;
}
function esc(s){ return String(s??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('.tabpane').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); $('tab-'+b.dataset.t).classList.add('on');
});

/* ---------- SSE ---------- */
let lastVersion = -1;
function connect(){
  const url = '/events' + (TOKEN ? ('?token='+encodeURIComponent(TOKEN)) : '');
  const es = new EventSource(url);
  es.onmessage = m => { try{ S = JSON.parse(evData(m)); lastVersion=S.version; render(); }catch(e){} };
  es.onerror = () => { $('status').textContent='reconectando…'; };
}
function evData(m){ return m.data; }
connect();
</script>
</body>
</html>
"""
