// Sign in by typing the code from the email, on the page that asked for it. Work email filters sometimes
// block or pre-open sign-in links; a typed code needs no link at all. Used after every "Check your email" message.
window.bsCode = function (after, email, extra) {
  const box = document.createElement("div");
  box.className = "codebox";
  box.innerHTML =
    '<p class="fine">Or type the code from the email:</p>' +
    '<form class="savef"><input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="12" required ' +
    'placeholder="Code" aria-label="Sign-in code from the email"><button>Sign in</button></form>' +
    '<p class="fine err" hidden></p>';
  const f = box.querySelector("form"), err = box.querySelector(".err"), btn = f.querySelector("button");
  f.onsubmit = async (e) => {
    e.preventDefault();
    btn.disabled = true;
    err.hidden = true;
    const r = await fetch("/api/auth/code", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ email: email, code: f.code.value }, extra || {})),
    });
    const k = await r.json().catch(() => ({}));
    if (r.ok) { location.href = k.redirect || (extra && extra.back) || location.pathname; return; }
    btn.disabled = false;
    err.textContent = k.error || "That code didn't work.";
    err.hidden = false;
  };
  after.insertAdjacentElement("afterend", box);
  return box;
};
