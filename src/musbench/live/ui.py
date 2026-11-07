"""The live mus table: one page, vanilla JS over Server-Sent Events.

Served at / by musbench.live.server and published statically (see
publish/build_static_play.sh). It opens straight onto the table; the
Reglamento (animated rules) and Clasificacion (leaderboard) views are
hash routes on the same page, so the live game keeps streaming while you
read them.

Visual language: the "Mus" design export (Nocturne tokens on black, Inter,
blurple accent used as line and glow). Its key animations -- deal/rise,
breathe (pensando), speak bubbles, the split + slash "No hay mus" cut, the
ordago rings, envite piedra drops -- are driven by the event feed. Card
faces are the real Spanish deck from GET /cards/<name>.svg. Model icons are
@lobehub/icons-static-svg (MIT), inlined as data URIs.

Generated file layout: edit the HTML below directly.
"""

INDEX_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mus — la mesa</title>
<meta name="description" content="Siéntate a jugar al mus con tres modelos de lenguaje: uno de compañero y dos enfrente.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='43' fill='%23e8c057' stroke='%23a8761c' stroke-width='6'/%3E%3Ccircle cx='50' cy='50' r='12' fill='%23a8761c'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap">
<style>
/* Nocturne tokens (from the Mus design export) */
:root{
  --color-bg:#000;
  --color-surface:#0b0c12;
  --color-text:#e9e9ed;
  --color-accent:#9184d9;
  --color-neutral-100:#f3f5fe;--color-neutral-200:#e4e7f5;--color-neutral-300:#cfd3e5;
  --color-neutral-400:#b2b6ca;--color-neutral-500:#9397ab;--color-neutral-600:#75798c;
  --color-neutral-700:#595d6c;--color-neutral-800:#3f424d;--color-neutral-900:#292b31;
  --color-accent-100:#f5f4ff;--color-accent-200:#e7e5fe;--color-accent-300:#d2cefd;
  --color-accent-400:#b5abfc;--color-accent-500:#968ae0;--color-accent-600:#796cbf;
  --color-accent-700:#5d5294;--color-accent-800:#423a6a;--color-accent-900:#2b2741;
  --color-danger:#d99a9a;
  --font-heading:"Inter",system-ui,sans-serif;
  --font-body:"Inter",system-ui,sans-serif;
  --space-1:2.8px;--space-2:5.6px;--space-3:8.4px;--space-4:11.2px;--space-6:16.8px;--space-8:22.4px;
  --radius-md:8px;--radius-lg:14px;
  --gutter:clamp(16px,4vw,64px);
  --ease:cubic-bezier(.2,.7,.2,1);
  color-scheme:dark;
}
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;background:var(--color-bg);color:var(--color-text);font-family:var(--font-body);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
body{overflow-x:hidden}
a{color:var(--color-neutral-200);text-decoration:none}
a:hover{color:var(--color-text)}
button{font:inherit;color:inherit}
:focus{outline:none}
:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}
::selection{background:color-mix(in srgb,var(--color-accent) 30%,transparent)}
h1,h2,h3{font-family:var(--font-heading);margin:0}
.eyebrow{font-size:11px;letter-spacing:.28em;text-transform:uppercase;color:var(--color-neutral-500)}
.muted{color:var(--color-neutral-500)}

/* ── key animations (verbatim from the design) ── */
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes breathe{0%,100%{opacity:.35}50%{opacity:1}}
@keyframes speak{0%{opacity:0;transform:translateY(-6px);filter:blur(4px)}10%{opacity:1;transform:none;filter:blur(0)}78%{opacity:1;transform:none}100%{opacity:0;transform:translateY(5px);filter:blur(2px)}}
@keyframes fxDim{0%{opacity:0}12%{opacity:1}75%{opacity:1}100%{opacity:0}}
@keyframes ring{0%{transform:scale(.3);opacity:0}10%{opacity:.9}100%{transform:scale(4.5);opacity:0}}
@keyframes ordago{0%{opacity:0;letter-spacing:.6em;filter:blur(14px);transform:scale(1.15)}24%{opacity:1;letter-spacing:-.04em;filter:blur(0);transform:scale(1)}80%{opacity:1;transform:scale(1.02)}100%{opacity:0;transform:scale(1.06);filter:blur(6px)}}
@keyframes fxSub{0%,18%{opacity:0;transform:translateY(8px)}32%{opacity:1;transform:none}100%{opacity:1}}
@keyframes slash{0%{transform:scaleX(0);opacity:1}28%{transform:scaleX(1);opacity:1}70%{opacity:.6}100%{transform:scaleX(1);opacity:0}}
@keyframes splitUp{0%{opacity:0}12%{opacity:1;transform:none}30%{transform:none}45%{transform:translate(-10px,-9px)}100%{transform:translate(-22px,-16px);opacity:.9}}
@keyframes splitDown{0%{opacity:0}12%{opacity:1;transform:none}30%{transform:none}45%{transform:translate(10px,9px)}100%{transform:translate(22px,16px);opacity:.9}}
@keyframes popIn{0%{opacity:0;transform:scale(.8);filter:blur(8px)}22%{opacity:1;transform:none;filter:blur(0)}100%{opacity:1;transform:translateY(-6px)}}
@keyframes seatFx{0%{opacity:0;transform:scale(.85)}14%{opacity:1;transform:scale(1)}78%{opacity:1}100%{opacity:0;transform:translateY(-8px)}}
@keyframes dropIn{0%{opacity:0;transform:translateY(-48px)}60%{opacity:1;transform:translateY(3px)}100%{opacity:1;transform:none}}
@keyframes flip{0%{transform:rotateY(90deg);opacity:.4}100%{transform:none;opacity:1}}

/* ── header ── */
header.top{position:fixed;top:0;left:0;right:0;z-index:40;display:flex;align-items:center;gap:var(--space-6);
  padding:18px var(--gutter);background:linear-gradient(#000 45%,transparent)}
.brand{font-family:var(--font-heading);font-weight:500;font-size:15px;letter-spacing:.32em;color:var(--color-text)}
.status{display:flex;align-items:center;gap:8px;font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:var(--color-neutral-500);white-space:nowrap}
.status i{width:6px;height:6px;border-radius:50%;background:var(--color-neutral-700)}
.status.live i{background:var(--color-accent-300);box-shadow:0 0 10px var(--color-accent);animation:breathe 2.4s ease-in-out infinite}
.status.bad i{background:var(--color-danger)}
nav.views{display:flex;gap:var(--space-6);margin-left:auto;font-size:11px;letter-spacing:.24em;text-transform:uppercase}
nav.views a{padding:4px 0;border-bottom:1px solid transparent;transition:color .2s,border-color .2s;color:var(--color-neutral-400)}
nav.views a.on{color:var(--color-text);border-bottom-color:var(--color-neutral-600)}
nav.views a:hover{color:var(--color-accent-200)}
.ghost{background:none;border:1px solid var(--color-neutral-700);border-radius:999px;color:var(--color-neutral-300);
  font-family:var(--font-heading);font-size:10px;letter-spacing:.22em;text-transform:uppercase;padding:8px 14px;cursor:pointer;
  transition:all .25s;white-space:nowrap}
.ghost:hover{border-color:var(--color-accent);color:var(--color-accent-200)}
.ghost[hidden]{display:none}

/* ── views ── */
.view{display:none}
.view.on{display:block;animation:rise .5s var(--ease) both}

/* ── mesa ── */
#mesa.on{display:flex}
#mesa{min-height:100vh;min-height:100dvh;flex-direction:column;padding-top:64px}
.mesa-head{display:flex;align-items:center;gap:var(--space-6);padding:var(--space-4) var(--gutter) var(--space-3);flex-wrap:wrap}
.lineup{font-size:13px;color:var(--color-neutral-400);display:flex;gap:6px;flex-wrap:wrap;align-items:baseline}
.lineup b{font-weight:500}
.score{display:flex;align-items:baseline;gap:var(--space-4);margin-left:auto;font-family:var(--font-heading);font-variant-numeric:tabular-nums}
.score .k{font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--color-neutral-500)}
.score .v{font-size:28px;font-weight:300;letter-spacing:-.02em;transition:color .4s}
.score .v.bump{color:var(--color-accent-200)}
.score .dash{color:var(--color-neutral-700)}
.score .meta{font-size:11px;letter-spacing:.2em;color:var(--color-neutral-600);margin-left:var(--space-3)}
.vdots{display:inline-flex;gap:4px;margin-left:6px;vertical-align:middle}
.vdots i{width:7px;height:7px;border-radius:50%;background:var(--color-accent-300);animation:dropIn .35s cubic-bezier(.3,1.4,.5,1) both}

.mesa-body{flex:1;min-height:0;display:flex;border-top:1px solid var(--color-neutral-900)}
.felt{flex:1;min-width:0;position:relative;display:flex;padding:var(--space-4) clamp(12px,3vw,48px)}
.felt .oval{position:absolute;inset:10% 8%;border:1px solid var(--color-neutral-900);border-radius:50%;pointer-events:none}
.grid{position:relative;flex:1;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr) minmax(0,1fr);
  grid-template-rows:auto 1fr auto;grid-template-areas:'. top .' 'left center right' 'you you you';
  gap:var(--space-4);align-items:center;justify-items:center;min-height:560px}

.seat{display:flex;flex-direction:column;align-items:center;gap:10px;min-width:0}
.seat[data-area=left]{grid-area:left}.seat[data-area=top]{grid-area:top}.seat[data-area=right]{grid-area:right}
.who{display:flex;align-items:center;gap:10px}
.avatar{position:relative;width:30px;height:30px;flex:0 0 auto;border-radius:50%;border:1px solid var(--color-neutral-800);
  display:flex;align-items:center;justify-content:center;font-family:var(--font-heading);font-size:12px;transition:box-shadow .3s;background:#000}
.avatar img{position:absolute;left:6px;top:6px;width:18px;height:18px;object-fit:contain}
.who .nm{display:flex;flex-direction:column;align-items:flex-start;gap:2px;min-width:0}
.who .name{font-family:var(--font-heading);font-size:14px;opacity:.85;transition:opacity .3s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
.seat.thinking .name{opacity:1}
.who .role{font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:var(--color-neutral-500);white-space:nowrap}
.hand{position:relative;display:flex;padding-left:24px;min-height:98px}
.hand .slot{margin-left:-24px}
.say{min-height:24px;display:flex;justify-content:center;text-align:center;max-width:240px}
.say .thinkingtxt{font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--color-neutral-500);animation:breathe 1.2s ease-in-out infinite}
.say .line{font-size:15px;line-height:1.35;color:var(--color-neutral-100);font-style:italic;animation:speak 3.6s ease forwards;text-wrap:balance}
.say .gest{font-size:12px;color:var(--color-accent-300);animation:speak 4.2s ease forwards}

/* cards */
.pc{position:relative;border-radius:7px;overflow:hidden;background:#fbfbf7;box-shadow:0 3px 10px rgba(9,10,18,.55);flex:0 0 auto}
.pc img{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;display:block;user-select:none;-webkit-user-drag:none}
.pc::after{content:"";position:absolute;inset:0;border:1px solid #d9cfb8;border-radius:7px;pointer-events:none}
.pc.back{background:linear-gradient(150deg,#2b2741,#423a6a 60%,#2b2741);display:flex;align-items:center;justify-content:center}
.pc.back::before{content:"";position:absolute;inset:0;opacity:.5;background:repeating-linear-gradient(45deg,rgba(181,171,252,.16) 0 2px,transparent 2px 7px)}
.pc.back::after{inset:3px;border:1px solid rgba(210,206,253,.35);border-radius:5px}
.pc.back .dia{width:44%;aspect-ratio:1;border:1px solid rgba(210,206,253,.55);transform:rotate(45deg)}
.deal{animation:rise .7s var(--ease) both}
.flipin{animation:flip .45s var(--ease) both}

/* seat-level fx */
.fxlayer{position:absolute;left:50%;top:50%;z-index:3;transform:translate(-50%,-50%);pointer-events:none}
.me .fxlayer{left:100%;transform:translate(20px,-50%)}
.sfx{position:relative;display:flex;flex-direction:column;align-items:center;gap:6px;padding:10px 16px;border-radius:var(--radius-md);
  background:rgba(0,0,0,.85);border:1px solid var(--color-neutral-800);white-space:nowrap;animation:seatFx var(--dur) var(--ease) forwards}
.sfx.ord{border-color:var(--color-accent-500)}
.sfx.cut{background:transparent;border-color:transparent}
.sfx .rg{position:absolute;left:50%;top:50%;width:90px;height:90px;margin:-45px 0 0 -45px;border-radius:50%;border:1px solid var(--color-accent-300);animation:ring 1.4s var(--ease) forwards}
.sfx .rg.b{border-color:var(--color-accent-600);animation-delay:.25s;animation-fill-mode:both}
.sfx .ot{position:relative;font-family:var(--font-heading);font-weight:300;font-size:32px;line-height:1;color:var(--color-accent-100);
  text-shadow:0 0 24px color-mix(in srgb,var(--color-accent) 80%,transparent);animation:ordago var(--dur) var(--ease) forwards}
.split{position:relative}
.split .t{font-family:var(--font-heading);font-weight:300;font-size:26px;line-height:1;letter-spacing:-.02em;white-space:nowrap}
.split .ghostt{visibility:hidden}
.split .u,.split .d{position:absolute;inset:0;color:var(--color-text);text-shadow:0 0 12px #000,0 0 4px #000,0 1px 2px #000}
.split .u{clip-path:inset(0 0 52% 0);animation:splitUp var(--dur) var(--ease) forwards}
.split .d{clip-path:inset(48% 0 0 0);animation:splitDown var(--dur) var(--ease) forwards}
.split .sl{position:absolute;left:-14%;right:-14%;top:50%;transform:rotate(-8deg)}
.split .sl div{height:1px;background:linear-gradient(to right,transparent,var(--color-accent-200) 15%,var(--color-text) 50%,var(--color-accent-200) 85%,transparent);
  box-shadow:0 0 10px var(--color-accent);transform-origin:left;animation:slash var(--dur) cubic-bezier(.7,0,.2,1) .15s both}
.sfx .et{font-family:var(--font-heading);font-weight:300;font-size:26px;line-height:1;letter-spacing:-.03em}
.sfx .dots{display:flex;flex-wrap:wrap;justify-content:center;gap:4px;max-width:120px}
.sfx .dots i{width:7px;height:7px;border-radius:50%;background:var(--color-accent-300);animation:dropIn .35s cubic-bezier(.3,1.4,.5,1) both}

/* table-wide fx */
.tfx{position:absolute;inset:0;z-index:5;pointer-events:none;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:var(--space-3);overflow:hidden;animation:fxDim var(--dur) ease forwards;background:radial-gradient(closest-side,rgba(0,0,0,.82),rgba(0,0,0,.55) 70%,transparent)}
.tfx .rg{position:absolute;left:50%;top:50%;width:220px;height:220px;margin:-110px 0 0 -110px;border-radius:50%;border:1px solid var(--color-accent-300);animation:ring 1.8s var(--ease) forwards}
.tfx .rg.b{border-color:var(--color-accent-500);animation-delay:.28s;animation-fill-mode:both}
.tfx .rg.c{border-color:var(--color-accent-700);animation-delay:.56s;animation-fill-mode:both}
.tfx .big{position:relative;font-family:var(--font-heading);font-weight:300;font-size:clamp(56px,7vw,110px);line-height:.9;color:var(--color-accent-100);
  text-shadow:0 0 60px color-mix(in srgb,var(--color-accent) 70%,transparent);animation:ordago var(--dur) var(--ease) forwards;white-space:nowrap}
.tfx .sub{position:relative;font-size:12px;letter-spacing:.32em;text-transform:uppercase;color:var(--color-neutral-300);animation:fxSub var(--dur) ease forwards;text-align:center;padding:0 16px}

/* center */
.center{grid-area:center;display:flex;flex-direction:column;align-items:center;gap:12px;text-align:center;min-height:150px;justify-content:center}
.center .ph{font-size:10px;letter-spacing:.28em;text-transform:uppercase;color:var(--color-neutral-500)}
.center .ln{font-family:var(--font-heading);font-weight:300;font-size:48px;line-height:1;letter-spacing:-.04em}
.center .bet{font-size:14px;color:var(--color-accent-300);min-height:20px}
.center .turn{font-size:12px;color:var(--color-neutral-500);min-height:18px}
.center .note{font-size:13px;color:var(--color-neutral-500);max-width:280px;line-height:1.55}
.cta{background:none;border:1px solid var(--color-neutral-600);border-radius:999px;color:var(--color-text);font-family:var(--font-heading);
  font-size:12px;letter-spacing:.28em;text-transform:uppercase;padding:18px 36px;cursor:pointer;transition:all .25s}
.cta:hover,.cta:focus-visible{border-color:var(--color-accent);color:var(--color-accent-200);box-shadow:0 0 32px color-mix(in srgb,var(--color-accent) 25%,transparent)}
.cta:disabled{opacity:.5;cursor:wait}
.nick{display:flex;flex-direction:column;align-items:center;gap:10px;padding-bottom:var(--space-4)}
.nick span{font-size:10px;letter-spacing:.28em;text-transform:uppercase;color:var(--color-neutral-500)}
.nick input{width:260px;max-width:70vw;background:none;border:none;border-bottom:1px solid var(--color-neutral-700);color:var(--color-text);
  font-family:var(--font-heading);font-weight:300;font-size:28px;letter-spacing:-.02em;text-align:center;padding:6px 0;outline:none}
.nick input:focus{border-bottom-color:var(--color-accent-300)}
.recap{display:flex;flex-direction:column;gap:6px;align-items:center;animation:popIn .9s var(--ease) both}
.recap .gain{font-family:var(--font-heading);font-weight:300;font-size:34px;letter-spacing:-.03em}
.recap .jg{display:flex;gap:14px;flex-wrap:wrap;justify-content:center;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--color-neutral-500)}
.recap .jg b{font-weight:500;color:var(--color-text)}
.recap .jg b.us{color:var(--color-accent-200)}
.chips{display:flex;gap:6px;flex-wrap:wrap;justify-content:center}
.chip{font-size:11px;padding:3px 9px;border:1px solid var(--color-accent-700);border-radius:999px;color:var(--color-accent-200);animation:popIn .8s var(--ease) both}

/* you */
.you{grid-area:you;display:flex;flex-direction:column;align-items:center;gap:12px;width:100%}
.myhand{position:relative;display:flex;gap:12px;min-height:147px}
.mycard{border-radius:8px;transition:transform .2s ease,box-shadow .2s ease}
.mycard.pick{cursor:pointer}
.mycard.pick:hover{transform:translateY(-6px)}
.mycard.sel{transform:translateY(-18px);box-shadow:0 0 0 1.5px var(--color-accent-300)}
.myinfo{font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--color-neutral-500);text-align:center}
.btns{min-height:46px;display:flex;flex-wrap:wrap;gap:10px;justify-content:center;align-items:center}
.pill{background:none;border:1px solid var(--color-neutral-700);border-radius:999px;color:var(--color-text);font-family:var(--font-heading);
  font-size:12px;letter-spacing:.2em;text-transform:uppercase;padding:0 22px;height:44px;cursor:pointer;white-space:nowrap;transition:color .2s,border-color .2s,box-shadow .2s;
  animation:rise .35s ease both}
.pill:hover{color:var(--color-accent-200)}
.pill.soft{color:var(--color-neutral-400)}
.pill.hot{border-color:var(--color-accent-400);color:var(--color-accent-200)}
.pill.hot.arm{box-shadow:0 0 28px color-mix(in srgb,var(--color-accent) 45%,transparent);border-color:var(--color-accent-200)}
.pill:disabled{color:var(--color-neutral-600);cursor:default}
.linkbtn{background:none;border:none;color:var(--color-neutral-600);font-size:11px;letter-spacing:.16em;text-transform:uppercase;cursor:pointer;padding:6px}
.linkbtn:hover{color:var(--color-neutral-300)}
.err{font-size:13px;color:var(--color-danger);min-height:0;text-align:center}

/* log aside */
aside.log{width:330px;flex:0 0 330px;border-left:1px solid var(--color-neutral-900);display:flex;flex-direction:column;min-height:0;max-height:calc(100dvh - 120px);position:sticky;top:64px}
.tabs{display:flex;gap:var(--space-6);padding:var(--space-4) var(--space-6) 0;border-bottom:1px solid var(--color-neutral-900)}
.tabs button{background:none;border:none;border-bottom:1px solid transparent;padding:6px 0 10px;cursor:pointer;font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--color-neutral-500)}
.tabs button.on{color:var(--color-text);border-bottom-color:var(--color-neutral-500)}
.pane{display:none;flex:1;min-height:0;overflow:auto;padding:var(--space-4) var(--space-6)}
.pane.on{display:block}
.feed{display:flex;flex-direction:column;gap:7px;font-size:13px;line-height:1.45}
.feed .r{display:flex;gap:8px;animation:rise .4s ease both}
.feed .r .w{font-family:var(--font-heading);white-space:nowrap}
.feed .r .tx{color:var(--color-neutral-100);min-width:0;overflow-wrap:anywhere}
.feed .r.sys .tx{color:var(--color-neutral-500);font-style:italic}
.feed .r.newhand{margin-top:8px;padding-top:8px;border-top:1px solid var(--color-neutral-900)}
.feed .r.hot .tx{color:var(--color-accent-200);font-style:normal}
.feed .r.bad .tx{color:var(--color-danger)}
.say-in{display:flex;gap:8px;padding:var(--space-4) var(--space-6);border-top:1px solid var(--color-neutral-900)}
.say-in input{flex:1;min-width:0;background:none;border:none;border-bottom:1px solid var(--color-neutral-800);color:var(--color-text);font-size:13px;padding:6px 0;outline:none}
.say-in input:focus{border-bottom-color:var(--color-accent-300)}
.senas{display:grid;grid-template-columns:1fr;gap:6px}
.senas button{display:flex;flex-direction:column;align-items:flex-start;gap:2px;background:none;border:1px solid var(--color-neutral-900);border-radius:var(--radius-md);
  padding:8px 12px;cursor:pointer;text-align:left;transition:border-color .2s}
.senas button:hover{border-color:var(--color-accent-600)}
.senas .g{font-family:var(--font-heading);font-size:13px}
.senas .m{font-size:12px;color:var(--color-neutral-500)}
.lead{font-size:12px;color:var(--color-neutral-500);line-height:1.6;margin:0 0 var(--space-4)}

/* ── reglamento ── */
.hero{min-height:92vh;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));align-items:end;gap:var(--space-8);
  padding:120px var(--gutter) clamp(40px,6vh,72px)}
.hero h1{font-weight:400;font-size:clamp(96px,17vw,260px);line-height:.8;letter-spacing:-.06em;margin:0 0 0 -.04em}
.hero p{max-width:34ch;color:var(--color-neutral-300);font-size:17px;line-height:1.6;margin:0;text-wrap:pretty}
.sit{display:flex;align-items:center;gap:14px;font-size:12px;letter-spacing:.24em;text-transform:uppercase;color:var(--color-text);padding-bottom:8px;
  border-bottom:1px solid var(--color-neutral-600);white-space:nowrap;transition:all .25s}
.sit:hover{border-color:var(--color-accent);color:var(--color-accent-200)}
.fan{position:relative;height:clamp(300px,52vh,480px)}
.fan > div{position:absolute;transform-origin:50% 120%}
.guide{padding:0 var(--gutter)}
.sechead{display:flex;align-items:baseline;gap:var(--space-6);padding:var(--space-8) 0}
.sechead .rule{height:1px;flex:1;background:linear-gradient(to right,var(--color-neutral-800),transparent)}
.art{min-height:78vh;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:clamp(32px,6vw,120px);align-items:center;padding:var(--space-8) 0}
.art .txt{display:flex;flex-direction:column;gap:var(--space-4)}
.art .num{font-family:var(--font-heading);font-size:13px;letter-spacing:.2em;color:var(--color-neutral-500)}
.art h2{font-weight:400;font-size:clamp(40px,5.5vw,84px);line-height:.95;letter-spacing:-.035em}
.art p{max-width:40ch;color:var(--color-neutral-300);font-size:17px;line-height:1.7;margin:0;text-wrap:pretty}
.sep{height:1px;background:linear-gradient(to right,transparent,var(--color-neutral-900) 10%,var(--color-neutral-900) 90%,transparent)}
figure{margin:0}
.cap{font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--color-neutral-400)}
.mv{transition:all .7s var(--ease)}
.deckfig{position:relative;height:380px}
.deckfig > div{position:absolute;transform-origin:50% 140%}
.row4{display:flex;gap:14px;align-items:center}
.gcrow{display:flex;align-items:center;gap:var(--space-6);transition:opacity .6s}
.gcrow .lbl{width:160px;flex:0 0 auto;display:flex;align-items:center;gap:10px;font-size:13px;font-family:var(--font-heading)}
.gcrow .lbl img{width:18px;height:18px;object-fit:contain}
.gcrow .track{position:relative;height:118px;flex:1;min-width:0}
.gcrow .track > div{position:absolute;top:12px;border-radius:7px}
.jsum{font-family:var(--font-heading);font-weight:300;font-size:120px;line-height:.85;letter-spacing:-.06em;min-width:2ch;transition:color .4s}
.ladder{display:flex;gap:var(--space-4);flex-wrap:wrap}
.ladder div{font-family:var(--font-heading);font-size:14px;padding-bottom:4px;border-bottom:1px solid transparent;color:var(--color-neutral-600);transition:all .4s}
.ladder div.on{border-bottom-color:var(--color-accent-300);color:var(--color-accent-200)}
.envfig{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:var(--space-8);align-items:end}
.envlines{display:flex;flex-direction:column;justify-content:flex-end;gap:10px;height:220px;overflow:hidden}
.envlines div{font-size:15px;line-height:1.4;animation:rise .4s ease both;display:flex;gap:12px;align-items:center}
.envlines img{width:16px;height:16px;object-fit:contain}
.envlines .w{font-family:var(--font-heading);white-space:nowrap}
.envlines .t{color:var(--color-neutral-200)}
.stake{display:flex;flex-direction:column;align-items:flex-end;gap:var(--space-3)}
.stake .n{font-family:var(--font-heading);font-weight:300;font-size:96px;line-height:.85;letter-spacing:-.05em}
.stakedots{display:grid;grid-template-columns:repeat(8,9px);gap:6px;margin-top:var(--space-3)}
.stakedots i{width:9px;height:9px;border-radius:50%;background:var(--color-neutral-900);transition:background .35s}
.stakedots i.on{background:var(--color-accent-300)}
.seninfo{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:10px 28px;margin-top:var(--space-6)}
.seninfo div{font-size:14px;color:var(--color-neutral-300);display:flex;flex-direction:column;gap:2px;padding:10px 0;border-bottom:1px solid var(--color-neutral-900)}
.seninfo b{font-family:var(--font-heading);font-weight:500;color:var(--color-text)}

/* ── clasificación ── */
.board{min-height:100vh;padding:120px var(--gutter) var(--space-8);display:flex;flex-direction:column;gap:var(--space-8)}
.board h2{font-weight:400;font-size:clamp(40px,5.5vw,84px);line-height:.95;letter-spacing:-.035em}
.board .intro{max-width:52ch;color:var(--color-neutral-300);font-size:17px;line-height:1.7;margin:0;text-wrap:pretty}
.boards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:clamp(40px,6vw,120px);align-items:start}
.tbl{display:flex;flex-direction:column}
.tbl .hd,.tbl .rw{display:grid;grid-template-columns:32px minmax(0,1fr) 48px 48px 56px;gap:var(--space-3)}
.tbl .hd{padding-bottom:var(--space-3);border-bottom:1px solid var(--color-neutral-800);font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--color-neutral-500)}
.tbl .hd span:nth-child(n+3),.tbl .rw span:nth-child(n+3){text-align:right}
.tbl .rw{align-items:center;padding:14px 0;border-bottom:1px solid var(--color-neutral-900);font-variant-numeric:tabular-nums;animation:rise .5s var(--ease) both}
.tbl .rk{font-family:var(--font-heading);font-size:13px;color:var(--color-neutral-600)}
.tbl .nmc{display:flex;flex-direction:column;gap:6px;min-width:0}
.tbl .nmc .top{display:flex;align-items:center;gap:10px;min-width:0}
.tbl .nmc img{width:18px;height:18px;object-fit:contain;flex:0 0 auto}
.tbl .nmc .n{font-family:var(--font-heading);font-size:17px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tbl .bar{height:1px;background:var(--color-neutral-900);position:relative}
.tbl .bar i{position:absolute;left:0;top:0;bottom:0;transition:width 1s var(--ease)}
.tbl .num{font-size:15px}
.tbl .empty{padding:18px 0;color:var(--color-neutral-500);font-size:14px}
.boardnote{font-size:12px;color:var(--color-neutral-600);line-height:1.7}

footer.foot{padding:var(--space-8) var(--gutter);font-size:12px;line-height:1.7;color:var(--color-neutral-600);border-top:1px solid var(--color-neutral-900)}
footer.foot a{color:var(--color-neutral-400)}
#mesa footer.foot{display:none}

/* ── phones ── */
@media (max-width:980px){
  .mesa-body{flex-direction:column}
  aside.log{width:auto;flex:none;border-left:none;border-top:1px solid var(--color-neutral-900);max-height:none;position:static}
  .pane{max-height:46vh}
}
@media (max-width:720px){
  header.top{gap:var(--space-4);padding:14px 16px;flex-wrap:wrap;background:#000;border-bottom:1px solid var(--color-neutral-900)}
  nav.views{gap:var(--space-4);font-size:10px;letter-spacing:.16em;order:3;width:100%;margin-left:0}
  .status{margin-left:auto}
  #mesa{padding-top:88px}
  .mesa-head{padding:var(--space-3) 16px}
  .score{margin-left:0}
  .score .v{font-size:22px}
  .felt{padding:var(--space-3) 8px}
  .felt .oval{inset:6% 2%}
  .grid{grid-template-columns:1fr 1fr;grid-template-rows:auto auto auto auto;
    grid-template-areas:'top top' 'left right' 'center center' 'you you';min-height:0;gap:var(--space-6) var(--space-3)}
  .hand{padding-left:16px;min-height:61px}
  .hand .slot{margin-left:-16px}
  .who .name{max-width:120px;font-size:13px}
  .who .role{letter-spacing:.12em;font-size:9px}
  .center{min-height:110px}
  .center .ln{font-size:38px}
  .myhand{gap:8px;min-height:116px}
  .me .fxlayer{left:50%;top:-10px;transform:translate(-50%,-100%)}
  .pill{padding:0 16px;letter-spacing:.14em}
  .hero{padding-top:110px}
  .deckfig{height:300px}
  .gcrow .lbl{width:96px;font-size:12px}
  .jsum{font-size:84px}
  .stake .n{font-size:64px}
  .envfig{grid-template-columns:1fr}
  .stake{align-items:flex-start}
  .board{padding-top:110px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms !important;animation-iteration-count:1 !important;transition-duration:.01ms !important}
}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"></svg>

<header class="top">
  <a class="brand" href="#mesa" aria-label="Mus — volver a la mesa">MUS</a>
  <div class="status" id="status" role="status"><i></i><span id="statustxt">conectando…</span></div>
  <nav class="views" aria-label="Secciones">
    <a href="#mesa" data-v="mesa">Mesa</a>
    <a href="#reglamento" data-v="reglamento">Reglamento</a>
    <a href="#clasificacion" data-v="clasificacion">Clasificación</a>
    <a href="https://diegoatencia.dev/blog/mus-against-the-machine.html">Blog ↗</a>
  </nav>
  <button class="ghost" id="newvaca" hidden title="Empieza una vaca nueva">Nueva vaca</button>
</header>

<!-- ═════════════ LA MESA ═════════════ -->
<section id="mesa" class="view on" aria-label="La mesa">
  <div class="mesa-head">
    <div class="eyebrow">La mesa</div>
    <div class="lineup" id="lineup"></div>
    <div class="score" aria-live="polite">
      <span class="k">Nosotros</span><span class="vdots" id="vus"></span>
      <span class="v" id="sus">0</span>
      <span class="dash">—</span>
      <span class="v" id="sthem">0</span>
      <span class="vdots" id="vthem"></span><span class="k">Ellos</span>
      <span class="meta">a 40</span>
    </div>
  </div>
  <div class="mesa-body">
    <div class="felt" id="felt">
      <div class="oval"></div>
      <div id="tfxlayer"></div>
      <div class="grid">
        <div class="seat" data-area="left" id="seat-left"></div>
        <div class="seat" data-area="top" id="seat-top"></div>
        <div class="seat" data-area="right" id="seat-right"></div>
        <div class="center" id="center"></div>
        <div class="you me" id="you">
          <div class="myhand" id="myhand"><div class="fxlayer" id="myfx"></div></div>
          <div class="say" id="mysay"></div>
          <div class="myinfo" id="myinfo"></div>
          <div class="err" id="err" role="alert"></div>
          <div class="btns" id="btns"></div>
        </div>
      </div>
    </div>
    <aside class="log" aria-label="Cante y señas">
      <div class="tabs" role="tablist">
        <button class="on" data-p="feed" role="tab" aria-selected="true">Cante</button>
        <button data-p="senas" role="tab" aria-selected="false">Señas</button>
      </div>
      <div class="pane on" id="pane-feed" role="tabpanel"><div class="feed" id="feed"></div></div>
      <div class="pane" id="pane-senas" role="tabpanel">
        <p class="lead">Gestos reglamentarios, de significado fijo. Tu compañero los lee en su
          próxima decisión; los rivales pueden pillarlos.</p>
        <div class="senas" id="senagrid"></div>
        <div id="mysenas" style="margin-top:14px"></div>
      </div>
      <div class="say-in">
        <input id="chatin" maxlength="120" placeholder="habla en la mesa (sin cantar cartas)…" aria-label="Mensaje para la mesa">
        <button class="ghost" id="chatgo">Decir</button>
      </div>
    </aside>
  </div>
</section>

<!-- ═════════════ REGLAMENTO ═════════════ -->
<section id="reglamento" class="view" aria-label="Reglamento">
  <div class="hero">
    <div style="display:flex;flex-direction:column;gap:var(--space-6)">
      <div class="eyebrow">Juego de envite · Baraja española</div>
      <h1>Mus</h1>
      <div style="display:flex;gap:var(--space-8);align-items:flex-end;flex-wrap:wrap">
        <p>Cuatro jugadores, cuarenta cartas y ningún naipe que valga lo que parece. Aprende el reglamento y siéntate con tres modelos de lenguaje.</p>
        <a class="sit" href="#mesa">Sentarse a la mesa <span style="letter-spacing:0">→</span></a>
      </div>
    </div>
    <div class="fan" id="fan" aria-hidden="true"></div>
  </div>

  <div class="guide">
    <div class="sechead"><div class="eyebrow">Reglamento</div><div class="rule"></div></div>

    <article class="art">
      <div class="txt"><div class="num">I</div><h2>La baraja</h2>
        <p>Cuatro palos — oros, copas, espadas y bastos — de diez cartas cada uno: del as al siete, sota, caballo y rey. Sin ochos ni nueves. Las rayas del borde, las pintas, delatan el palo aunque sólo asome la esquina.</p></div>
      <figure style="display:flex;flex-direction:column;gap:var(--space-4)">
        <div class="deckfig" id="d-deck"></div>
        <figcaption class="cap" style="display:flex;gap:var(--space-4)"><span id="d-suit" style="color:var(--color-text)"></span><span id="d-pinta" class="muted"></span></figcaption>
      </figure>
    </article>
    <div class="sep"></div>

    <article class="art">
      <div class="txt"><div class="num">II</div><h2>Mus y descarte</h2>
        <p>Cuatro cartas a cada uno. Por turno, desde la mano, se dice «mus» o «no hay mus». Si los cuatro piden mus, cada uno tira las que no quiere y recibe otras. Un solo «no hay mus» corta, y empiezan las apuestas.</p></div>
      <figure style="display:flex;flex-direction:column;gap:var(--space-6)">
        <div class="row4" id="d-mus" style="height:260px"></div>
        <figcaption id="d-muscap" style="font-size:15px;color:var(--color-neutral-300);min-height:22px"></figcaption>
      </figure>
    </article>
    <div class="sep"></div>

    <article class="art">
      <div class="txt"><div class="num">III</div><h2>Grande y chica</h2>
        <p>Los dos primeros lances. A grande gana la mano más alta, carta a carta: el rey manda y el tres vale como rey. A chica, al revés: gana la más baja, y manda el as. La misma mano puede ganar uno y perder el otro.</p></div>
      <figure style="display:flex;flex-direction:column;gap:var(--space-6)">
        <figcaption class="cap" id="d-gctitle"></figcaption>
        <div id="d-gc"></div>
      </figure>
    </article>
    <div class="sep"></div>

    <article class="art">
      <div class="txt"><div class="num">IV</div><h2>Pares</h2>
        <p>Antes del lance cada uno declara si lleva pares, y sólo juega quien tiene. Duples — dos parejas o cuatro iguales — ganan a medias, tres iguales, que ganan a un par. Al final cobran aparte: tres piedras, dos y una.</p></div>
      <figure style="display:flex;flex-direction:column;gap:var(--space-6)">
        <div class="row4" id="d-pares" style="height:240px"></div>
        <figcaption style="display:flex;gap:var(--space-4);align-items:baseline">
          <span id="d-plab" style="font-family:var(--font-heading);font-size:28px;letter-spacing:-.02em"></span>
          <span id="d-ppts" class="muted" style="font-size:13px"></span></figcaption>
      </figure>
    </article>
    <div class="sep"></div>

    <article class="art">
      <div class="txt"><div class="num">V</div><h2>Juego</h2>
        <p>Las figuras y el tres valen diez; el as y el dos, uno. Con treinta y uno o más hay juego: la 31 es la mejor, luego la 32, después la 40 y de ahí hacia abajo hasta la 33. Si nadie llega, se juega al punto.</p></div>
      <figure style="display:flex;flex-direction:column;gap:var(--space-6)">
        <div style="display:flex;align-items:center;gap:clamp(24px,4vw,64px);flex-wrap:wrap">
          <div style="display:flex;gap:12px" id="d-juego"></div>
          <div class="jsum" id="d-jsum">0</div>
        </div>
        <div class="ladder" id="d-ladder"></div>
      </figure>
    </article>
    <div class="sep"></div>

    <article class="art">
      <div class="txt"><div class="num">VI</div><h2>Envites y órdago</h2>
        <p>En cada lance se pasa o se envida: dos piedras. El rival puede querer, subir — «y yo», dos más, o reenvidar, el doble — o no querer, y entonces cobras lo último que aceptó. El órdago lo apuesta todo: si lo quieren, ese lance decide la vaca.</p></div>
      <figure class="envfig">
        <div class="envlines" id="d-envlines"></div>
        <div class="stake">
          <div class="n" id="d-stake">0</div>
          <div class="eyebrow" id="d-stakelab"></div>
          <div class="stakedots" id="d-dots"></div>
        </div>
      </figure>
    </article>
    <div class="sep"></div>

    <article class="art" style="min-height:0">
      <div class="txt"><div class="num">VII</div><h2>Señas</h2>
        <p>Los compañeros se hablan con la cara: un gesto, un significado. Aquí las mandas desde la pestaña «Señas» de la mesa. Tu compañero las lee; los rivales, si están atentos, también.</p></div>
      <div class="seninfo" id="d-senas"></div>
    </article>
  </div>
  <footer class="foot" data-foot></footer>
</section>

<!-- ═════════════ CLASIFICACIÓN ═════════════ -->
<section id="clasificacion" class="view" aria-label="Clasificación">
  <div class="board">
    <div style="display:flex;flex-direction:column;gap:var(--space-4)">
      <div class="eyebrow">Clasificación</div>
      <h2>Vacas</h2>
      <p class="intro">Cada partida a 40 piedras es una vaca. A la izquierda, los modelos jugando entre ellos en el benchmark; a la derecha, tus vacas en esta mesa.</p>
    </div>
    <div class="boards">
      <div class="tbl" id="b-models"></div>
      <div class="tbl" id="b-you"></div>
    </div>
    <div class="boardnote" id="b-note"></div>
  </div>
  <footer class="foot" data-foot></footer>
</section>

<script>
'use strict';
/* ── endpoints (the static build rewrites these two lines) ── */
const API = '';              /*@API*/
const CARDS = '/cards/';     /*@CARDS*/
const BENCH_URL = '/mus/bench-v2-results.json';
const ICONS = /*@ICONS*/{"deepseek": "data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFlbSIgc3R5bGU9ImZsZXg6bm9uZTtsaW5lLWhlaWdodDoxIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHdpZHRoPSIxZW0iIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHRpdGxlPkRlZXBTZWVrPC90aXRsZT48cGF0aCBkPSJNMjMuNzQ4IDQuNDgyYy0uMjU0LS4xMjQtLjM2NC4xMTMtLjUxMi4yMzQtLjA1MS4wMzktLjA5NC4wOS0uMTM3LjEzNi0uMzcyLjM5Ny0uODA2LjY1Ny0xLjM3My42MjYtLjgyOS0uMDQ2LTEuNTM3LjIxNC0yLjE2My44NDgtLjEzMy0uNzgyLS41NzUtMS4yNDgtMS4yNDctMS41NDgtLjM1Mi0uMTU2LS43MDgtLjMxMS0uOTU1LS42NS0uMTcyLS4yNDEtLjIxOS0uNTEtLjMwNS0uNzc0LS4wNTUtLjE2LS4xMS0uMzIzLS4yOTMtLjM1LS4yLS4wMzEtLjI3OC4xMzYtLjM1Ni4yNzYtLjMxMy41NzItLjQzNCAxLjIwMi0uNDIyIDEuODQuMDI3IDEuNDM2LjYzMyAyLjU4IDEuODM4IDMuMzkzLjEzNy4wOTMuMTcyLjE4Ny4xMjkuMzIzLS4wODIuMjgtLjE4LjU1Mi0uMjY2LjgzMy0uMDU1LjE3OS0uMTM3LjIxNy0uMzI5LjE0YTUuNTI2IDUuNTI2IDAgMDEtMS43MzYtMS4xOGMtLjg1Ny0uODI4LTEuNjMxLTEuNzQyLTIuNTk3LTIuNDU4YTExLjM2NSAxMS4zNjUgMCAwMC0uNjg5LS40NzFjLS45ODUtLjk1Ny4xMy0xLjc0My4zODgtMS44MzYuMjctLjA5OC4wOTMtLjQzMi0uNzc5LS40MjgtLjg3Mi4wMDQtMS42Ny4yOTUtMi42ODcuNjg0YTMuMDU1IDMuMDU1IDAgMDEtLjQ2NS4xMzcgOS41OTcgOS41OTcgMCAwMC0yLjg4My0uMTAyYy0xLjg4NS4yMS0zLjM5IDEuMTAyLTQuNDk3IDIuNjIzQy4wODIgOC42MDYtLjIzMSAxMC42ODQuMTUyIDEyLjg1Yy40MDMgMi4yODQgMS41NjkgNC4xNzUgMy4zNiA1LjY1MyAxLjg1OCAxLjUzMyAzLjk5NyAyLjI4NCA2LjQzOCAyLjE0IDEuNDgyLS4wODUgMy4xMzMtLjI4NCA0Ljk5NC0xLjg2LjQ3LjIzNC45NjIuMzI3IDEuNzguMzk3LjYzLjA1OSAxLjIzNi0uMDMgMS43MDUtLjEyOC43MzUtLjE1Ni42ODQtLjgzNy40MTktLjk2MS0yLjE1NS0xLjAwNC0xLjY4Mi0uNTk1LTIuMTEzLS45MjYgMS4wOTYtMS4yOTYgMi43NDYtMi42NDIgMy4zOTItNy4wMDMuMDUtLjM0Ny4wMDctLjU2NSAwLS44NDUtLjAwNC0uMTcuMDM1LS4yMzcuMjMtLjI1NmE0LjE3MyA0LjE3MyAwIDAwMS41NDUtLjQ3NWMxLjM5Ni0uNzYzIDEuOTYtMi4wMTUgMi4wOTMtMy41MTcuMDItLjIzLS4wMDQtLjQ2Ny0uMjQ3LS41ODh6TTExLjU4MSAxOGMtMi4wODktMS42NDItMy4xMDItMi4xODMtMy41Mi0yLjE2LS4zOTIuMDI0LS4zMjEuNDcxLS4yMzUuNzYzLjA5LjI4OC4yMDcuNDg2LjM3MS43MzkuMTE0LjE2Ny4xOTIuNDE2LS4xMTMuNjAzLS42NzMuNDE2LTEuODQyLS4xNC0xLjg5Ny0uMTY3LTEuMzYxLS44MDItMi41LTEuODYtMy4zMDEtMy4zMDctLjc3NC0xLjM5My0xLjIyNC0yLjg4Ny0xLjI5OC00LjQ4Mi0uMDItLjM4Ni4wOTMtLjUyMi40NzctLjU5MmE0LjY5NiA0LjY5NiAwIDAxMS41MjktLjAzOWMyLjEzMi4zMTIgMy45NDYgMS4yNjUgNS40NjggMi43NzQuODY4Ljg2IDEuNTI1IDEuODg3IDIuMjAyIDIuODkxLjcyIDEuMDY2IDEuNDk0IDIuMDgyIDIuNDggMi45MTQuMzQ4LjI5Mi42MjUuNTE0Ljg5MS42NzctLjgwMi4wOS0yLjE0LjExLTMuMDU0LS42MTR6bTEtNi40NGEuMzA2LjMwNiAwIDAxLjQxNS0uMjg3LjMwMi4zMDIgMCAwMS4yLjI4OC4zMDYuMzA2IDAgMDEtLjMxLjMwNy4zMDMuMzAzIDAgMDEtLjMwNC0uMzA4em0zLjExIDEuNTk2Yy0uMi4wODEtLjM5OS4xNTEtLjU5LjE2YTEuMjQ1IDEuMjQ1IDAgMDEtLjc5OC0uMjU0Yy0uMjc0LS4yMy0uNDctLjM1OC0uNTUyLS43NThhMS43MyAxLjczIDAgMDEuMDE2LS41ODhjLjA3LS4zMjctLjAwOC0uNTM3LS4yMzktLjcyNy0uMTg3LS4xNTYtLjQyNi0uMTk5LS42ODgtLjE5OWEuNTU5LjU1OSAwIDAxLS4yNTQtLjA3OGMtLjExLS4wNTQtLjItLjE5LS4xMTQtLjM1OC4wMjgtLjA1NC4xNi0uMTg2LjE5Mi0uMjEuMzU2LS4yMDIuNzY3LS4xMzYgMS4xNDYuMDE2LjM1Mi4xNDQuNjE4LjQwOCAxLjAwMS43ODIuMzkxLjQ1MS40NjIuNTc2LjY4NS45MTQuMTc2LjI2NS4zMzYuNTM3LjQ0NS44NDguMDY3LjE5NS0uMDE5LjM1NC0uMjUuNDUyeiIgZmlsbD0iIzRENkJGRSI+PC9wYXRoPjwvc3ZnPg==", "gemma": "data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFlbSIgc3R5bGU9ImZsZXg6bm9uZTtsaW5lLWhlaWdodDoxIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHdpZHRoPSIxZW0iIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHRpdGxlPkdlbW1hPC90aXRsZT48ZGVmcz48bGluZWFyR3JhZGllbnQgaWQ9ImxvYmUtaWNvbnMtZ2VtbWEtX1JfMF8iIHgxPSIyNC40MTklIiB4Mj0iNzUuMTk0JSIgeTE9Ijc1LjU4MSUiIHkyPSIyNS4xOTQlIj48c3RvcCBvZmZzZXQ9IjAlIiBzdG9wLWNvbG9yPSIjNDQ2RUZGIj48L3N0b3A+PHN0b3Agb2Zmc2V0PSIzNi42NjElIiBzdG9wLWNvbG9yPSIjMkU5NkZGIj48L3N0b3A+PHN0b3Agb2Zmc2V0PSI4My4yMjElIiBzdG9wLWNvbG9yPSIjQjFDNUZGIj48L3N0b3A+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PHBhdGggZD0iTTEyLjM0IDUuOTUzYTguMjMzIDguMjMzIDAgMDEtLjI0Ny0xLjEyNVYzLjcyYTguMjUgOC4yNSAwIDAxNS41NjIgMi4yMzJIMTIuMzR6bS0uNjkgMGMuMTEzLS4zNzMuMTk5LS43NTUuMjU3LTEuMTQ1VjMuNzJhOC4yNSA4LjI1IDAgMDAtNS41NjIgMi4yMzJoNS4zMDR6bS01LjQzMy4xODdoNS4zNzNhNy45OCA3Ljk4IDAgMDEtLjI2Ny42OTYgOC40MSA4LjQxIDAgMDEtMS43NiAyLjY1TDYuMjE2IDYuMTR6bS0uMjY0LS4xODdIMi45Nzd2LjE4N2gyLjkxNWE4LjQzNiA4LjQzNiAwIDAwLTIuMzU3IDUuNzY3SDB2LjE4NmgzLjUzNWE4LjQzNiA4LjQzNiAwIDAwMi4zNTcgNS43NjdIMi45Nzd2LjE4NmgyLjk3NnYyLjk3N2guMTg3di0yLjkxNWE4LjQzNiA4LjQzNiAwIDAwNS43NjcgMi4zNTdWMjRoLjE4NnYtMy41MzVhOC40MzYgOC40MzYgMCAwMDUuNzY3LTIuMzU3djIuOTE1aC4xODZ2LTIuOTc3aDIuOTc3di0uMTg2aC0yLjkxNWE4LjQzNiA4LjQzNiAwIDAwMi4zNTctNS43NjdIMjR2LS4xODZoLTMuNTM1YTguNDM2IDguNDM2IDAgMDAtMi4zNTctNS43NjdoMi45MTV2LS4xODdoLTIuOTc3VjIuOTc3aC0uMTg2djIuOTE1YTguNDM2IDguNDM2IDAgMDAtNS43NjctMi4zNTdWMGgtLjE4NnYzLjUzNUE4LjQzNiA4LjQzNiAwIDAwNi4xNCA1Ljg5MlYyLjk3N2gtLjE4N3YyLjk3NnptNi4xNCAxNC4zMjZhOC4yNSA4LjI1IDAgMDA1LjU2Mi0yLjIzM0gxMi4zNGMtLjEwOC4zNjctLjE5Ljc0My0uMjQ3IDEuMTI2djEuMTA3em0tLjE4Ni0xLjA4N2E4LjAxNSA4LjAxNSAwIDAwLS4yNTgtMS4xNDZINi4zNDVhOC4yNSA4LjI1IDAgMDA1LjU2MiAyLjIzM3YtMS4wODd6bS04LjE4Ni03LjI4NWgxLjEwN2E4LjIzIDguMjMgMCAwMDEuMTI1LS4yNDdWNi4zNDVhOC4yNSA4LjI1IDAgMDAtMi4yMzIgNS41NjJ6bTEuMDg3LjE4NkgzLjcyYTguMjUgOC4yNSAwIDAwMi4yMzIgNS41NjJ2LTUuMzA0YTguMDEyIDguMDEyIDAgMDAtMS4xNDUtLjI1OHptMTUuNDctLjE4NmE4LjI1IDguMjUgMCAwMC0yLjIzMi01LjU2MnY1LjMxNWMuMzY3LjEwOC43NDMuMTkgMS4xMjYuMjQ3aDEuMTA3em0tMS4wODYuMTg2Yy0uMzkuMDU4LS43NzIuMTQ0LTEuMTQ2LjI1OHY1LjMwNGE4LjI1IDguMjUgMCAwMDIuMjMzLTUuNTYyaC0xLjA4N3ptLTEuMzMyIDUuNjlWMTIuNDFhNy45NyA3Ljk3IDAgMDAtLjY5Ni4yNjcgOC40MDkgOC40MDkgMCAwMC0yLjY1IDEuNzZsMy4zNDYgMy4zNDZ6bTAtNi4xOHYtNS40NWwtLjAxMi0uMDEzaC01LjQ1MWMuMDc2LjIzNS4xNjIuNDY4LjI2LjY5NmE4LjY5OCA4LjY5OCAwIDAwMS44MTkgMi42ODggOC42OTggOC42OTggMCAwMDIuNjg4IDEuODJjLjIyOC4wOTcuNDYuMTgzLjY5Ni4yNTl6TTYuMTQgMTcuODQ4VjEyLjQxYy4yMzUuMDc4LjQ2OC4xNjcuNjk2LjI2N2E4LjQwMyA4LjQwMyAwIDAxMi42ODggMS43OTkgOC40MDQgOC40MDQgMCAwMTEuNzk5IDIuNjg4Yy4xLjIyOC4xOS40Ni4yNjcuNjk2SDYuMTUybC0uMDEyLS4wMTJ6bTAtNi4yNDVWNi4zMjZsMy4yOSAzLjI5YTguNzE2IDguNzE2IDAgMDEtMi41OTQgMS43MjggOC4xNCA4LjE0IDAgMDEtLjY5Ni4yNTl6bTYuMjU3IDYuMjU3aDUuMjc3bC0zLjI5LTMuMjlhOC43MTYgOC43MTYgMCAwMC0xLjcyOCAyLjU5NCA4LjEzNSA4LjEzNSAwIDAwLS4yNTkuNjk2em0tMi4zNDctNy44MWE5LjQzNSA5LjQzNSAwIDAxLTIuODggMS45NiA5LjE0IDkuMTQgMCAwMTIuODggMS45NCA5LjE0IDkuMTQgMCAwMTEuOTQgMi44OCA5LjQzNSA5LjQzNSAwIDAxMS45Ni0yLjg4IDkuMTQgOS4xNCAwIDAxMi44OC0xLjk0IDkuNDM1IDkuNDM1IDAgMDEtMi44OC0xLjk2IDkuNDM0IDkuNDM0IDAgMDEtMS45Ni0yLjg4IDkuMTQgOS4xNCAwIDAxLTEuOTQgMi44OHoiIGZpbGw9InVybCgjbG9iZS1pY29ucy1nZW1tYS1fUl8wXykiIGZpbGwtcnVsZT0iZXZlbm9kZCI+PC9wYXRoPjwvc3ZnPg==", "qwen": "data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFlbSIgc3R5bGU9ImZsZXg6bm9uZTtsaW5lLWhlaWdodDoxIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHdpZHRoPSIxZW0iIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHRpdGxlPlF3ZW48L3RpdGxlPjxwYXRoIGQ9Ik0xOS43MTMgMi44MjVoLTUuOTA3YzAtLjI1MS0uMDY2LS41MDMtLjE5Ni0uNzI4TDEyLjgxOS43MjhBMS40NiAxLjQ2IDAgMCAwIDExLjU1OSAwaC0xLjU4Yy0uNTIgMC0xIC4yNzUtMS4yNi43MjhsLTIuNDIgNC4xOWExLjQ1IDEuNDUgMCAwIDAgMCAxLjQ1M2wuNzkxIDEuMzdjLjI2LjQ0OC43NC43MjcgMS4yNi43MjdoMTEuMzZjLjUyIDAgMS0uMjc1IDEuMjYtLjcyOGwuNzktMS4zN2ExLjQ1IDEuNDUgMCAwIDAgMC0xLjQ1MWwtLjc5LTEuMzdhMS40NiAxLjQ2IDAgMCAwLTEuMjYtLjcyOHpNLjE5NSA5LjkwNWwyLjk1MSA1LjExNWExLjQ2IDEuNDYgMCAwIDAtLjUzMS41MzFsLS43OTEgMS4zN2ExLjQ1IDEuNDUgMCAwIDAgMCAxLjQ1MmwuNzkgMS4zN2MuMjYuNDQ4Ljc0LjcyNyAxLjI2LjcyN2g0Ljg0Yy41MiAwIDEtLjI3NSAxLjI2LS43MjhsLjc5LTEuMzdhMS40NSAxLjQ1IDAgMCAwIDAtMS40NTFMNS4wODYgNy4wODNhMS40NiAxLjQ2IDAgMCAwLTEuMjYtLjcyOGgtMS41OGMtLjUyIDAtMSAuMjc2LTEuMjYuNzI4bC0uNzkgMS4zN2ExLjQ1IDEuNDUgMCAwIDAgMCAxLjQ1Mm0xNS44ODggMTMuMzY3IDIuOTUxLTUuMTE1Yy4yMTcuMTI1LjQ2OS4xOTYuNzI4LjE5NmgxLjU4MmMuNTIgMCAxLS4yNzUgMS4yNi0uNzI4bC43OS0xLjM3YTEuNDUgMS40NSAwIDAgMCAwLTEuNDUxbC0yLjQyLTQuMTkxYTEuNDYgMS40NiAwIDAgMC0xLjI1OS0uNzI4aC0xLjU4MmMtLjUyIDAtMSAuMjc2LTEuMjU5LjcyOGwtNS42NzggOS44MzhhMS40NSAxLjQ1IDAgMCAwIDAgMS40NTJsLjc5IDEuMzdjLjI2LjQ0OC43NC43MjcgMS4yNi43MjdoMS41ODJjLjUyIDAgMS0uMjc1IDEuMjYtLjcyOHoiIGZpbGw9IiMwODJkZmYiPjwvcGF0aD48L3N2Zz4=", "meta": "data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFlbSIgc3R5bGU9ImZsZXg6bm9uZTtsaW5lLWhlaWdodDoxIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHdpZHRoPSIxZW0iIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHRpdGxlPk1ldGE8L3RpdGxlPjxwYXRoIGQ9Ik02Ljg5NyA0aC0uMDI0bC0uMDMxIDIuNjE1aC4wMjJjMS43MTUgMCAzLjA0NiAxLjM1NyA1Ljk0IDYuMjQ2bC4xNzUuMjk3LjAxMi4wMiAxLjYyLTIuNDM4LS4wMTItLjAxOWE0OC43NjMgNDguNzYzIDAgMDAtMS4wOTgtMS43MTYgMjguMDEgMjguMDEgMCAwMC0xLjE3NS0xLjYyOUMxMC40MTMgNC45MzIgOC44MTIgNCA2Ljg5NiA0eiIgZmlsbD0idXJsKCNsb2JlLWljb25zLW1ldGEtMC1fUl8wXykiPjwvcGF0aD48cGF0aCBkPSJNNi44NzMgNEM0Ljk1IDQuMDEgMy4yNDcgNS4yNTggMi4wMiA3LjE3YTQuMzUyIDQuMzUyIDAgMDAtLjAxLjAxN2wyLjI1NCAxLjIzMS4wMTEtLjAxN2MuNzE4LTEuMDgzIDEuNjEtMS43NzQgMi41NjgtMS43ODVoLjAyMUw2Ljg5NiA0aC0uMDIzeiIgZmlsbD0idXJsKCNsb2JlLWljb25zLW1ldGEtMS1fUl8wXykiPjwvcGF0aD48cGF0aCBkPSJNMi4wMTkgNy4xN2wtLjAxMS4wMTdDMS4yIDguNDQ3LjU5OCA5Ljk5NS4yNzQgMTEuNjY0bC0uMDA1LjAyMiAyLjUzNC42LjAwNC0uMDIyYy4yNy0xLjQ2Ny43ODYtMi44MjggMS40NTYtMy44NDVsLjAxMS0uMDE3TDIuMDIgNy4xN3oiIGZpbGw9InVybCgjbG9iZS1pY29ucy1tZXRhLTItX1JfMF8pIj48L3BhdGg+PHBhdGggZD0iTTIuODA3IDEyLjI2NGwtMi41MzMtLjYtLjAwNS4wMjJjLS4xNzcuOTE4LS4yNjcgMS44NTEtLjI2OSAyLjc4NnYuMDIzbDIuNTk4LjIzM3YtLjAyM2ExMi41OTEgMTIuNTkxIDAgMDEuMjEtMi40NHoiIGZpbGw9InVybCgjbG9iZS1pY29ucy1tZXRhLTMtX1JfMF8pIj48L3BhdGg+PHBhdGggZD0iTTIuNjc3IDE1LjUzN2E1LjQ2MiA1LjQ2MiAwIDAxLS4wNzktLjgxM3YtLjAyMkwwIDE0LjQ2OHYuMDI0YTguODkgOC44OSAwIDAwLjE0NiAxLjY1MmwyLjUzNS0uNTg1YTQuMTA2IDQuMTA2IDAgMDEtLjAwNC0uMDIyeiIgZmlsbD0idXJsKCNsb2JlLWljb25zLW1ldGEtNC1fUl8wXykiPjwvcGF0aD48cGF0aCBkPSJNMy4yNyAxNi44OWMtLjI4NC0uMzEtLjQ4NC0uNzU2LS41ODktMS4zMjhsLS4wMDQtLjAyMS0yLjUzNS41ODUuMDA0LjAyMWMuMTkyIDEuMDEuNTY4IDEuODUgMS4xMDYgMi40ODdsLjAxNC4wMTcgMi4wMTgtMS43NDVhMi4xMDYgMi4xMDYgMCAwMS0uMDE1LS4wMTZ6IiBmaWxsPSJ1cmwoI2xvYmUtaWNvbnMtbWV0YS01LV9SXzBfKSI+PC9wYXRoPjxwYXRoIGQ9Ik0xMC43OCA5LjY1NGMtMS41MjggMi4zNS0yLjQ1NCAzLjgyNS0yLjQ1NCAzLjgyNS0yLjAzNSAzLjItMi43MzkgMy45MTctMy44NzEgMy45MTdhMS41NDUgMS41NDUgMCAwMS0xLjE4Ni0uNTA4bC0yLjAxNyAxLjc0NC4wMTQuMDE3QzIuMDEgMTkuNTE4IDMuMDU4IDIwIDQuMzU2IDIwYzEuOTYzIDAgMy4zNzQtLjkyOCA1Ljg4NC01LjMzbDEuNzY2LTMuMTNhNDEuMjgzIDQxLjI4MyAwIDAwLTEuMjI3LTEuODg2eiIgZmlsbD0iIzAwODJGQiI+PC9wYXRoPjxwYXRoIGQ9Ik0xMy41MDIgNS45NDZsLS4wMTYuMDE2Yy0uNC40My0uNzg2LjkwOC0xLjE2IDEuNDE2LjM3OC40ODMuNzY4IDEuMDI0IDEuMTc1IDEuNjMuNDgtLjc0My45MjgtMS4zNDUgMS4zNjctMS44MDdsLjAxNi0uMDE2LTEuMzgyLTEuMjR6IiBmaWxsPSJ1cmwoI2xvYmUtaWNvbnMtbWV0YS02LV9SXzBfKSI+PC9wYXRoPjxwYXRoIGQ9Ik0yMC45MTggNS43MTNDMTkuODUzIDQuNjMzIDE4LjU4MyA0IDE3LjIyNSA0Yy0xLjQzMiAwLTIuNjM3Ljc4Ny0zLjcyMyAxLjk0NGwtLjAxNi4wMTYgMS4zODIgMS4yNC4wMTYtLjAxN2MuNzE1LS43NDcgMS40MDgtMS4xMiAyLjE3Ni0xLjEyLjgyNiAwIDEuNi4zOSAyLjI3IDEuMDc1bC4wMTUuMDE2IDEuNTg5LTEuNDI1LS4wMTYtLjAxNnoiIGZpbGw9IiMwMDgyRkIiPjwvcGF0aD48cGF0aCBkPSJNMjMuOTk4IDE0LjEyNWMtLjA2LTMuNDY3LTEuMjctNi41NjYtMy4wNjQtOC4zOTZsLS4wMTYtLjAxNi0xLjU4OCAxLjQyNC4wMTUuMDE2YzEuMzUgMS4zOTIgMi4yNzcgMy45OCAyLjM2MSA2Ljk3MXYuMDIzaDIuMjkydi0uMDIyeiIgZmlsbD0idXJsKCNsb2JlLWljb25zLW1ldGEtNy1fUl8wXykiPjwvcGF0aD48cGF0aCBkPSJNMjMuOTk4IDE0LjE1di0uMDIzaC0yLjI5MnYuMDIyYy4wMDQuMTQuMDA2LjI4Mi4wMDYuNDI0IDAgLjgxNS0uMTIxIDEuNDc0LS4zNjggMS45NWwtLjAxMS4wMjIgMS43MDggMS43ODIuMDEzLS4wMmMuNjItLjk2Ljk0Ni0yLjI5My45NDYtMy45MSAwLS4wODMgMC0uMTY1LS4wMDItLjI0N3oiIGZpbGw9InVybCgjbG9iZS1pY29ucy1tZXRhLTgtX1JfMF8pIj48L3BhdGg+PHBhdGggZD0iTTIxLjM0NCAxNi41MmwtLjAxMS4wMmMtLjIxNC40MDItLjUxOS42Ny0uOTE3Ljc4N2wuNzc4IDIuNDYyYTMuNDkzIDMuNDkzIDAgMDAuNDM4LS4xODIgMy41NTggMy41NTggMCAwMDEuMzY2LTEuMjE4bC4wNDQtLjA2NS4wMTItLjAyLTEuNzEtMS43ODR6IiBmaWxsPSJ1cmwoI2xvYmUtaWNvbnMtbWV0YS05LV9SXzBfKSI+PC9wYXRoPjxwYXRoIGQ9Ik0xOS45MiAxNy4zOTNjLS4yNjIgMC0uNDkyLS4wMzktLjcxOC0uMTRsLS43OTggMi41MjJjLjQ0OS4xNTMuOTI3LjIyMiAxLjQ2LjIyMi40OTIgMCAuOTQzLS4wNzMgMS4zNTItLjIxNWwtLjc4LTIuNDYyYy0uMTY3LjA1LS4zNDEuMDc1LS41MTcuMDczeiIgZmlsbD0idXJsKCNsb2JlLWljb25zLW1ldGEtMTAtX1JfMF8pIj48L3BhdGg+PHBhdGggZD0iTTE4LjMyMyAxNi41MzRsLS4wMTQtLjAxNy0xLjgzNiAxLjkxNC4wMTYuMDE3Yy42MzcuNjgyIDEuMjQ2IDEuMTA1IDEuOTM3IDEuMzM3bC43OTctMi41MmMtLjI5MS0uMTI1LS41NzMtLjM1My0uOS0uNzMxeiIgZmlsbD0idXJsKCNsb2JlLWljb25zLW1ldGEtMTEtX1JfMF8pIj48L3BhdGg+PHBhdGggZD0iTTE4LjMwOSAxNi41MTVjLS41NS0uNjQyLTEuMjMyLTEuNzEyLTIuMzAzLTMuNDRsLTEuMzk2LTIuMzM2LS4wMTEtLjAyLTEuNjIgMi40MzguMDEyLjAyLjk4OSAxLjY2OGMuOTU5IDEuNjEgMS43NCAyLjc3NCAyLjQ5MyAzLjU4NWwuMDE2LjAxNiAxLjgzNC0xLjkxNGEyLjM1MyAyLjM1MyAwIDAxLS4wMTQtLjAxN3oiIGZpbGw9InVybCgjbG9iZS1pY29ucy1tZXRhLTEyLV9SXzBfKSI+PC9wYXRoPjxkZWZzPjxsaW5lYXJHcmFkaWVudCBpZD0ibG9iZS1pY29ucy1tZXRhLTAtX1JfMF8iIHgxPSI3NS44OTclIiB4Mj0iMjYuMzEyJSIgeTE9Ijg5LjE5OSUiIHkyPSIxMi4xOTQlIj48c3RvcCBvZmZzZXQ9Ii4wNiUiIHN0b3AtY29sb3I9IiMwODY3REYiPjwvc3RvcD48c3RvcCBvZmZzZXQ9IjQ1LjM5JSIgc3RvcC1jb2xvcj0iIzA2NjhFMSI+PC9zdG9wPjxzdG9wIG9mZnNldD0iODUuOTElIiBzdG9wLWNvbG9yPSIjMDA2NEUwIj48L3N0b3A+PC9saW5lYXJHcmFkaWVudD48bGluZWFyR3JhZGllbnQgaWQ9ImxvYmUtaWNvbnMtbWV0YS0xLV9SXzBfIiB4MT0iMjEuNjclIiB4Mj0iOTcuMDY4JSIgeTE9Ijc1Ljg3NCUiIHkyPSIyMy45ODUlIj48c3RvcCBvZmZzZXQ9IjEzLjIzJSIgc3RvcC1jb2xvcj0iIzAwNjRERiI+PC9zdG9wPjxzdG9wIG9mZnNldD0iOTkuODglIiBzdG9wLWNvbG9yPSIjMDA2NEUwIj48L3N0b3A+PC9saW5lYXJHcmFkaWVudD48bGluZWFyR3JhZGllbnQgaWQ9ImxvYmUtaWNvbnMtbWV0YS0yLV9SXzBfIiB4MT0iMzguMjYzJSIgeDI9IjYwLjg5NSUiIHkxPSI4OS4xMjclIiB5Mj0iMTYuMTMxJSI+PHN0b3Agb2Zmc2V0PSIxLjQ3JSIgc3RvcC1jb2xvcj0iIzAwNzJFQyI+PC9zdG9wPjxzdG9wIG9mZnNldD0iNjguODElIiBzdG9wLWNvbG9yPSIjMDA2NERGIj48L3N0b3A+PC9saW5lYXJHcmFkaWVudD48bGluZWFyR3JhZGllbnQgaWQ9ImxvYmUtaWNvbnMtbWV0YS0zLV9SXzBfIiB4MT0iNDcuMDMyJSIgeDI9IjUyLjE1JSIgeTE9IjkwLjE5JSIgeTI9IjE1Ljc0NSUiPjxzdG9wIG9mZnNldD0iNy4zMSUiIHN0b3AtY29sb3I9IiMwMDdDRjYiPjwvc3RvcD48c3RvcCBvZmZzZXQ9Ijk5LjQzJSIgc3RvcC1jb2xvcj0iIzAwNzJFQyI+PC9zdG9wPjwvbGluZWFyR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJsb2JlLWljb25zLW1ldGEtNC1fUl8wXyIgeDE9IjUyLjE1NSUiIHgyPSI0Ny41OTElIiB5MT0iNTguMzAxJSIgeTI9IjM3LjAwNCUiPjxzdG9wIG9mZnNldD0iNy4zMSUiIHN0b3AtY29sb3I9IiMwMDdGRjkiPjwvc3RvcD48c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiMwMDdDRjYiPjwvc3RvcD48L2xpbmVhckdyYWRpZW50PjxsaW5lYXJHcmFkaWVudCBpZD0ibG9iZS1pY29ucy1tZXRhLTUtX1JfMF8iIHgxPSIzNy42ODklIiB4Mj0iNjEuOTYxJSIgeTE9IjEyLjUwMiUiIHkyPSI2My42MjQlIj48c3RvcCBvZmZzZXQ9IjcuMzElIiBzdG9wLWNvbG9yPSIjMDA3RkY5Ij48L3N0b3A+PHN0b3Agb2Zmc2V0PSIxMDAlIiBzdG9wLWNvbG9yPSIjMDA4MkZCIj48L3N0b3A+PC9saW5lYXJHcmFkaWVudD48bGluZWFyR3JhZGllbnQgaWQ9ImxvYmUtaWNvbnMtbWV0YS02LV9SXzBfIiB4MT0iMzQuODA4JSIgeDI9IjYyLjMxMyUiIHkxPSI2OC44NTklIiB5Mj0iMjMuMTc0JSI+PHN0b3Agb2Zmc2V0PSIyNy45OSUiIHN0b3AtY29sb3I9IiMwMDdGRjgiPjwvc3RvcD48c3RvcCBvZmZzZXQ9IjkxLjQxJSIgc3RvcC1jb2xvcj0iIzAwODJGQiI+PC9zdG9wPjwvbGluZWFyR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJsb2JlLWljb25zLW1ldGEtNy1fUl8wXyIgeDE9IjQzLjc2MiUiIHgyPSI1Ny42MDIlIiB5MT0iNi4yMzUlIiB5Mj0iOTguNTE0JSI+PHN0b3Agb2Zmc2V0PSIwJSIgc3RvcC1jb2xvcj0iIzAwODJGQiI+PC9zdG9wPjxzdG9wIG9mZnNldD0iOTkuOTUlIiBzdG9wLWNvbG9yPSIjMDA4MUZBIj48L3N0b3A+PC9saW5lYXJHcmFkaWVudD48bGluZWFyR3JhZGllbnQgaWQ9ImxvYmUtaWNvbnMtbWV0YS04LV9SXzBfIiB4MT0iNjAuMDU1JSIgeDI9IjM5Ljg4JSIgeTE9IjQuNjYxJSIgeTI9IjY5LjA3NyUiPjxzdG9wIG9mZnNldD0iNi4xOSUiIHN0b3AtY29sb3I9IiMwMDgxRkEiPjwvc3RvcD48c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiMwMDgwRjkiPjwvc3RvcD48L2xpbmVhckdyYWRpZW50PjxsaW5lYXJHcmFkaWVudCBpZD0ibG9iZS1pY29ucy1tZXRhLTktX1JfMF8iIHgxPSIzMC4yODIlIiB4Mj0iNjEuMDgxJSIgeTE9IjU5LjMyJSIgeTI9IjMzLjI0NCUiPjxzdG9wIG9mZnNldD0iMCUiIHN0b3AtY29sb3I9IiMwMjdBRjMiPjwvc3RvcD48c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiMwMDgwRjkiPjwvc3RvcD48L2xpbmVhckdyYWRpZW50PjxsaW5lYXJHcmFkaWVudCBpZD0ibG9iZS1pY29ucy1tZXRhLTEwLV9SXzBfIiB4MT0iMjAuNDMzJSIgeDI9IjgyLjExMiUiIHkxPSI1MC4wMDElIiB5Mj0iNTAuMDAxJSI+PHN0b3Agb2Zmc2V0PSIwJSIgc3RvcC1jb2xvcj0iIzAzNzdFRiI+PC9zdG9wPjxzdG9wIG9mZnNldD0iOTkuOTQlIiBzdG9wLWNvbG9yPSIjMDI3OUYxIj48L3N0b3A+PC9saW5lYXJHcmFkaWVudD48bGluZWFyR3JhZGllbnQgaWQ9ImxvYmUtaWNvbnMtbWV0YS0xMS1fUl8wXyIgeDE9IjQwLjMwMyUiIHgyPSI3Mi4zOTQlIiB5MT0iMzUuMjk4JSIgeTI9IjU3LjgxMSUiPjxzdG9wIG9mZnNldD0iLjE5JSIgc3RvcC1jb2xvcj0iIzA0NzFFOSI+PC9zdG9wPjxzdG9wIG9mZnNldD0iMTAwJSIgc3RvcC1jb2xvcj0iIzAzNzdFRiI+PC9zdG9wPjwvbGluZWFyR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJsb2JlLWljb25zLW1ldGEtMTItX1JfMF8iIHgxPSIzMi4yNTQlIiB4Mj0iNjguMDAzJSIgeTE9IjE5LjcxOSUiIHkyPSI4NC45MDglIj48c3RvcCBvZmZzZXQ9IjI3LjY1JSIgc3RvcC1jb2xvcj0iIzA4NjdERiI+PC9zdG9wPjxzdG9wIG9mZnNldD0iMTAwJSIgc3RvcC1jb2xvcj0iIzA0NzFFOSI+PC9zdG9wPjwvbGluZWFyR3JhZGllbnQ+PC9kZWZzPjwvc3ZnPg==", "mistral": "data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFlbSIgc3R5bGU9ImZsZXg6bm9uZTtsaW5lLWhlaWdodDoxIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHdpZHRoPSIxZW0iIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHRpdGxlPk1pc3RyYWw8L3RpdGxlPjxwYXRoIGQ9Ik0zLjQyOCAzLjRoMy40Mjl2My40MjhIMy40MjhWMy40em0xMy43MTQgMGgzLjQzdjMuNDI4aC0zLjQzVjMuNHoiIGZpbGw9ImdvbGQiPjwvcGF0aD48cGF0aCBkPSJNMy40MjggNi44MjhoNi44NTd2My40MjlIMy40MjlWNi44Mjh6bTEwLjI4NiAwaDYuODU3djMuNDI5aC02Ljg1N1Y2LjgyOHoiIGZpbGw9IiNGRkFGMDAiPjwvcGF0aD48cGF0aCBkPSJNMy40MjggMTAuMjU4aDE3LjE0NHYzLjQyOEgzLjQyOHYtMy40Mjh6IiBmaWxsPSIjRkY4MjA1Ij48L3BhdGg+PHBhdGggZD0iTTMuNDI4IDEzLjY4NmgzLjQyOXYzLjQyOEgzLjQyOHYtMy40Mjh6bTYuODU4IDBoMy40Mjl2My40MjhoLTMuNDI5di0zLjQyOHptNi44NTYgMGgzLjQzdjMuNDI4aC0zLjQzdi0zLjQyOHoiIGZpbGw9IiNGQTUwMEYiPjwvcGF0aD48cGF0aCBkPSJNMCAxNy4xMTRoMTAuMjg2djMuNDI5SDB2LTMuNDI5em0xMy43MTQgMEgyNHYzLjQyOUgxMy43MTR2LTMuNDI5eiIgZmlsbD0iI0UxMDUwMCI+PC9wYXRoPjwvc3ZnPg==", "openai": "data:image/svg+xml;base64,PHN2ZyBmaWxsPSJjdXJyZW50Q29sb3IiIGZpbGwtcnVsZT0iZXZlbm9kZCIgaGVpZ2h0PSIxZW0iIHN0eWxlPSJmbGV4Om5vbmU7bGluZS1oZWlnaHQ6MSIgdmlld0JveD0iMCAwIDI0IDI0IiB3aWR0aD0iMWVtIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjx0aXRsZT5PcGVuQUk8L3RpdGxlPjxwYXRoIGQ9Ik05LjIwNSA4LjY1OHYtMi4yNmMwLS4xOS4wNzItLjMzMy4yMzgtLjQyOGw0LjU0My0yLjYxNmMuNjE5LS4zNTcgMS4zNTYtLjUyMyAyLjExNy0uNTIzIDIuODU0IDAgNC42NjIgMi4yMTIgNC42NjIgNC41NjYgMCAuMTY3IDAgLjM1Ny0uMDI0LjU0N2wtNC43MS0yLjc1OWEuNzk3Ljc5NyAwIDAwLS44NTYgMGwtNS45NyAzLjQ3M3ptMTAuNjA5IDguOFYxMi4wNmMwLS4zMzMtLjE0My0uNTctLjQyOS0uNzM3bC01Ljk3LTMuNDczIDEuOTUtMS4xMThhLjQzMy40MzMgMCAwMS40NzYgMGw0LjU0MyAyLjYxN2MxLjMwOS43NiAyLjE4OSAyLjM3OCAyLjE4OSAzLjk0OCAwIDEuODA4LTEuMDcgMy40NzMtMi43NiA0LjE2M3pNNy44MDIgMTIuNzAzbC0xLjk1LTEuMTQyYy0uMTY3LS4wOTUtLjIzOS0uMjM4LS4yMzktLjQyOFY1Ljg5OWMwLTIuNTQ1IDEuOTUtNC40NzIgNC41OTEtNC40NzIgMSAwIDEuOTI3LjMzMyAyLjcxMi45MjhMOC4yMyA1LjA2N2MtLjI4NS4xNjYtLjQyOC40MDQtLjQyOC43Mzd2Ni44OTh6TTEyIDE1LjEyOGwtMi43OTUtMS41N3YtMy4zM0wxMiA4LjY1OGwyLjc5NSAxLjU3djMuMzNMMTIgMTUuMTI4em0xLjc5NiA3LjIzYy0xIDAtMS45MjctLjMzMi0yLjcxMi0uOTI3bDQuNjg2LTIuNzEyYy4yODUtLjE2Ni40MjgtLjQwNC40MjgtLjczN3YtNi44OThsMS45NzQgMS4xNDJjLjE2Ny4wOTUuMjM4LjIzOC4yMzguNDI4djUuMjMzYzAgMi41NDUtMS45NzQgNC40NzItNC42MTQgNC40NzJ6bS01LjYzNy01LjMwM2wtNC41NDQtMi42MTdjLTEuMzA4LS43NjEtMi4xODgtMi4zNzgtMi4xODgtMy45NDhBNC40ODIgNC40ODIgMCAwMTQuMjEgNi4zMjd2NS40MjNjMCAuMzMzLjE0My41NzEuNDI4LjczOGw1Ljk0NyAzLjQ0OS0xLjk1IDEuMTE4YS40MzIuNDMyIDAgMDEtLjQ3NiAwem0tLjI2MiAzLjljLTIuNjg4IDAtNC42NjItMi4wMjEtNC42NjItNC41MTkgMC0uMTkuMDI0LS4zOC4wNDctLjU3bDQuNjg2IDIuNzFjLjI4Ni4xNjcuNTcxLjE2Ny44NTYgMGw1Ljk3LTMuNDQ4djIuMjZjMCAuMTktLjA3LjMzMy0uMjM3LjQyOGwtNC41NDMgMi42MTZjLS42MTkuMzU3LTEuMzU2LjUyMy0yLjExNy41MjN6bTUuODk5IDIuODNhNS45NDcgNS45NDcgMCAwMDUuODI3LTQuNzU2QzIyLjI4NyAxOC4zMzkgMjQgMTUuODQgMjQgMTMuMjk2YzAtMS42NjUtLjcxMy0zLjI4Mi0xLjk5OC00LjQ0OC4xMTktLjUuMTktLjk5OS4xOS0xLjQ5OCAwLTMuNDAxLTIuNzU5LTUuOTQ3LTUuOTQ2LTUuOTQ3LS42NDIgMC0xLjI2LjA5NS0xLjg4LjMxQTUuOTYyIDUuOTYyIDAgMDAxMC4yMDUgMGE1Ljk0NyA1Ljk0NyAwIDAwLTUuODI3IDQuNzU3QzEuNzEzIDUuNDQ3IDAgNy45NDUgMCAxMC40OWMwIDEuNjY2LjcxMyAzLjI4MyAxLjk5OCA0LjQ0OC0uMTE5LjUtLjE5IDEtLjE5IDEuNDk5IDAgMy40MDEgMi43NTkgNS45NDYgNS45NDYgNS45NDYuNjQyIDAgMS4yNi0uMDk1IDEuODgtLjMwOWE1Ljk2IDUuOTYgMCAwMDQuMTYyIDEuNzEzeiI+PC9wYXRoPjwvc3ZnPg==", "kimi": "data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFlbSIgc3R5bGU9ImZsZXg6bm9uZTtsaW5lLWhlaWdodDoxIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHdpZHRoPSIxZW0iIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHRpdGxlPktpbWk8L3RpdGxlPjxwYXRoIGQ9Ik0yMS44NDYgMGExLjkyMyAxLjkyMyAwIDExMCAzLjg0NkgyMC4xNWEuMjI2LjIyNiAwIDAxLS4yMjctLjIyNlYxLjkyM0MxOS45MjMuODYxIDIwLjc4NCAwIDIxLjg0NiAweiIgZmlsbD0iIzE3ODNGRiI+PC9wYXRoPjxwYXRoIGQ9Ik0xMS4wNjUgMTEuMTk5bDcuMjU3LTcuMmMuMTM3LS4xMzYuMDYtLjQxLS4xMTYtLjQxSDE0LjNhLjE2NC4xNjQgMCAwMC0uMTE3LjA1MWwtNy44MiA3Ljc1NmMtLjEyMi4xMi0uMzAyLjAxMy0uMzAyLS4xNzlWMy44MmMwLS4xMjctLjA4My0uMjMtLjE4NS0uMjNIMy4xODZjLS4xMDMgMC0uMTg2LjEwMy0uMTg2LjIzVjE5Ljc3YzAgLjEyOC4wODMuMjMuMTg2LjIzaDIuNjljLjEwMyAwIC4xODYtLjEwMi4xODYtLjIzdi0zLjI1YzAtLjA2OS4wMjUtLjEzNS4wNjktLjE3OGwyLjQyNC0yLjQwNmEuMTU4LjE1OCAwIDAxLjIwNS0uMDIzbDYuNDg0IDQuNzcyYTcuNjc3IDcuNjc3IDAgMDAzLjQ1MyAxLjI4M2MuMTA4LjAxMi4yLS4wOTUuMi0uMjN2LTMuMDZjMC0uMTE3LS4wNy0uMjEyLS4xNjQtLjIyN2E1LjAyOCA1LjAyOCAwIDAxLTIuMDI3LS44MDdsLTUuNjEzLTQuMDY0Yy0uMTE3LS4wNzgtLjEzMi0uMjc5LS4wMjgtLjM4MXoiIGZpbGw9ImN1cnJlbnRDb2xvciI+PC9wYXRoPjwvc3ZnPg==", "glm": "data:image/svg+xml;base64,PHN2ZyBoZWlnaHQ9IjFlbSIgc3R5bGU9ImZsZXg6bm9uZTtsaW5lLWhlaWdodDoxIiB2aWV3Qm94PSIwIDAgMjQgMjQiIHdpZHRoPSIxZW0iIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHRpdGxlPkNoYXRHTE08L3RpdGxlPjxkZWZzPjxsaW5lYXJHcmFkaWVudCBpZD0ibG9iZS1pY29ucy1jaGF0Z2xtLWZpbGwiIHgxPSItMTguNzU2JSIgeDI9IjcwLjg5NCUiIHkxPSI0OS4zNzElIiB5Mj0iOTAuOTQ0JSI+PHN0b3Agb2Zmc2V0PSIwJSIgc3RvcC1jb2xvcj0iIzUwNEFGNCI+PC9zdG9wPjxzdG9wIG9mZnNldD0iMTAwJSIgc3RvcC1jb2xvcj0iIzM0ODVGRiI+PC9zdG9wPjwvbGluZWFyR3JhZGllbnQ+PC9kZWZzPjxwYXRoIGQ9Ik05LjkxNyAyYzQuOTA2IDAgMTAuMTc4IDMuOTQ3IDguOTMgMTAuNTgtLjAxNC4wNy0uMDM3LjE0LS4wNTcuMjFsLS4wMDMtLjI3N2MtLjA4My0zLTEuNTM0LTguOTM0LTguODctOC45MzQtMy4zOTMgMC04LjEzNyAzLjA1NC03LjkzIDguMTU4LS4wNCA0Ljc3OCAzLjU1NSA4LjQgNy45NSA4LjMzMmwuMDczLS4wMDFjMS4yLS4wMzMgMi43NjMtLjQyOSAzLjEtMS42NTcuMDYzLS4wMzEuMjYuNTM0LjI2OC41OTguMDQ4LjI1Ni4xMTIuMzY5LjE5Mi4zNC45ODEtLjM0OCAyLjI4Ni0xLjIyMiAxLjk1Mi0yLjM4LS4xNzYtLjYxLTEuNzc1LS4xNDctMS45MjEtLjM0Ny40MTgtLjk3OSAyLjIzNC0uOTI2IDMuMTUzLS43MTYuNDQzLjEwMi42NTcuMzggMS4wMTIuNDQyLjI5LjA1Mi45ODEtLjIuOTYuMjQyLTEuNSAzLjA0Mi00Ljg5MyA1LjQxLTguODA4IDUuNDFDMy42NTQgMjIgMCAxNi41NzQgMCAxMS43MzcgMCA1Ljk0NyA0Ljk1OSAyIDkuOTE3IDJ6TTkuOSA1LjNjLjQ4NCAwIDEuMTI1LjIyNSAxLjM4LjU4NSAzLjY2OS4xNDUgNC4zMTMgMi42ODYgNC42OTQgNS40NDQuMjU1IDEuODM4LjMxNSAyLjMuMTgyIDEuMzg3bC4wODMuNTljLjA2OC40NDguNTU0LjczNy45ODIuNTE2LjE0NC0uMDc1LjI1NC0uMjMxLjMyOC0uNDdhLjIuMiAwIDAxLjI1OC0uMTNsLjYyNS4yMmEuMi4yIDAgMDEuMTI0LjIzOCAyLjE3MiAyLjE3MiAwIDAxLS41MS45MmMtLjg3OC45MTctMi43NTcuNjY0LTMuMDgtLjYyLS4xNC0uNTU0LS4wNTUtLjYyNi0uMzQ1LTEuMjQyLS4yOTItLjYyMS0xLjIzOC0uNzA5LTEuNjktLjI5NS0uMzQ1LjMxNS0uNDA3LjgwNS0uNDA2IDEuMjgyTDEyLjYgMTUuOWEuOS45IDAgMDEtLjkuOWgtMS40YS45LjkgMCAwMS0uOS0uOXYtLjY1YTEuMTUgMS4xNSAwIDEwLTIuMyAwdi42NWEuOS45IDAgMDEtLjkuOUg0LjhhLjkuOSAwIDAxLS45LS45bC4wMzUtMy4yMzljLjAxMi0xLjg4NC4zNTYtMy42NTggMi40Ny00LjEzNC4yLS4wNDUuMjUyLjEzLjI5LjM0Mi4wMjUuMTU0LjA0My4yNTIuMDUzLjI5NC43MDEgMy4wNTggMS43NSA0LjI5OSAzLjE0NCAzLjcyMmwuNjYtLjMzMS4yNTQtLjEzYy4xNTgtLjA4Mi4yNS0uMTMxLjI3Ni0uMTUuMDEyLS4wMS0uMTY1LS4yMDYtLjQwNy0uNDY0bC0xLjAxMi0xLjA2N2E4LjkyNSA4LjkyNSAwIDAxLS4xOTktLjIxNmMtLjA0Ny0uMDM0LS4xMTYuMDY4LS4yMDguMzA2LS4wNzQuMTU3LS4yNTEuMjUyLS4yNzIuMzI2LS4wMTMuMDU4LjEwOC4yOTguMzYyLjcyLjE2NC4yODguMjIuNTA4LS4zMS4zNDMtMS4wNC0uOC0xLjUxOC0yLjI3My0xLjY4NC0zLjcyNS0uMDA0LS4wMzUtLjE2Mi0xLjkxMy0uMTYyLTEuOTEzYTEuMiAxLjIgMCAwMTEuMTEzLTEuMjgxTDkuOSA1LjN6bTEyLjk5NCA4LjY4Yy4wMzcuNjk3LS40MDMuNzA0LTEuMjEzLjU5MWwtMS43ODMtLjI3NmMtLjI2NS0uMDUzLS4zODUtLjA5OS0uMzEzLS4xNDcuNDctLjMxNSAzLjI2OC0uOTMgMy4zMS0uMTY4em0tLjkxNS0uMDgzbC0uOTI2LjA0MmMtLjg1LjA3Ny0xLjQ1Mi4yNC4zMzguMzM2bC4xMDMuMDAzYy44MTUuMDEyIDEuMjY0LS4zNTkuNDg1LS4zODF6bTEuNjY3LTMuNjAxaC4wMWMuNzkuMzk4LjA2NyAxLjAzLS42NSAxLjM5My0uMTQuMDctLjQ5MS4xNzYtMS4wNTIuMzE1LS4yNDEuMDQtLjQ1Ny4wOTItLjMzMy4xNmwuMDEuMDA1YzEuOTUyLjk1OC0zLjEyMyAxLjUzNC0yLjQ5NSAxLjI4NWwuMzgtLjE0OGMuNjgtLjI2NiAxLjYxNC0uNjgyIDEuNjY2LTEuMzM3LjAzOC0uNDggMS4yNTMtLjQ0MiAxLjQ5My0uOTY4LjA0OC0uMTA2IDAtLjIzNi0uMTQ0LS4zODktLjA1LS4wNDctLjA5NC0uMDk0LS4xMDctLjE0OC0uMDczLS4zMDUuNy0uNDMxIDEuMjIyLS4xNjh6bS0yLjU2OC0uNDc0Yy0uMTM1IDEuMTk4LTIuNDc5IDQuMTkyLTEuOTQ5IDIuODYzbC4wMTctLjA0MmMuMjk4LS43MTcuMzc2LTIuMjIxIDEuMzM3LTMuMjIxLjI1LS4yNi42MzYuMDM1LjU5NS40em0tNy45NzYtLjI1M2MuMDItLjY5NCAxLjAwMi0uOTY4IDEuMzQ2LS4zNDcuMDEtMS4yNzQtMS45NDEtLjc2OC0xLjM0Ni4zNDd6IiBmaWxsPSJ1cmwoI2xvYmUtaWNvbnMtY2hhdGdsbS1maWxsKSIgZmlsbC1ydWxlPSJldmVub2RkIj48L3BhdGg+PC9zdmc+"};

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const el = (tag, cls, html) => { const e = document.createElement(tag); if(cls) e.className = cls; if(html != null) e.innerHTML = html; return e; };
const pick = a => a[Math.floor(Math.random() * a.length)];
const store = {
  get(k, d){ try { const v = localStorage.getItem(k); return v == null ? d : v; } catch(e){ return d; } },
  set(k, v){ try { localStorage.setItem(k, v); } catch(e){} },
  json(k, d){ try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch(e){ return d; } }
};

/* ── cards ── */
const SUITS = [{id:'oros',es:'Oros',pinta:0},{id:'copas',es:'Copas',pinta:1},{id:'espadas',es:'Espadas',pinta:2},{id:'bastos',es:'Bastos',pinta:3}];
const SUIT_FILE = {oros:'coins',copas:'cups',espadas:'swords',bastos:'clubs'};
const RANKS = [1,2,3,4,5,6,7,10,11,12];
const RANK_NUM = {as:1,dos:2,tres:3,cuatro:4,cinco:5,seis:6,siete:7,sota:10,caballo:11,rey:12};
const RANK_ES = Object.fromEntries(Object.entries(RANK_NUM).map(([k,v]) => [v,k]));
function parseCard(name){ const m = String(name).match(/^(\w+) de (\w+)$/); return m && RANK_NUM[m[1]] ? {r:RANK_NUM[m[1]], s:m[2]} : null; }
function cardSrc(s, r){ return CARDS + 'card_' + SUIT_FILE[s] + '_' + String(r).padStart(2,'0') + '.svg'; }
/* card: {s,r} | null (back). w: width px */
function cardNode(card, w, extra){
  const h = Math.round(w * 1.53);
  const d = el('div', 'pc' + (card ? '' : ' back') + (extra ? ' ' + extra : ''));
  d.style.width = w + 'px'; d.style.height = h + 'px';
  if(card){
    const img = document.createElement('img');
    img.src = cardSrc(card.s, card.r); img.alt = RANK_ES[card.r] + ' de ' + card.s; img.draggable = false; img.decoding = 'async';
    d.appendChild(img);
  } else d.appendChild(el('div', 'dia'));
  return d;
}
function setCard(node, card){
  const img = node.querySelector('img');
  if(card && img){ const src = cardSrc(card.s, card.r); if(img.getAttribute('src') !== src){ img.src = src; img.alt = RANK_ES[card.r] + ' de ' + card.s; } }
}
const gv = r => r === 3 ? 12 : r;   // engine rule: tres = rey; the dos is its own card
const jv = r => r === 3 ? 10 : r === 2 ? 1 : r >= 10 ? 10 : r;
function paresOf(cards){
  const m = {}; cards.forEach(c => { const v = gv(c.r); m[v] = (m[v] || 0) + 1; });
  const vals = Object.keys(m).map(Number);
  if(vals.some(v => m[v] === 4) || vals.filter(v => m[v] === 2).length === 2) return 'duples';
  if(vals.some(v => m[v] === 3)) return 'medias';
  if(vals.some(v => m[v] === 2)) return 'par';
  return 'sin pares';
}
const sumOf = cards => cards.reduce((a, c) => a + jv(c.r), 0);

/* ── models: colour + icon ── */
const FAMILIES = [
  [/deepseek/i,'DeepSeek','oklch(0.8 0.08 205)','deepseek'],
  [/qwen/i,'Alibaba','oklch(0.8 0.09 300)','qwen'],
  [/gemma|gemini/i,'Google','oklch(0.83 0.08 160)','gemma'],
  [/glm|zhipu/i,'Zhipu','oklch(0.8 0.09 265)','glm'],
  [/llama|meta/i,'Meta','oklch(0.8 0.09 250)','meta'],
  [/mistral/i,'Mistral','oklch(0.84 0.09 70)','mistral'],
  [/gpt|openai/i,'OpenAI','oklch(0.88 0.02 260)','openai'],
  [/kimi|moonshot/i,'Moonshot','oklch(0.8 0.09 350)','kimi'],
  [/jev/i,'jev','oklch(0.84 0.09 70)',null],
  [/heuristic|random|offline/i,'offline','var(--color-neutral-400)',null]
];
function family(name){ const n = String(name || ''); for(const f of FAMILIES) if(f[0].test(n)) return {lab:f[1], color:f[2], icon:f[3] ? ICONS[f[3]] || '' : '', mono:f[3] === 'openai'}; return {lab:'', color:'var(--color-text)', icon:'', mono:false}; }
const cleanModel = m => String(m || '').replace(/^[a-z]+:/i, '');
function iconImg(name, size){
  const f = family(name); if(!f.icon) return '';
  return '<img src="' + f.icon + '" alt="" style="width:' + size + 'px;height:' + size + 'px;object-fit:contain' + (f.mono ? ';filter:invert(1)' : '') + '">';
}

/* ── session state ── */
const params = new URLSearchParams(location.search);
let TOKEN = params.get('token') || store.get('mus_token', null);
let SID = store.get('mus_sid', null);
const REVEAL = params.get('reveal') === 'all' ? 'all' : 'none';
let NICK = store.get('mus.nick', '');
let NOTE = '';
let S = null, lastVersion = -1, needNew = false, connOk = null;

function qs(){
  const q = new URLSearchParams();
  if(TOKEN) q.set('token', TOKEN);
  if(SID) q.set('sid', SID);
  q.set('reveal', REVEAL);
  return q.toString();
}
function headers(){ const h = {'Content-Type':'application/json'}; if(SID) h['X-Mus-Session'] = SID; return h; }
function post(path, body){
  return fetch(API + path, {method:'POST', headers:headers(), credentials:'include',
    body:JSON.stringify(Object.assign({token:TOKEN, sid:SID}, body || {}))})
    .then(r => r.json().catch(() => ({ok:false, error:'respuesta inválida'})));
}

/* ── seats relative to me ── */
function mySeat(){ return S && S.you ? S.you.seat : 0; }
function myTeam(){ return S && S.you ? S.you.team : 0; }
function areaOf(seat){ const d = (seat - mySeat() + 4) % 4; return ['me','left','top','right'][d]; }
function seatAt(area){ const d = {me:0,left:1,top:2,right:3}[area]; return (mySeat() + d) % 4; }
const teamWord = t => t === myTeam() ? 'nosotros' : 'ellos';
function displayName(seat){
  const s = S && S.seats[seat]; if(!s) return '';
  if(S.you && seat === S.you.seat) return NICK || 'tú';
  if(s.is_llm) return cleanModel(s.model);
  return s.name;
}
function modelKey(seat){ const s = S && S.seats[seat]; return s ? (s.is_llm ? s.model : s.model || s.name) : ''; }

/* ═════════ RENDER: mesa ═════════ */
const seatEls = {};
['left','top','right'].forEach(a => {
  const root = $('seat-' + a);
  root.innerHTML = '<div class="who"><div class="avatar"></div><div class="nm"><span class="name"></span><span class="role"></span></div></div>' +
    '<div class="hand"><div class="fxlayer"></div></div><div class="say"></div>';
  seatEls[a] = {root, avatar:root.querySelector('.avatar'), name:root.querySelector('.name'), role:root.querySelector('.role'),
    hand:root.querySelector('.hand'), fx:root.querySelector('.fxlayer'), say:root.querySelector('.say'), sig:null, speech:null};
});
seatEls.me = {root:$('you'), hand:$('myhand'), fx:$('myfx'), say:$('mysay'), sig:null, speech:null};

let selected = new Set();
let recap = null;          // {hand, until, data}
let lastRevealHand = null;

function rivalCardW(){ return innerWidth < 720 ? 40 : 64; }
function myCardW(){ return innerWidth < 420 ? 72 : innerWidth < 720 ? 80 : 96; }

function renderSeat(area){
  const E = seatEls[area], seat = seatAt(area);
  const s = S ? S.seats[seat] : null;
  if(!s){ // placeholder before a game exists
    const sig = 'empty' + rivalCardW();
    if(E.sig !== sig){ E.sig = sig; E.avatar.innerHTML = '<span>·</span>'; E.name.textContent = area === 'top' ? 'compañero' : 'rival';
      E.name.style.color = 'var(--color-neutral-500)'; E.role.textContent = area === 'top' ? 'por sentarse' : 'por sentarse';
      E.hand.querySelectorAll('.slot').forEach(n => n.remove());
      for(let i = 0; i < 4; i++){ const sl = el('div','slot'); sl.appendChild(cardNode(null, rivalCardW())); E.hand.appendChild(sl); }
      E.hand.style.opacity = .35; }
    E.root.classList.remove('thinking'); E.avatar.style.boxShadow = 'none';
    return;
  }
  E.hand.style.opacity = '';
  const name = displayName(seat), key = modelKey(seat), f = family(key);
  const partner = s.team === myTeam();
  E.root.classList.toggle('thinking', !!s.thinking);
  E.avatar.style.boxShadow = s.thinking ? '0 0 0 3px color-mix(in srgb, ' + f.color + ' 22%, transparent), 0 0 16px ' + f.color : 'none';
  const head = name + '|' + key;
  if(E.head !== head){ E.head = head;
    E.avatar.innerHTML = '<span style="color:' + f.color + '">' + esc((name[0] || '?').toUpperCase()) + '</span>' +
      (f.icon ? '<img src="' + f.icon + '" alt="' + esc(f.lab) + '"' + (f.mono ? ' style="filter:invert(1)"' : '') + '>' : '');
    E.name.textContent = name; E.name.style.color = f.color; E.name.title = s.model || '';
  }
  const decl = s.declared === true ? (S.lance ? 'con ' + S.lance.toLowerCase() : 'tengo') : s.declared === false ? (S.lance ? 'sin ' + S.lance.toLowerCase() : 'no tengo') : '';
  E.role.textContent = [partner ? 'compañero' : 'rival', f.lab, S.mano === seat ? 'mano' : '', s.folded ? 'fuera' : '', decl].filter(Boolean).join(' · ');
  // cards: back, director view, or the end-of-hand reveal
  let cards = null, mode = 'back';
  const rv = recapShowing() ? recap.data : null;
  if(rv && rv.hands && rv.hands[seat]){ cards = rv.hands[seat].map(parseCard); mode = 'rev' + rv.hand; }
  else if(S.director && s.hand && s.hand.length){ cards = s.hand.map(parseCard); mode = 'dir'; }
  const sig = mode + '|' + (cards ? cards.map(c => c ? c.s + c.r : '?').join(',') : '') + '|' + S.scores.hands_played + '|' + rivalCardW();
  if(E.sig !== sig){
    const dealing = !E.sig || E.sig.split('|')[2] !== String(S.scores.hands_played);
    E.sig = sig;
    E.hand.querySelectorAll('.slot').forEach(n => n.remove());
    for(let i = 0; i < 4; i++){
      const sl = el('div', 'slot');
      const c = cards ? cards[i] : null;
      const n = cardNode(c || null, rivalCardW(), mode.startsWith('rev') ? 'flipin' : dealing ? 'deal' : '');
      n.style.animationDelay = (mode.startsWith('rev') ? i * 90 : dealing ? i * 70 + {left:0,top:280,right:560}[area] : 0) + 'ms';
      sl.appendChild(n); E.hand.appendChild(sl);
    }
  }
  // speech line: thinking beats speech
  if(s.thinking){
    if(!E.say.querySelector('.thinkingtxt')) E.say.innerHTML = '<span class="thinkingtxt">pensando</span>';
  } else if(E.say.querySelector('.thinkingtxt')) E.say.innerHTML = '';
}

function renderMe(){
  const E = seatEls.me;
  const hand = (S && S.you && S.you.hand || []).map(parseCard).filter(Boolean);
  const legal = (S && S.you && S.you.legal) || [];
  const discard = legal.includes('discard');
  if(!discard && selected.size) selected.clear();
  const sig = hand.map(c => c.s + c.r).join(',') + '|' + (S ? S.scores.hands_played : 0) + '|' + myCardW();
  if(E.sig !== sig){
    const old = E.sig ? E.sig.split('|')[0].split(',') : [];
    E.sig = sig; selected.clear();
    E.hand.querySelectorAll('.mycard').forEach(n => n.remove());
    if(!hand.length){ for(let i = 0; i < 4; i++){ const w = el('div','mycard'); w.appendChild(cardNode(null, myCardW())); w.style.opacity = .3; E.hand.appendChild(w); } }
    hand.forEach((c, i) => {
      const key = c.s + c.r, fresh = !old.includes(key);
      const w = el('div', 'mycard'); w.dataset.card = RANK_ES[c.r] + ' de ' + c.s;
      const n = cardNode(c, myCardW(), fresh ? 'deal' : '');
      n.style.animationDelay = (fresh ? 120 + i * 90 : 0) + 'ms';
      w.appendChild(n); E.hand.appendChild(w);
      w.addEventListener('click', () => toggleCard(w));
      w.addEventListener('keydown', e => { if(e.key === ' ' || e.key === 'Enter'){ e.preventDefault(); toggleCard(w); } });
    });
  }
  E.hand.querySelectorAll('.mycard').forEach(w => {
    w.classList.toggle('pick', discard); w.classList.toggle('sel', discard && selected.has(w.dataset.card));
    if(discard){ w.tabIndex = 0; w.setAttribute('role','button'); w.setAttribute('aria-pressed', String(selected.has(w.dataset.card))); }
    else { w.removeAttribute('tabindex'); w.removeAttribute('role'); w.removeAttribute('aria-pressed'); }
  });
  $('myinfo').textContent = hand.length ? [NICK || 'tú', paresOf(hand), (sumOf(hand) >= 31 ? 'juego ' : 'punto ') + sumOf(hand),
    S.mano === mySeat() ? 'mano' : ''].filter(Boolean).join(' · ') : '';
  $('err').textContent = S && S.you && S.you.error ? 'Acción rechazada: ' + S.you.error : '';
  renderButtons(legal);
}
function toggleCard(w){
  const legal = (S && S.you && S.you.legal) || [];
  if(!legal.includes('discard')) return;
  const k = w.dataset.card; if(selected.has(k)) selected.delete(k); else selected.add(k);
  renderMe();
}

const LABELS = {mus:'Mus', no:'No hay mus', ordago:'Órdago', tengo:'Tengo', 'no-tengo':'No tengo', paso:'Paso',
  envido:'Envido · 2', 'y-yo':'Y yo · +2', reenvido:'Reenvido · ×2', quiero:'Quiero', 'no-quiero':'No quiero'};
const SOFT = new Set(['paso','no-quiero','no-tengo']);
const ORDER = ['mus','no','tengo','no-tengo','paso','envido','y-yo','reenvido','quiero','no-quiero','ordago'];
let btnSig = null, armTimer = null;
function renderButtons(legal){
  const sig = legal.join(',') + '|' + selected.size + '|' + (S && S.lance);
  if(sig === btnSig) return; btnSig = sig;
  const box = $('btns'); box.replaceChildren();
  if(!legal.length) return;
  if(legal.includes('discard')){
    const n = selected.size;
    const b = el('button', 'pill' + (n ? '' : ' soft'), n ? 'Descartar ' + n : 'Elige qué tirar'); b.disabled = !n;
    b.onclick = () => act({action:'discard', cards:[...selected]});
    const all = el('button', 'pill soft', 'Las cuatro'); all.onclick = () => act({action:'discard', cards:S.you.hand.slice()});
    box.append(b, all);
  } else {
    let shown = legal.slice();
    const truth = declTruth();
    if(truth !== null && shown.includes('tengo') && shown.includes('no-tengo')) shown = shown.filter(a => a !== (truth ? 'no-tengo' : 'tengo'));
    shown.sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)).forEach(a => {
      const b = el('button', 'pill' + (a === 'ordago' ? ' hot' : SOFT.has(a) ? ' soft' : ''), esc(LABELS[a] || a));
      b.onclick = () => {
        if(a === 'ordago' && !b.classList.contains('arm')){
          b.classList.add('arm'); b.textContent = '¿Órdago? Confirma';
          clearTimeout(armTimer); armTimer = setTimeout(() => { b.classList.remove('arm'); b.textContent = LABELS.ordago; }, 3000);
          return;
        }
        act({action:a});
      };
      box.appendChild(b);
    });
  }
  const d = el('button', 'linkbtn', 'por defecto'); d.title = 'Juega la acción legal por defecto';
  d.onclick = () => act({action:'__default__'}); box.appendChild(d);
}
function declTruth(){
  if(!S || S.phase !== 'DECLARE' || !S.lance || !S.you) return null;
  const hand = (S.you.hand || []).map(parseCard).filter(Boolean); if(hand.length !== 4) return null;
  const l = S.lance.toLowerCase();
  if(l.startsWith('pares')) return paresOf(hand) !== 'sin pares';
  if(l.startsWith('juego')) return sumOf(hand) >= 31;
  return null;
}
function act(obj){
  btnSig = null; $('btns').querySelectorAll('button').forEach(b => b.disabled = true);
  post('/api/action', obj).then(d => { if(!d.ok){ flash(d.error || 'error'); btnSig = null; if(S) renderMe(); } });
}
function flash(t){ $('err').textContent = t; setTimeout(() => { if($('err').textContent === t) $('err').textContent = ''; }, 4500); }

const PHASES = {MUS_REQUEST:'Mus', MUS_DRAW:'Descarte', DECLARE:'Declaración', ENVITE:'Lance', ORDAGO_RESPONSE:'Órdago', DONE:'Recuento'};
function recapShowing(){ return recap && Date.now() < recap.until; }
let centerSig = null;
function renderCenter(){
  const C = $('center');
  if(!S){
    const sig = 'start|' + needNew + '|' + NOTE;
    if(centerSig === sig) return; centerSig = sig;
    C.innerHTML = '';
    const lab = el('label', 'nick'); lab.innerHTML = '<span>Tu nombre en la mesa</span>';
    const inp = el('input'); inp.maxLength = 20; inp.placeholder = 'nombre o mote'; inp.spellcheck = false; inp.value = NICK;
    inp.oninput = () => { NICK = inp.value.trim().slice(0, 20); store.set('mus.nick', NICK); };
    inp.onkeydown = e => { if(e.key === 'Enter') startGame(); };
    lab.appendChild(inp);
    const b = el('button', 'cta', 'Sentarse'); b.id = 'startbtn'; b.onclick = startGame;
    C.append(lab, b, el('div', 'note', esc(NOTE || 'Tres modelos de lenguaje: uno de compañero, dos enfrente. Una vaca, a 40 piedras.')));
    return;
  }
  const finished = S.status !== 'running';
  if(finished){
    const sig = 'over|' + S.status + '|' + S.scores.vacas_a + S.scores.vacas_b;
    if(centerSig === sig) return; centerSig = sig;
    const va = myTeam() === 0 ? S.scores.vacas_a : S.scores.vacas_b, vb = myTeam() === 0 ? S.scores.vacas_b : S.scores.vacas_a;
    const msg = S.status === 'finished' ? (va > vb ? 'La vaca es vuestra.' : va < vb ? 'La vaca es suya.' : 'Vaca sin decidir.')
      : S.status === 'error' ? 'La partida se cortó: ' + (S.error || 'error') : 'Partida detenida.';
    C.innerHTML = '';
    C.appendChild(el('div', 'ph', 'Fin de la partida'));
    C.appendChild(el('div', 'ln', esc(va + ' – ' + vb)));
    const b = el('button', 'cta', 'Otra vaca'); b.onclick = startGame;
    C.append(b, el('div', 'note', esc(msg)));
    return;
  }
  if(recapShowing()){
    const r = recap.data, sig = 'recap|' + r.hand;
    if(centerSig === sig) return; centerSig = sig;
    const gu = myTeam() === 0 ? r.gain.a : r.gain.b, gt = myTeam() === 0 ? r.gain.b : r.gain.a;
    C.innerHTML = '<div class="recap"><div class="ph">Mano ' + r.hand + ' · recuento</div>' +
      '<div class="gain">+' + gu + ' <span class="muted" style="font-size:18px">nosotros</span> · +' + gt + ' <span class="muted" style="font-size:18px">ellos</span></div>' +
      '<div class="jg">' + (r.jugadas || []).map(j => j.name + ' <b class="' + (j.winner === myTeam() ? 'us' : '') + '">' +
        (j.winner == null ? '—' : teamWord(j.winner)) + '</b>').join('') + '</div></div>';
    return;
  }
  const ph = PHASES[S.phase] || '';
  const ln = S.lance || (S.phase === 'MUS_REQUEST' ? 'Mus' : S.phase === 'MUS_DRAW' ? 'Descarte' : ph);
  let bet = '';
  if(S.ordago) bet = 'Órdago de ' + teamWord(S.ordago.caller % 2) + ' · la vaca en juego';
  else if(S.envite && S.envite.current > 0) bet = (S.envite.holder ? teamWord(S.envite.holder.team) + ' · ' : '') + S.envite.current + ' piedras' + (S.envite.locked ? ' · querido' : '');
  else if(S.phase === 'MUS_REQUEST' && S.mus_round) bet = 'ronda de descarte ' + S.mus_round;
  const myTurn = !!(S.you && S.you.legal && S.you.legal.length);
  const who = S.thinking_seat != null ? S.thinking_seat : S.turn;
  const turn = myTurn ? 'te toca' : (who != null && S.seats[who] ? (S.thinking_seat != null ? 'piensa ' : 'turno de ') + displayName(who) : '');
  const caught = (S.you && S.you.caught) || [];
  const sig = [ph, ln, bet, turn, caught.map(c => c.gesture).join(',')].join('|');
  if(centerSig === sig) return;
  const lnChanged = !centerSig || centerSig.split('|')[1] !== ln;
  centerSig = sig;
  C.innerHTML = '<div class="ph">' + esc(ph) + '</div><div class="ln"' + (lnChanged ? ' style="animation:rise .5s var(--ease) both"' : '') + '>' + esc(ln) + '</div>' +
    '<div class="bet">' + esc(bet) + '</div><div class="turn">' + esc(turn) + '</div>' +
    (caught.length ? '<div class="chips">' + caught.map(c => '<span class="chip" title="' + esc(c.gesture) + '">' + esc(c.meaning) + '</span>').join('') + '</div>' : '');
}

let lastPts = [0, 0];
function renderScore(){
  const sc = S ? S.scores : {points_a:0, points_b:0, vacas_a:0, vacas_b:0};
  const us = myTeam() === 0 ? [sc.points_a, sc.vacas_a] : [sc.points_b, sc.vacas_b];
  const th = myTeam() === 0 ? [sc.points_b, sc.vacas_b] : [sc.points_a, sc.vacas_a];
  [['sus', us[0], 0], ['sthem', th[0], 1]].forEach(([id, v, i]) => {
    const e = $(id); if(e.textContent !== String(v)){ e.textContent = v; if(v > lastPts[i]){ e.classList.add('bump'); setTimeout(() => e.classList.remove('bump'), 900); } lastPts[i] = v; }
  });
  const dots = n => '<i></i>'.repeat(Math.min(n, 6));
  if($('vus').dataset.n !== String(us[1])){ $('vus').dataset.n = us[1]; $('vus').innerHTML = dots(us[1]); }
  if($('vthem').dataset.n !== String(th[1])){ $('vthem').dataset.n = th[1]; $('vthem').innerHTML = dots(th[1]); }
}
function renderLineup(){
  const L = $('lineup');
  if(!S){ L.innerHTML = ''; return; }
  const nm = a => { const s = seatAt(a); return '<b style="color:' + family(modelKey(s)).color + '">' + esc(displayName(s)) + '</b>'; };
  const sig = [0,1,2,3].map(displayName).join('|');
  if(L.dataset.sig === sig) return; L.dataset.sig = sig;
  L.innerHTML = '<span>con</span>' + nm('top') + '<span>· contra</span>' + nm('left') + '<span>y</span>' + nm('right');
}

/* ── feed (cante) ── */
const FEED_SKIP = new Set(['thought','policy','chat_redacted','sena_note']);
let feedLast = -1;
function feedRow(ev){
  if(FEED_SKIP.has(ev.kind)) return null;
  let who = '', color = '', text = ev.text || '', cls = 'r';
  const seat = ev.seat;
  const nameOf = s => S && S.seats[s] ? displayName(s) : '';
  if(ev.kind === 'chat' && seat != null){
    who = nameOf(seat); color = family(modelKey(seat)).color; text = chatText(ev.text);
  } else if(['envite','declare','discard','mus','sena','sena_caught','fallback','timeout','rejected','api_error'].includes(ev.kind) && seat != null){
    who = nameOf(seat); color = family(modelKey(seat)).color;
    const raw = S && S.seats[seat] ? S.seats[seat].name : '';
    if(raw && text.startsWith(raw)) text = text.slice(raw.length).replace(/^[\s:]+/, '');
    if(ev.kind === 'sena') text = ev.gesture ? 'seña: ' + ev.gesture + (ev.meaning ? ' · ' + ev.meaning : '') : 'hizo un gesto a su compañero';
    if(['fallback','timeout','rejected','api_error'].includes(ev.kind)) cls += ' bad';
  } else {
    cls += ' sys';
    if(ev.kind === 'hand_start'){ cls += ' newhand'; text = 'reparto · mano ' + ev.hand; }
    if(ev.kind === 'lance') text = text.replace(/equipo A/g, teamWord(0)).replace(/equipo B/g, teamWord(1));
    if(ev.kind === 'hand_end' || ev.kind === 'vaca' || ev.kind === 'match_end'){ cls += ' hot';
      text = text.replace(/el Equipo ([AB])/g, (_, t) => teamWord(t === 'A' ? 0 : 1)).replace(/\bA\b/g, teamWord(0)).replace(/\bB\b/g, teamWord(1)).replace(/\s*->\s*/g, ' · '); }
    if(ev.kind === 'match') text = 'se abre la mesa · una vaca a 40 piedras';
    if(ev.kind === 'error') cls += ' bad';
  }
  const r = el('div', cls);
  if(who) r.innerHTML = '<span class="w" style="color:' + color + '">' + esc(who) + '</span><span class="tx">' + esc(text) + '</span>';
  else r.innerHTML = '<span class="tx">' + esc(text) + '</span>';
  return r;
}
function chatText(t){ const m = String(t).match(/^[^:]*:\s*"([\s\S]*)"\s*$/); return m ? m[1] : String(t).replace(/^[^:]*:\s*/, ''); }
function renderFeed(reset){
  const F = $('feed'), pane = $('pane-feed');
  const atBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 40;
  if(reset){ F.replaceChildren(); feedLast = -1; if(NOTE) F.appendChild(el('div', 'r sys hot', '<span class="tx">' + esc(NOTE) + '</span>')); }
  const evs = (S.feed || []).filter(e => e.i > feedLast);
  if(!evs.length) return;
  const frag = document.createDocumentFragment();
  evs.forEach(ev => { const r = feedRow(ev); if(r) frag.appendChild(r); });
  feedLast = evs[evs.length - 1].i;
  F.appendChild(frag);
  while(F.childElementCount > 220) F.firstElementChild.remove();
  if(atBottom || reset) pane.scrollTop = pane.scrollHeight;
}

/* ── animations driven by new events ── */
let animLast = null;
const SAY = {mus:'mus', no:'no hay mus', paso:'paso', envido:'envido', 'y-yo':'y yo', reenvido:'reenvido', quiero:'quiero',
  'no-quiero':'no quiero', ordago:'órdago', tengo:'tengo', 'no-tengo':'no tengo'};
function actionOf(ev){
  if(ev.action) return ev.action;
  const t = ev.text || '';
  if(ev.kind === 'envite'){
    if(/órdago/i.test(t)) return 'ordago'; if(/no quiere/.test(t)) return 'no-quiero'; if(/quiere/.test(t)) return 'quiero';
    if(/reenvida/.test(t)) return 'reenvido'; if(/y yo/.test(t)) return 'y-yo'; if(/envida/.test(t)) return 'envido'; return 'paso';
  }
  if(ev.kind === 'declare') return /no tengo/.test(t) ? 'no-tengo' : 'tengo';
  return null;
}
function speak(area, text, cls){
  const E = seatEls[area]; if(!E || !text) return;
  if(area !== 'me' && E.say.querySelector('.thinkingtxt')) return;
  const n = el('div', cls || 'line', '«' + esc(text) + '»');
  E.say.replaceChildren(n);
  const id = Math.random(); E.speech = id;
  setTimeout(() => { if(E.speech === id && n.parentNode) n.remove(); }, cls === 'gest' ? 4200 : 3600);
}
function seatFx(area, kind, text, n){
  const E = seatEls[area]; if(!E) return;
  const dur = kind === 'ordago' ? 2000 : kind === 'corte' ? 1500 : 1400;
  const box = el('div', 'sfx' + (kind === 'ordago' ? ' ord' : kind === 'corte' ? ' cut' : ''));
  box.style.setProperty('--dur', dur + 'ms');
  if(kind === 'ordago') box.innerHTML = '<div class="rg"></div><div class="rg b"></div><span class="ot">Órdago</span>';
  else if(kind === 'corte') box.innerHTML = '<div class="split"><div class="t ghostt">No hay mus</div><div class="t u">No hay mus</div><div class="t d">No hay mus</div><div class="sl"><div></div></div></div>';
  else {
    box.innerHTML = '<span class="et">' + esc(text) + '</span>' + (n ? '<div class="dots">' +
      Array.from({length:Math.min(n, 40)}, (_, i) => '<i style="animation-delay:' + (80 + i * 35) + 'ms"></i>').join('') + '</div>' : '');
  }
  E.fx.replaceChildren(box);
  setTimeout(() => { if(box.parentNode) box.remove(); }, dur);
}
function tableFx(kind, text, sub){
  const dur = 2600;
  const L = $('tfxlayer');
  const f = el('div', 'tfx'); f.style.setProperty('--dur', dur + 'ms');
  if(kind === 'ordago') f.innerHTML = '<div class="rg"></div><div class="rg b"></div><div class="rg c"></div>';
  f.innerHTML += '<div class="big">' + esc(text) + '</div><div class="sub">' + esc(sub || '') + '</div>';
  L.replaceChildren(f);
  setTimeout(() => { if(f.parentNode) f.remove(); }, dur);
}
function animate(evs){
  const chatted = new Set(evs.filter(e => e.kind === 'chat' && e.seat != null).map(e => e.seat));
  let prevOrdago = !!(prevSnap && prevSnap.ordago);
  evs.forEach(ev => {
    const seat = ev.seat, area = seat != null && S.seats[seat] ? areaOf(seat) : null;
    if(ev.kind === 'chat' && area){ speak(area, chatText(ev.text)); return; }
    if(ev.kind === 'sena' && area){ if(ev.gesture) speak(area, ev.gesture.replace(/-/g, ' '), 'gest'); else if(area !== 'me') speak(area, 'hace un gesto', 'gest'); return; }
    if(ev.kind === 'vaca'){
      const va = S.scores.vacas_a, vb = S.scores.vacas_b;
      const us = myTeam() === 0 ? va : vb, them = myTeam() === 0 ? vb : va;
      tableFx('ordago', 'Vaca', (us > them ? 'para nosotros' : 'para ellos') + ' · ' + us + '–' + them); return;
    }
    if(!area) return;
    const a = actionOf(ev);
    if(ev.kind === 'mus' || ev.kind === 'envite' || ev.kind === 'declare'){
      if(a === 'no' && ev.kind === 'mus') seatFx(area, 'corte');
      else if(a === 'ordago'){ seatFx(area, 'ordago'); tableFx('ordago', 'Órdago', displayName(seat) + ' · la vaca a un lance'); }
      else if(a === 'envido') seatFx(area, 'envite', 'Envido 2', 2);
      else if(a === 'y-yo') seatFx(area, 'envite', 'Y yo · ' + ((S.envite && S.envite.current) || ''), 2);
      else if(a === 'reenvido'){ const c = (S.envite && S.envite.current) || 4; seatFx(area, 'envite', 'Reenvido · ' + c, Math.min(c, 40)); }
      else if(a === 'quiero' && prevOrdago){ tableFx('ordago', 'Quiero', 'órdago aceptado · se enseñan las cartas'); }
      if(!chatted.has(seat)){
        let line = SAY[a] || '';
        if(ev.kind === 'declare' && S.lance) line = (a === 'tengo' ? 'tengo ' : 'no tengo ') + S.lance.toLowerCase();
        if(line && !(a === 'no' && ev.kind === 'mus')) speak(area, line);
      }
    } else if(ev.kind === 'discard'){
      const n = (ev.cards || []).length || (String(ev.text).match(/(\d+)/) || [])[1] || '';
      if(!chatted.has(seat)) speak(area, area === 'me' ? 'descarto ' + n : 'me echo ' + n);
    }
  });
}

/* ── señas ── */
let senasBuilt = false;
function renderSenas(){
  const vocab = (S && S.senas_vocab) || null;
  if(vocab && !senasBuilt){
    senasBuilt = true;
    const g = $('senagrid'); g.replaceChildren();
    Object.entries(vocab).forEach(([k, m]) => {
      const b = el('button', '', '<span class="g">' + esc(k.replace(/-/g, ' ')) + '</span><span class="m">' + esc(m) + '</span>');
      b.onclick = () => post('/api/sena', {gesture:k}).then(d => { if(!d.ok) flash(d.error || 'seña rechazada'); else speak('me', k.replace(/-/g, ' '), 'gest'); });
      g.appendChild(b);
    });
    buildSenaGuide(vocab);
  }
  const mine = (S && S.you && S.you.my_senas) || [];
  const sig = mine.map(s => s.gesture + s.truthful).join(',');
  if($('mysenas').dataset.sig !== sig){ $('mysenas').dataset.sig = sig;
    $('mysenas').innerHTML = mine.length ? '<div class="eyebrow" style="margin-bottom:6px">Tus señas</div>' + mine.map(s =>
      '<div style="font-size:12px;color:var(--color-neutral-400)">' + esc(s.gesture.replace(/-/g, ' ')) + (s.truthful ? ' · veraz' : ' · farol') + '</div>').join('') : '';
  }
}
function buildSenaGuide(vocab){
  const box = $('d-senas'); if(!box || box.childElementCount) return;
  Object.entries(vocab).forEach(([k, m]) => box.appendChild(el('div', '', '<b>' + esc(k.replace(/-/g, ' ')) + '</b><span>' + esc(m) + '</span>')));
}

/* ── main render ── */
let prevSnap = null;
function render(){
  renderScore(); renderLineup();
  ['left','top','right'].forEach(renderSeat);
  if(S) renderMe(); else { seatEls.me.sig = null; renderMeEmpty(); }
  renderCenter();
  if(S) renderSenas();
  $('newvaca').hidden = !S || !SID;
}
function renderMeEmpty(){
  const E = seatEls.me;
  if(E.hand.querySelector('.mycard')) return;
  for(let i = 0; i < 4; i++){ const w = el('div', 'mycard'); w.appendChild(cardNode(null, myCardW())); w.style.opacity = .3; E.hand.appendChild(w); }
  $('myinfo').textContent = ''; $('btns').replaceChildren(); btnSig = null;
}

function applySnapshot(d){
  if(!d) return;
  if(d.need_new){ if(S || !needNew){ needNew = true; S = null; prevSnap = null; feedLast = -1; $('feed').replaceChildren(); render(); } setStatus('idle'); return; }
  if(typeof d.version !== 'number' || d.version === lastVersion) return;
  const first = !S;
  needNew = false;
  prevSnap = S; S = d; lastVersion = d.version;
  setStatus('live');
  // end-of-hand reveal → recap window
  if(S.reveal && S.reveal.hand !== lastRevealHand){
    if(lastRevealHand !== null || !first) recap = {data:S.reveal, until:Date.now() + 4800};
    lastRevealHand = S.reveal.hand;
    setTimeout(() => { if(S) render(); }, 4900);
  }
  const maxI = (S.feed || []).reduce((m, e) => Math.max(m, e.i), -1);
  if(prevSnap && maxI < feedLast){ renderFeed(true); animLast = maxI; }   // new game: event ids restart
  else renderFeed(first);
  if(animLast === null || first) animLast = maxI;
  else { const fresh = (S.feed || []).filter(e => e.i > animLast); animLast = maxI; if(fresh.length) animate(fresh); }
  recordResult();
  render();
}

/* ── transport ── */
let es = null;
function setStatus(k){
  const st = $('status'), t = $('statustxt');
  st.className = 'status' + (k === 'live' ? ' live' : k === 'bad' ? ' bad' : '');
  t.textContent = k === 'live' ? (S && S.status === 'running' ? 'en vivo' : 'mesa abierta') : k === 'bad' ? 'la mesa no responde' : k === 'retry' ? 'reconectando…' : 'mesa libre';
}
function connect(){
  if(es) es.close();
  try {
    es = new EventSource(API + '/events?' + qs(), {withCredentials:true});
    es.onmessage = m => { try { applySnapshot(JSON.parse(m.data)); } catch(e){} };
    es.onerror = () => { if(S) setStatus('retry'); };
  } catch(e) {}
}
function poll(){
  fetch(API + '/snapshot?' + qs(), {credentials:'include', cache:'no-store'})
    .then(r => r.json()).then(d => { connOk = true; applySnapshot(d); })
    .catch(() => { connOk = false; setStatus('bad'); });
}
function startGame(){
  const b = $('startbtn'); if(b) b.disabled = true;
  if(S && S.status === 'running' && !confirm('¿Empezar una vaca nueva? La actual se pierde.')){ if(b) b.disabled = false; return; }
  post('/api/new', {}).then(d => {
    if(!d.ok){ NOTE = d.error || 'no se pudo abrir la mesa'; centerSig = null; render(); if(b) b.disabled = false; return; }
    if(d.sid){ SID = d.sid; store.set('mus_sid', SID); }
    if(d.token){ TOKEN = d.token; store.set('mus_token', TOKEN); }
    NOTE = d.message || '';
    store.set('mus.game', (SID || 'local') + ':' + Date.now());
    lastVersion = -1; feedLast = -1; animLast = null; lastRevealHand = null; recap = null; S = null; prevSnap = null;
    $('feed').replaceChildren(); centerSig = null;
    if(NOTE) $('feed').appendChild(el('div', 'r sys hot', '<span class="tx">' + esc(NOTE) + '</span>'));
    connect(); poll();
  }).catch(() => { NOTE = 'la mesa no responde; prueba en un momento'; centerSig = null; render(); if(b) b.disabled = false; });
}
$('newvaca').onclick = startGame;
$('chatgo').onclick = () => {
  const v = $('chatin').value.trim(); if(!v) return;
  if(!S){ flash('siéntate primero'); return; }
  post('/api/chat', {text:v}).then(d => { if(d.ok) $('chatin').value = ''; else flash(d.error || 'no se pudo decir'); });
};
$('chatin').addEventListener('keydown', e => { if(e.key === 'Enter') $('chatgo').onclick(); });
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tabs button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-selected', String(x === b)); });
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + b.dataset.p));
});
let rsz = null;
addEventListener('resize', () => { clearTimeout(rsz); rsz = setTimeout(() => { Object.values(seatEls).forEach(E => E.sig = null); seatEls.me.hand.querySelectorAll('.mycard').forEach(n => n.remove()); render(); }, 200); });

/* ── results bookkeeping (this browser) ── */
function recordResult(){
  if(!S || S.status !== 'finished' || !S.you) return;
  const gid = store.get('mus.game', null); if(!gid) return;
  const B = store.json('mus.board', {games:[]});
  if(!Array.isArray(B.games)) B.games = [];
  if(B.games.some(g => g.id === gid)) return;
  const va = S.scores.vacas_a, vb = S.scores.vacas_b;
  const us = myTeam() === 0 ? va : vb, them = myTeam() === 0 ? vb : va;
  if(us === them) return;
  B.games.push({id:gid, t:Date.now(), won:us > them, nick:NICK || 'tú',
    rivals:[1,3].map(d => cleanModel(modelKey((mySeat() + d) % 4))), partner:cleanModel(modelKey((mySeat() + 2) % 4))});
  store.set('mus.board', JSON.stringify(B));
}

/* ═════════ VIEWS ═════════ */
const VIEWS = {mesa:'mesa', reglamento:'reglamento', guia:'reglamento', clasificacion:'clasificacion'};
function route(){
  const v = VIEWS[location.hash.replace('#', '')] || 'mesa';
  document.querySelectorAll('.view').forEach(s => s.classList.toggle('on', s.id === v));
  document.querySelectorAll('nav.views a[data-v]').forEach(a => a.classList.toggle('on', a.dataset.v === v));
  if(v === 'reglamento'){ buildGuide(); tickGuide(); }
  if(v === 'clasificacion') renderBoards();
  window.scrollTo(0, 0);
  document.title = v === 'mesa' ? 'Mus — la mesa' : v === 'reglamento' ? 'Mus — reglamento' : 'Mus — clasificación';
}
addEventListener('hashchange', route);

/* ── reglamento demos (ticks every 1.6 s while visible) ── */
const DEMO_NAMES = ['tú', 'glm5.3-flash', 'qwen3.8-flash', 'deepseek-v4-flash'];
function demoNames(){ return S ? [0,1,2,3].map(d => displayName((mySeat() + d) % 4)) : DEMO_NAMES; }
let G = null, gT = 0;
function buildGuide(){
  if(G) return;
  G = {};
  const fan = $('fan');
  [['espadas',1,34,30,-12,0],['bastos',1,22,60,-4,120],['copas',2,10,60,5,240],['espadas',3,0,26,13,360]].forEach(h => {
    const w = el('div'); w.style.right = h[2] + '%'; w.style.bottom = h[3] + 'px'; w.style.transform = 'rotate(' + h[4] + 'deg)';
    const c = cardNode({s:h[0], r:h[1]}, innerWidth < 720 ? 120 : 170, 'deal'); c.style.animationDuration = '1s'; c.style.animationDelay = h[5] + 'ms';
    w.appendChild(c); fan.appendChild(w);
  });
  const dk = $('d-deck'); G.deck = RANKS.map((r, i) => {
    const w = el('div', 'mv'); w.style.left = (2 + i * 8.6) + '%'; w.style.top = (80 + Math.abs(i - 4.5) * 6) + 'px'; w.style.transform = 'rotate(' + ((i - 4.5) * 5) + 'deg)';
    const n = cardNode({s:'oros', r}, innerWidth < 720 ? 74 : 104); w.appendChild(n); dk.appendChild(w); return n;
  });
  G.mus = [0,1,2,3].map(() => { const w = el('div', 'mv'); const n = cardNode({s:'oros', r:1}, innerWidth < 720 ? 72 : 110); w.appendChild(n); $('d-mus').appendChild(w); return {w, n}; });
  G.gc = [0,1].map(() => {
    const row = el('div', 'gcrow'); const lbl = el('div', 'lbl'); const tr = el('div', 'track'); row.append(lbl, tr); $('d-gc').appendChild(row);
    return {row, lbl, cards:[0,1,2,3].map(() => { const w = el('div', 'mv'); const n = cardNode({s:'oros', r:1}, innerWidth < 720 ? 48 : 66); w.appendChild(n); tr.appendChild(w); return {w, n}; })};
  });
  G.pares = [0,1,2,3].map(() => { const w = el('div', 'mv'); w.style.borderRadius = '8px'; const n = cardNode({s:'oros', r:1}, innerWidth < 720 ? 72 : 110); w.appendChild(n); $('d-pares').appendChild(w); return {w, n}; });
  G.juego = [['oros',12],['copas',10],['espadas',7],['bastos',4]].map(c => { const w = el('div', 'mv'); w.appendChild(cardNode({s:c[0], r:c[1]}, innerWidth < 720 ? 58 : 86)); $('d-juego').appendChild(w); return {w, c}; });
  G.ladder = [31,32,40,39,38,37,36,35,34,33].map(v => { const d = el('div', '', String(v)); $('d-ladder').appendChild(d); return {d, v}; });
  G.dots = Array.from({length:40}, (_, i) => { const d = el('i'); d.style.transitionDelay = (i * 8) + 'ms'; $('d-dots').appendChild(d); return d; });
  G.envStep = -1;
  if(S && S.senas_vocab) buildSenaGuide(S.senas_vocab);
  else buildSenaGuide({'muerde-el-labio-inferior':'dos reyes (para Grande)','saca-la-punta-de-la-lengua':'dos ases (para Chica)','torcer-los-labios':'medias (tres iguales)','elevar-las-cejas':'duples','guinar-el-ojo':'tengo 31','cerrar-los-ojos':'ciego: ni pares ni juego'});
}
function tickGuide(){
  if(!G || !$('reglamento').classList.contains('on')) return;
  const t = gT, n = demoNames();
  const suit = SUITS[Math.floor(t / 2) % 4];
  G.deck.forEach((node, i) => setCard(node, {s:suit.id, r:RANKS[i]}));
  $('d-suit').textContent = suit.es; $('d-pinta').textContent = suit.pinta === 0 ? 'sin pintas' : suit.pinta + (suit.pinta === 1 ? ' pinta' : ' pintas');

  const mp = t % 3, orig = [['espadas',5],['copas',4],['bastos',12],['oros',12]], fresh = [['oros',3],['espadas',6]];
  G.mus.forEach((m, i) => { const o = i < 2, c = mp === 2 && o ? fresh[i] : orig[i];
    setCard(m.n, {s:c[0], r:c[1]}); m.w.style.transform = 'translateY(' + (mp === 1 && o ? -40 : 0) + 'px)'; m.w.style.opacity = mp === 1 && o ? .25 : 1; });
  $('d-muscap').textContent = ['Cuatro cartas. Todos dicen mus.', 'Se tiran el cinco y el cuatro.', 'Entra un tres: ya son tres reyes.'][mp];

  const grande = t % 2 === 0, decide = grande ? 1 : 0;
  const A = [['oros',12],['copas',11],['bastos',6],['espadas',4]], B = [['copas',12],['espadas',10],['espadas',5],['bastos',1]];
  $('d-gctitle').textContent = grande ? 'Grande · gana la más alta' : 'Chica · gana la más baja';
  const step = innerWidth < 720 ? 54 : 76;
  [[A, n[1], grande], [B, n[3], !grande]].forEach((row, ri) => {
    const R = G.gc[ri], f = family(row[1]);
    const lbl = iconImg(row[1], 18) + '<span>' + esc(row[1]) + '</span>';
    if(R.lbl.dataset.k !== lbl){ R.lbl.dataset.k = lbl; R.lbl.innerHTML = lbl; R.lbl.style.color = f.color; }
    R.row.style.opacity = row[2] ? 1 : .32;
    const sorted = row[0].slice().sort((x, y) => grande ? gv(y[1]) - gv(x[1]) : gv(x[1]) - gv(y[1]));
    row[0].forEach((c, i) => { const pos = sorted.indexOf(c), C = R.cards[i];
      setCard(C.n, {s:c[0], r:c[1]}); C.w.style.left = (pos * step) + 'px'; C.w.style.transform = 'translateY(' + (pos === decide ? -10 : 0) + 'px)';
      C.w.style.boxShadow = pos === decide && row[2] ? '0 0 0 1.5px var(--color-accent-300)' : 'none'; });
  });

  const PX = [
    {h:[['copas',11],['oros',11],['bastos',6],['espadas',2]], m:[0,1], l:'Par', p:'una piedra'},
    {h:[['oros',7],['copas',7],['espadas',7],['bastos',10]], m:[0,1,2], l:'Medias', p:'dos piedras'},
    {h:[['oros',12],['espadas',3],['bastos',1],['copas',1]], m:[0,1,2,3], l:'Duples', p:'tres piedras — el tres cuenta como rey'}][t % 3];
  G.pares.forEach((P, i) => { const on = PX.m.includes(i); setCard(P.n, {s:PX.h[i][0], r:PX.h[i][1]});
    P.w.style.transform = 'translateY(' + (on ? -18 : 0) + 'px)'; P.w.style.boxShadow = on ? '0 0 0 1.5px var(--color-accent-300)' : 'none'; });
  $('d-plab').textContent = PX.l; $('d-ppts').textContent = PX.p;

  const shown = Math.min(t % 6, 4); let sum = 0;
  G.juego.forEach((J, i) => { if(i < shown) sum += jv(J.c[1]); J.w.style.opacity = i < shown ? 1 : .06; J.w.style.transform = 'translateY(' + (i < shown ? 0 : 14) + 'px)'; });
  $('d-jsum').textContent = sum; $('d-jsum').style.color = sum === 31 ? 'var(--color-accent-200)' : 'var(--color-text)';
  G.ladder.forEach(L => L.d.classList.toggle('on', L.v === sum));

  const ES = [{s:1,text:'paso',stake:0,lab:'en juego'},{s:2,text:'envido',stake:2,lab:'piedras'},{s:3,text:'y yo · dos más',stake:4,lab:'piedras'},
    {s:2,text:'órdago',stake:40,lab:'la vaca'},{s:1,text:'no quiero',stake:4,lab:'para nosotros'}];
  const es2 = t % 6 === 5 ? 4 : t % 6;
  if(es2 !== G.envStep){
    const L = $('d-envlines');
    if(es2 === 0 || es2 < G.envStep) L.replaceChildren();
    for(let i = Math.max(0, L.childElementCount); i <= es2; i++){
      const e = ES[i], nm = n[e.s];
      L.appendChild(el('div', '', iconImg(nm, 16) + '<span class="w" style="color:' + family(nm).color + '">' + esc(nm) + '</span><span class="t">' + esc(e.text) + '</span>'));
    }
    G.envStep = es2;
  }
  $('d-stake').textContent = ES[es2].stake; $('d-stakelab').textContent = ES[es2].lab;
  G.dots.forEach((d, i) => d.classList.toggle('on', i < ES[es2].stake));
}
setInterval(() => { gT++; tickGuide(); }, 1600);

/* ── clasificación ── */
let bench = null, benchTried = false;
function loadBench(){
  if(benchTried) return Promise.resolve(bench); benchTried = true;
  const viaApi = fetch(API + '/api/results', {cache:'no-store'}).then(r => r.json()).then(d => (d && d.leaderboard && d.leaderboard.length) ? d : Promise.reject());
  return viaApi.catch(() => fetch(BENCH_URL, {cache:'no-store'}).then(r => r.json()))
    .then(d => { bench = d; return d; }).catch(() => null);
}
function tableHTML(title, rows, emptyMsg){
  let h = '<div class="hd"><span></span><span>' + esc(title) + '</span><span>G</span><span>P</span><span>±</span></div>';
  if(!rows.length) return h + '<div class="empty">' + esc(emptyMsg) + '</div>';
  rows.forEach((r, i) => {
    const bal = r.w - r.l, tot = r.w + r.l, pct = tot ? Math.round(r.w / tot * 100) : 0;
    h += '<div class="rw" style="animation-delay:' + (i * 50) + 'ms"><span class="rk">' + (i + 1) + '</span><div class="nmc"><div class="top">' + (r.icon || '') +
      '<span class="n" style="color:' + r.color + '">' + esc(r.name) + '</span></div><div class="bar"><i style="width:' + pct + '%;background:' + r.bar + '"></i></div></div>' +
      '<span class="num">' + r.w + '</span><span class="num muted">' + r.l + '</span><span class="num" style="color:' + (bal > 0 ? 'var(--color-text)' : 'var(--color-neutral-500)') + '">' + (bal > 0 ? '+' : '') + bal + '</span></div>';
  });
  return h;
}
function renderBoards(){
  // tus vacas: overall + per rival model, from this browser
  const B = store.json('mus.board', {games:[]}), games = Array.isArray(B.games) ? B.games : [];
  const you = [], per = {};
  if(games.length){
    const w = games.filter(g => g.won).length;
    you.push({name:(NICK || 'tú') + ' · total', w, l:games.length - w, color:'var(--color-accent-200)', bar:'var(--color-accent-400)', icon:''});
    games.forEach(g => (g.rivals || []).forEach(m => { const a = per[m] = per[m] || {w:0, l:0}; if(g.won) a.w++; else a.l++; }));
    Object.entries(per).sort((a, b) => (b[1].w - b[1].l) - (a[1].w - a[1].l)).forEach(([m, a]) => {
      const f = family(m); you.push({name:'contra ' + m, w:a.w, l:a.l, color:f.color, bar:f.color, icon:iconImg(m, 18)});
    });
  }
  $('b-you').innerHTML = tableHTML('Tus vacas', you, 'Aún no has terminado ninguna vaca. Siéntate a la mesa.');
  $('b-models').innerHTML = tableHTML('Modelos entre ellos', [], 'cargando…');
  loadBench().then(d => {
    const rows = ((d && d.leaderboard) || []).map(k => { const nm = cleanModel(k.model), f = family(nm);
      return {name:nm, w:k.vacas_for || 0, l:k.vacas_against || 0, color:f.color, bar:f.color, icon:iconImg(nm, 18)}; })
      .sort((a, b) => (b.w - b.l) - (a.w - a.l) || b.w - a.w);
    $('b-models').innerHTML = tableHTML('Modelos entre ellos', rows, 'Sin resultados del benchmark disponibles.');
    const when = d && d.generated ? new Date(d.generated).toLocaleDateString('es-ES', {day:'numeric', month:'long', year:'numeric'}) : '';
    $('b-note').innerHTML = (d && rows.length ? 'Modelos: vacas ganadas y perdidas en el benchmark' + (d.rules ? ' (' + esc(d.rules) + ')' : '') + (when ? ', ' + esc(when) : '') + '. ' : '') +
      'Tus vacas se guardan sólo en este navegador. <a href="https://diegoatencia.dev/blog/mus-against-the-machine.html">Cómo se midió →</a>';
  });
}

/* ── footer ── */
document.querySelectorAll('[data-foot]').forEach(f => f.innerHTML =
  'Naipes de <a href="https://github.com/gjenkins20/spanish-playing-cards-svg">spanish-playing-cards-svg</a> sobre arte de ' +
  '<a href="https://commons.wikimedia.org/wiki/Category:Spanish_playing_cards">Basquetteur</a> (CC BY-SA 3.0). ' +
  'Rivales jugados por modelos de lenguaje · <a href="https://diegoatencia.dev/blog/mus-against-the-machine.html">el benchmark</a>.');

/* ── boot ── */
route();
render();
connect();
poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""
