(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---------- copy buttons ---------- */
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var ta = el("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy") ? resolve() : reject(new Error("copy failed")); }
      catch (e) { reject(e); }
      document.body.removeChild(ta);
    });
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy-target]");
    if (!btn) return;
    var target = document.getElementById(btn.getAttribute("data-copy-target"));
    if (!target) return;
    var label = btn.textContent;
    copyText(target.textContent.trim()).then(function () {
      btn.textContent = "Copied";
      btn.classList.add("done");
    }, function () {
      btn.textContent = "Press ⌘C";
    }).then(function () {
      setTimeout(function () { btn.textContent = label; btn.classList.remove("done"); }, 1400);
    });
  });

  /* ---------- nav ---------- */
  var toggle = document.querySelector(".nav-toggle");
  var menu = document.getElementById("nav-menu");
  function setMenu(open) {
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    menu.classList.toggle("open", open);
  }
  toggle.addEventListener("click", function () { setMenu(toggle.getAttribute("aria-expanded") !== "true"); });
  menu.addEventListener("click", function (e) { if (e.target.closest("a")) setMenu(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setMenu(false); });

  if ("IntersectionObserver" in window) {
    var navLinks = {};
    document.querySelectorAll('.nav-links a[href^="#"]').forEach(function (a) { navLinks[a.getAttribute("href").slice(1)] = a; });
    var secObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var a = navLinks[en.target.id];
        if (a && en.isIntersecting) {
          Object.keys(navLinks).forEach(function (k) { navLinks[k].removeAttribute("aria-current"); });
          a.setAttribute("aria-current", "true");
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    Object.keys(navLinks).forEach(function (id) { var s = document.getElementById(id); if (s) secObs.observe(s); });
  }

  /* ---------- recipes ---------- */
  var RECIPES = [
    { name: "build-watcher", icon: "🛠️", color: "coral", src: ["screen"], desc: "Says it out loud the moment a CI build or deploy on screen fails or passes.", rules: ["build-failed", "build-passed"] },
    { name: "done-yet", icon: "⏳", color: "gold", src: ["screen"], desc: "Pings you when a download, render, export, install or test run finishes, then exits.", rules: ["task-finished"] },
    { name: "focus-guard", icon: "🧘", color: "mint", src: ["screen"], desc: "A gentle nudge when you drift onto social feeds or a video binge during focus time.", rules: ["doomscrolling", "video-binge"] },
    { name: "doorbell", icon: "🚪", color: "forest", src: ["camera", "url"], desc: "Person at the door or a parcel left behind, pushed to your phone with the photo.", rules: ["person-at-door", "parcel-left"] },
    { name: "print-failure", icon: "🍝", color: "coral", src: ["camera"], desc: "Catches 3D print spaghetti with an urgent push (plus an OctoPrint pause example).", rules: ["spaghetti", "print-finished"] },
    { name: "kitchen", icon: "🍳", color: "gold", src: ["camera"], desc: "A kitchen timer that actually looks: water boiling, pot boiling over, smoke.", rules: ["boiling", "boiling-over", "smoke"] },
    { name: "pet-patrol", icon: "🐕", color: "mint", src: ["camera"], desc: "Catches the dog on the sofa or the cat on the counter and tells them off.", rules: ["dog-on-sofa", "cat-on-counter"] },
    { name: "meeting-radar", icon: "👂", color: "forest", src: ["mic"], desc: "Zoned out on a call? Buzzes you when someone says your name or asks you something.", rules: ["name-called", "question-for-me", "action-item"] },
    { name: "baby-monitor", icon: "👶", color: "coral", src: ["camera", "mic"], desc: "Crying, standing up in the cot, or face covered, with urgent pushes.", rules: ["crying", "standing-up", "face-covered"] }
  ];
  var SRC_CHIP = { screen: "coral", camera: "mint", url: "ghost", mic: "gold" };

  var grid = document.getElementById("recipe-grid");
  RECIPES.forEach(function (r) {
    var tags = r.src.map(function (s) { return '<span class="chip ' + SRC_CHIP[s] + '">' + s + "</span>"; }).join("");
    var rules = r.rules.map(function (x) { return "<span>" + x + "</span>"; }).join("");
    var id = "run-" + r.name;
    grid.appendChild(el("article", { "class": "recipe" },
      '<div class="recipe-top"><span class="ricon ' + r.color + '" aria-hidden="true">' + r.icon + '</span><div class="tags">' + tags + "</div></div>" +
      "<h3>" + r.name + "</h3><p>" + esc(r.desc) + '</p><div class="rules" aria-label="Rules">' + rules + "</div>" +
      '<div class="run"><code id="' + id + '">ifseen watch ' + r.name + '</code><button class="copy" type="button" data-copy-target="' + id + '" aria-label="Copy command for ' + r.name + '">Copy</button></div>'
    ));
  });

  /* ---------- example rule cards ---------- */
  var CARDS = [
    { rule: "spaghetti", recipe: "print-failure", icon: "🍝", color: "coral", thr: 0.85, n: 3, cd: "15m", src: "camera", bar: "var(--coral)", when: 'The 3D print has failed - a tangled mess of loose filament ("spaghetti"), a print knocked off the bed, or the nozzle printing into thin air.', then: ["ntfy", "urgent push"] },
    { rule: "name-called", recipe: "meeting-radar", icon: "👂", color: "gold", thr: 0.75, n: 1, cd: "20s", src: "mic", bar: "var(--gold)", when: 'Someone in the audio says the name "${MY_NAME:-Alex}" or addresses that person directly.', then: ["notify", "say: heads up"] },
    { rule: "face-covered", recipe: "baby-monitor", icon: "👶", color: "mint", thr: 0.7, n: 2, cd: "1m", src: "camera + mic", bar: "var(--mint)", when: "A blanket, toy or pillow is covering the baby's face.", then: ["ntfy", "\u201cCheck on the baby\u201d"] },
    { rule: "doomscrolling", recipe: "focus-guard", icon: "🧘", color: "mint", thr: 0.8, n: 3, cd: "10m", src: "screen", bar: "var(--mint)", when: "The screen is mostly showing a social media feed or short-form video (X/Twitter, Instagram, TikTok, Reddit, YouTube Shorts, Facebook).", then: ["say", "back to work"] },
    { rule: "boiling-over", recipe: "kitchen", icon: "🍳", color: "gold", thr: 0.75, n: 1, cd: "2m", src: "camera", bar: "var(--gold)", when: "A pot is boiling over, or liquid is spilling onto the hob.", then: ["say", "pot boiling over"] },
    { rule: "dog-on-sofa", recipe: "pet-patrol", icon: "🐕", color: "coral", thr: 0.85, n: 2, cd: "2m", src: "camera", bar: "var(--coral)", when: "A dog is on the sofa or couch.", then: ["shell", "play \u201coff the sofa\u201d + snapshot"] }
  ];
  var QUOTE = '<svg viewBox="0 0 24 24" fill="#1A3C2B" aria-hidden="true"><path d="M3 6h7v7H6.5c0 2 1.2 3.3 3.5 3.5V19c-4.4 0-7-2.6-7-7V6zm11 0h7v7h-3.5c0 2 1.2 3.3 3.5 3.5V19c-4.4 0-7-2.6-7-7V6z"/></svg>';
  var cards = document.getElementById("rule-cards");
  CARDS.forEach(function (c) {
    var hits = "";
    for (var i = 0; i < 5; i++) hits += '<b class="' + (i < c.n ? "on" : "") + '"></b>';
    cards.appendChild(el("article", { "class": "card" },
      '<div class="card-top">' + QUOTE + '<span class="hits" aria-label="for: ' + c.n + ' consecutive hits">' + hits + "&nbsp;FOR " + c.n + "</span></div>" +
      "<blockquote>when: " + esc(c.when) + '<span class="then">then: <b>' + esc(c.then[0]) + "</b> " + esc(c.then[1]) + "</span>" +
      '<span class="kv"><span>source</span><b>' + c.src + '</b><span>threshold</span><b>' + c.thr + '</b><span>for</span><b>' + c.n + '</b><span>cooldown</span><b>' + c.cd + "</b></span>" +
      '<span class="tbar" aria-hidden="true"><i style="width:' + c.thr * 100 + "%;background:" + c.bar + '"></i><span style="left:' + c.thr * 100 + '%"></span></span></blockquote>' +
      '<div class="card-foot"><span class="av ricon ' + c.color + '" aria-hidden="true">' + c.icon + '</span><span class="who">' + c.rule +
      "<span>" + c.recipe + " · threshold " + Math.round(c.thr * 100) + "%</span></span></div>"
    ));
  });

  /* ---------- cost meter ticks ---------- */
  var ticks = document.getElementById("ticks");
  "sssccsssssscccfsssssscsssscsss".split("").forEach(function (t) {
    ticks.appendChild(el("i", { "class": t === "s" ? "" : t }));
  });

  /* ---------- benchmark bars ---------- */
  var barGroups = document.querySelectorAll("[data-bars]");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    barGroups.forEach(function (b) { b.classList.add("in"); });
  } else {
    var barObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add("in"); barObs.unobserve(en.target); } });
    }, { threshold: 0.4 });
    barGroups.forEach(function (b) { barObs.observe(b); });
  }

  /* ---------- live simulation ---------- */
  var SIM_RULES = [
    { name: "person-at-door", when: "A person is standing at or walking up to the front door.", thr: 0.8, n: 2 },
    { name: "parcel-left", when: "A parcel, box or delivery bag has been left on the doorstep.", thr: 0.85, n: 3 },
    { name: "dog-at-door", when: "A dog is on the doorstep.", thr: 0.8, n: 2 }
  ];
  var ACTIONS = { "person-at-door": "ntfy + snapshot", "parcel-left": "ntfy “📦 Parcel delivered”", "dog-at-door": "say “someone's visiting”" };
  var TIMELINE = [
    [0.02, 0.03, 0.04], null, null,
    [0.41, 0.02, 0.03], [0.88, 0.04, 0.03], [0.93, 0.31, 0.02], [0.9, 0.62, 0.02],
    [0.22, 0.91, 0.03], [0.04, 0.94, 0.02], [0.03, 0.97, 0.03], null, null,
    [0.03, 0.96, 0.71], [0.02, 0.95, 0.86], [0.02, 0.96, 0.91], [0.02, 0.95, 0.12],
    null, null, [0.03, 0.12, 0.05], null, null
  ];
  var COST_PER_CALL = 520 * 0.10 / 1e6;
  var probsEl = document.getElementById("probs");
  var logEl = document.getElementById("sim-log");
  var frameEl = document.getElementById("sim-frame");
  var stateEl = document.getElementById("sim-state");
  var costEl = document.getElementById("sim-cost");

  var rows = SIM_RULES.map(function (r) {
    var li = el("li", { "class": "prob" });
    var streak = "";
    for (var i = 0; i < r.n; i++) streak += "<b></b>";
    li.innerHTML =
      '<div class="meta"><span class="name">' + r.name + '<span class="when">' + esc(r.when) + '</span></span><span class="pct">0%</span></div>' +
      '<div class="track"><span class="fill"></span><span class="thr" style="left:' + r.thr * 100 + '%" data-t="' + Math.round(r.thr * 100) + '%"></span><span class="streak">' + streak + "</span></div>";
    probsEl.appendChild(li);
    return { li: li, fill: li.querySelector(".fill"), pct: li.querySelector(".pct"), dots: li.querySelectorAll(".streak b") };
  });

  var state, frame = 0, step = 0, cost = 0;
  function resetState() { state = SIM_RULES.map(function () { return { streak: 0, armed: true, p: 0 }; }); }
  resetState();

  function clock(f) {
    var s = 14 * 3600 + 2 * 60 + f * 2;
    function p(x) { return (x < 10 ? "0" : "") + x; }
    return p(Math.floor(s / 3600) % 24) + ":" + p(Math.floor(s / 60) % 60) + ":" + p(s % 60);
  }
  function log(cls, html) {
    logEl.appendChild(el("li", { "class": cls }, html));
    while (logEl.children.length > 14) logEl.removeChild(logEl.firstChild);
  }
  function render() {
    SIM_RULES.forEach(function (r, i) {
      var s = state[i], row = rows[i];
      row.fill.style.width = (s.p * 100).toFixed(1) + "%";
      row.pct.textContent = (s.p * 100).toFixed(1) + "%";
      row.fill.classList.toggle("hit", s.armed && s.p >= r.thr);
      row.fill.classList.toggle("fired", !s.armed && s.p >= r.thr - 0.15);
      row.dots.forEach(function (d, k) { d.classList.toggle("on", k < s.streak); });
    });
    costEl.textContent = "$" + cost.toFixed(6);
    frameEl.textContent = "frame #" + String(frame).padStart(4, "0");
  }

  function tick() {
    var probs = TIMELINE[step];
    var t = '<span class="t">' + clock(frame) + "</span> ";
    if (!probs) {
      stateEl.textContent = "skipped";
      stateEl.className = "chip ghost";
      log("skp", t + "skip  frame unchanged");
    } else {
      stateEl.textContent = "1 call · 3 rules";
      stateEl.className = "chip gold";
      cost += COST_PER_CALL;
      var parts = [];
      var fires = [];
      SIM_RULES.forEach(function (r, i) {
        var s = state[i];
        s.p = probs[i];
        if (s.p >= r.thr) {
          if (s.armed) {
            s.streak++;
            if (s.streak >= r.n) { fires.push(i); s.armed = false; s.streak = 0; }
          }
        } else {
          s.streak = 0;
          if (s.p < r.thr - 0.15) s.armed = true;
        }
        if (s.p > 0.3) parts.push(r.name + ' <span class="p">' + Math.round(s.p * 100) + "%</span>");
      });
      log("dec", t + "decide " + (parts.length ? parts.join(" · ") : "all &lt; 30%"));
      fires.forEach(function (i) {
        var r = SIM_RULES[i];
        log("fire", t + "🔔 FIRED " + r.name + " " + Math.round(state[i].p * 100) + "%");
        log("act", t + "→ " + esc(ACTIONS[r.name]));
      });
    }
    render();
    frame++;
    step++;
    if (step >= TIMELINE.length) { step = 0; resetState(); }
  }

  if (reduceMotion) {
    for (var k = 0; k < 10; k++) tick();
  } else {
    tick();
    var timer = null;
    var simEl = document.getElementById("sim");
    var start = function () { if (!timer) timer = setInterval(tick, 1100); };
    var stop = function () { clearInterval(timer); timer = null; };
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { en.isIntersecting ? start() : stop(); });
      }).observe(simEl);
    } else {
      start();
    }
  }

  /* ---------- rule builder ---------- */
  var form = document.getElementById("rule-form");
  var fWhen = document.getElementById("f-when");
  var fSrc = document.getElementById("f-src");
  var fSrcLabel = document.getElementById("f-src-label");
  var srcWrap = document.getElementById("src-extra-wrap");
  var fAct = document.getElementById("f-act");
  var fActLabel = document.getElementById("f-act-label");
  var actWrap = document.getElementById("act-extra-wrap");
  var fThr = document.getElementById("f-thr");
  var fFor = document.getElementById("f-for");
  var fEvery = document.getElementById("f-every");
  var micWarn = document.getElementById("mic-warn");
  var outCli = document.getElementById("out-cli");
  var outYaml = document.getElementById("out-yaml");

  var SRC_CFG = {
    screen: { label: "Monitor number (0 = all)", def: "1" },
    camera: { label: "Webcam index or rtsp:// URL", def: "0" },
    url: { label: "Snapshot URL", def: "http://frigate.local/api/door/latest.jpg" },
    mic: null
  };
  var ACT_CFG = {
    notify: null,
    say: { label: "Text to speak", def: "heads up" },
    ntfy: { label: "ntfy topic", def: "my-secret-topic" },
    shell: { label: "Shell command (gets $IFSEEN_* env vars)", def: "./on-trigger.sh" }
  };
  var srcVals = {}, actVals = {};
  var curSrc = form.querySelector('input[name="src"]:checked').value;
  var curAct = form.querySelector('input[name="act"]:checked').value;
  srcVals[curSrc] = fSrc.value;
  actVals[curAct] = fAct.value;

  function slug(text) {
    var base = text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/^-+|-+$/g, "");
    return base || "rule";
  }
  function shq(s) {
    if (s === "") return '""';
    if (/^[A-Za-z0-9_\-.,:\/@%+=]+$/.test(s)) return s;
    if (!/["$`\\!]/.test(s)) return '"' + s + '"';
    return "'" + s.replace(/'/g, "'\\''") + "'";
  }
  function yq(s) {
    s = String(s);
    if (s === "" || /^[\s\-?:,\[\]{}#&*!|>'"%@`]/.test(s) || /\s$/.test(s) || /: |\s#|["\\]/.test(s) ||
        /^(true|false|yes|no|on|off|null|~)$/i.test(s) || /^[-+]?(\d|\.\d)/.test(s)) {
      return JSON.stringify(s);
    }
    return s;
  }
  function clamp(v, lo, hi, d) { v = parseFloat(v); return isNaN(v) ? d : Math.min(hi, Math.max(lo, v)); }

  function syncExtra() {
    var s = SRC_CFG[curSrc];
    srcWrap.hidden = !s;
    if (s) { fSrcLabel.textContent = s.label; fSrc.value = srcVals[curSrc] != null ? srcVals[curSrc] : s.def; }
    var a = ACT_CFG[curAct];
    actWrap.hidden = !a;
    if (a) { fActLabel.textContent = a.label; fAct.value = actVals[curAct] != null ? actVals[curAct] : a.def; }
    micWarn.hidden = curSrc !== "mic";
  }

  function build() {
    var when = fWhen.value.replace(/\s+/g, " ").trim() || "Describe what should be true";
    var sv = fSrc.value.trim() || (SRC_CFG[curSrc] && SRC_CFG[curSrc].def) || "";
    var av = fAct.value.trim() || (ACT_CFG[curAct] && ACT_CFG[curAct].def) || "";
    var thr = Math.round(clamp(fThr.value, 0.05, 0.99, 0.8) * 100) / 100;
    var n = Math.round(clamp(fFor.value, 1, 20, 1));
    var every = fEvery.value;

    var cli = ["ifseen", shq(when)];
    if (curSrc === "screen") cli.push("--screen", shq(sv));
    else if (curSrc === "camera") cli.push("--camera", shq(sv));
    else if (curSrc === "url") cli.push("--url", shq(sv));
    else cli.push("--mic", "--provider", "gemini");
    if (curAct === "notify") cli.push("--notify");
    else if (curAct === "say") cli.push("--say", shq(av));
    else if (curAct === "ntfy") cli.push("--ntfy", shq(av));
    else cli.push("--then", shq(av));
    if (thr !== 0.8) cli.push("--threshold", String(thr));
    if (n !== 1) cli.push("--for", String(n));
    cli.push("--every", every);
    outCli.innerHTML = cli.map(function (t, i) {
      var cls = t.indexOf("--") === 0 ? "nb fl" : (i === 1 ? "st" : "");
      return cls ? '<span class="' + cls + '">' + esc(t) + "</span>" : esc(t);
    }).join(" ");

    var y = [];
    if (curSrc === "screen") y.push(sv === "1" ? "source: screen" : "source:\n  screen: " + yq(sv));
    else if (curSrc === "camera") y.push("source:\n  camera: " + (/^\d+$/.test(sv) ? sv : yq(sv)));
    else if (curSrc === "url") y.push("source:\n  url: " + yq(sv));
    else y.push("source:\n  mic:\n    seconds: 5");
    y.push("every: " + every);
    if (curSrc === "mic") y.push("provider: gemini");
    y.push("rules:");
    y.push("  - name: " + slug(when));
    y.push("    when: " + yq(when));
    y.push("    threshold: " + thr);
    if (n !== 1) y.push("    for: " + n);
    y.push("    then:");
    if (curAct === "notify") y.push("      - notify");
    else y.push("      - " + curAct + ": " + yq(av));
    outYaml.textContent = y.join("\n");
  }

  form.addEventListener("change", function (e) {
    if (e.target.name === "src") { srcVals[curSrc] = fSrc.value; curSrc = e.target.value; syncExtra(); }
    if (e.target.name === "act") { actVals[curAct] = fAct.value; curAct = e.target.value; syncExtra(); }
    build();
  });
  form.addEventListener("input", build);
  form.addEventListener("submit", function (e) { e.preventDefault(); });
  syncExtra();
  build();
})();
