const el = (id) => document.getElementById(id);
const status = (message) => {
  el("status").textContent = message;
};
const projectPath = () => "/api/projects/" + el("project").value;
const bookPath = () => projectPath() + "/manuscripts/" + el("book").value;
let generation = 0;
let busy = false;
let activeJob;
async function api(path, method = "GET", body) {
  const form = body instanceof FormData;
  const response = await fetch(path, {
    method,
    headers: body && !form ? { "Content-Type": "application/json" } : {},
    body: form ? body : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw Object.assign(
      new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Revisa los datos ingresados",
      ),
      { code: response.status },
    );
  return data;
}
function options(id, rows, key, label, selected) {
  const node = el(id);
  node.replaceChildren(...rows.map((row) => new Option(row[label], row[key])));
  if (selected !== undefined) node.value = selected;
}
function screen(active) {
  el("access").hidden = active;
  el("workspace").hidden = el("logout").hidden = !active;
}
async function projects(selected) {
  options("project", await api("/api/projects"), "id", "name", selected);
  screen(true);
  await showPlan();
  await books();
  const slug = location.pathname.split("/").pop();
  if (
    ["proyectos", "suscripcion", "staylo", "manuscript", "publish"].includes(
      slug,
    )
  )
    el(slug)?.scrollIntoView();
}
async function books(selected) {
  const path = projectPath();
  const rows = el("project").value ? await api(path + "/manuscripts") : [];
  if (path !== projectPath()) return;
  options("book", rows, "id", "filename", selected);
  await chapters();
  await loadLayouts();
}
async function chapters() {
  const path = bookPath();
  const rows = el("book").value ? await api(path + "/chapters") : [];
  if (path !== bookPath()) return;
  options("chapter", rows, "index", "title");
  await readChapter();
}
async function readChapter() {
  const current = ++generation;
  clearReview();
  el("corrected").value = "";
  for (const format of ["epub", "docx"]) {
    if (el("book").value) el(format).href = bookPath() + "/export/" + format;
    else el(format).removeAttribute("href");
  }
  const path = bookPath();
  const index = el("chapter").value;
  el("original").textContent =
    el("translation").value =
    el("quality").textContent =
      "";
  el("version").replaceChildren();
  el("translate").disabled = busy || index === "";
  if (index === "") return;
  const [chapter, versions] = await Promise.all([
    api(path + "/chapters/" + index),
    api(path + "/versions"),
  ]);
  if (current !== generation) return;
  el("original").textContent = chapter.text;
  el("corrected").value = chapter.text;
  options(
    "version",
    versions
      .filter((v) => v.chapter_index === Number(index))
      .map((v) => ({ ...v, label: v.created_at })),
    "id",
    "label",
  );
  await readVersion();
}
async function readVersion() {
  const id = el("version").value,
    path = bookPath();
  if (!id) return;
  const data = await api(path + "/versions/" + id);
  if (path === bookPath() && id === el("version").value) {
    el("translation").value = data.translated_text;
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    el("quality").textContent = warnings
      .map((w) => w.message)
      .filter(Boolean)
      .join(" · ");
  }
}
function bind(id, event, action) {
  el(id).addEventListener(event, async (e) => {
    e.preventDefault();
    try {
      await action(e);
    } catch (error) {
      status(error.message);
    }
  });
}
bind("credentials", "submit", async (e) => {
  const credentials = Object.fromEntries(new FormData(e.target));
  const result = await api("/api/" + e.submitter.value, "POST", credentials);
  if (result.verification_required) {
    const mail = await api("/api/mail/request", "POST", {
      email: credentials.email,
      purpose: "verify",
    });
    status(mail.message);
    return;
  }
  e.target.reset();
  await projects();
  status("Sesión iniciada.");
});
bind("logout", "click", async () => {
  await api("/api/logout", "POST");
  location.reload();
});
bind("newProject", "submit", async (e) => {
  const item = await api(
    "/api/projects",
    "POST",
    Object.fromEntries(new FormData(e.target)),
  );
  e.target.reset();
  await projects(item.id);
  status("Proyecto creado.");
});
bind("upload", "submit", async (e) => {
  if (!el("project").value) throw new Error("Crea o elige un proyecto.");
  const item = await api(
    projectPath() + "/manuscripts",
    "POST",
    new FormData(e.target),
  );
  e.target.reset();
  await books(item.id);
  status("Manuscrito importado.");
});
bind("project", "change", () => books());
bind("book", "change", () => chapters());
bind("chapter", "change", readChapter);
bind("version", "change", readVersion);
bind("translate", "click", async () => {
  const path = bookPath(),
    chapter = Number(el("chapter").value),
    job = crypto.randomUUID();
  busy = true;
  el("translate").disabled = true;
  try {
    await api(path + "/translation-jobs", "POST", {
      chapter_index: chapter,
      job_id: job,
    });
    activeJob = path + "/translation-progress/" + job;
    el("jobControls").hidden = false;
    el("progress").hidden = false;
    status("Traducción en curso…");
    while (true) {
      const p = await api(path + "/translation-progress/" + job);
      if (p.state === "failed") throw new Error(p.detail);
      if (p.state === "completed") break;
      if (p.state !== "running")
        throw new Error("El servidor perdió el estado del trabajo.");
      if (p.total) {
        el("progress").max = p.total;
        el("progress").value = p.completed;
      }
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
    await readChapter();
    status("Traducción guardada.");
  } finally {
    activeJob = null;
    el("jobControls").hidden = true;
    busy = false;
    el("translate").disabled = !el("book").value;
    el("progress").hidden = true;
    el("progress").removeAttribute("value");
  }
});
projects().catch((error) => {
  if (error.code !== 401) status(error.message);
});

let reviewId = 0;
let matches = [];
function clearReview() {
  reviewId++;
  matches = [];
  el("findings").replaceChildren();
  el("applyAll").disabled = true;
}
function applyMatch(match, replacement) {
  const input = el("corrected");
  input.value =
    input.value.slice(0, match.offset) +
    replacement +
    input.value.slice(match.offset + match.length);
  const end = match.offset + match.length;
  matches = matches.filter(
    (m) =>
      m !== match && (m.offset + m.length <= match.offset || m.offset >= end),
  );
  for (const m of matches)
    if (m.offset >= end) m.offset += replacement.length - match.length;
}
function renderMatches() {
  const container = el("findings");
  container.replaceChildren();
  for (const match of matches) {
    const row = document.createElement("article");
    row.dataset.group = match.spelling
      ? "spelling"
      : /gram[aá]|concord/i.test(match.category)
        ? "grammar"
        : "other";
    const title = document.createElement("strong");
    title.textContent = match.category + " · " + match.term;
    const hint = document.createElement("p");
    hint.textContent = match.message;
    const locate = document.createElement("button");
    locate.textContent = "Ver en el manuscrito";
    locate.onclick = () => {
      const field = el("corrected");
      field.focus();
      field.setSelectionRange(match.offset, match.offset + match.length);
    };
    row.append(title, hint, locate);
    if (match.choices.length) {
      const choice = document.createElement("select");
      choice.setAttribute("aria-label", "Sugerencia");
      choice.replaceChildren(...match.choices.map((v) => new Option(v, v)));
      const apply = document.createElement("button");
      apply.textContent = "Aplicar esta corrección";
      apply.onclick = () => {
        applyMatch(match, choice.value);
        renderMatches();
      };
      row.append(choice, apply);
    }
    if (match.spelling) {
      const add = document.createElement("button");
      add.textContent = "Agregar al diccionario";
      add.onclick = async () => {
        try {
          const id = reviewId;
          await api(bookPath() + "/dictionary", "POST", { word: match.term });
          if (id !== reviewId) return;
          matches = matches.filter(
            (m) =>
              !(
                m.spelling &&
                m.term.toLocaleLowerCase() === match.term.toLocaleLowerCase()
              ),
          );
          renderMatches();
          status("Palabra guardada.");
        } catch (error) {
          status(error.message);
        }
      };
      row.append(add);
    }
    container.append(row);
  }
  el("applyAll").disabled = !matches.some((m) => m.choices.length);
}
el("corrected").addEventListener("input", clearReview);
bind("review", "click", async () => {
  if (!el("book").value) throw new Error("Importa un manuscrito.");
  clearReview();
  const id = reviewId,
    text = el("corrected").value,
    found = [];
  for (let start = 0; start < text.length; ) {
    let end = Math.min(text.length, start + 4500);
    if (end < text.length) {
      const boundary = Math.max(
        text.lastIndexOf("\n", end - 1),
        text.lastIndexOf(" ", end - 1),
      );
      if (boundary > start + 2000) end = boundary + 1;
      else if (
        text.charCodeAt(end - 1) >= 0xd800 &&
        text.charCodeAt(end - 1) <= 0xdbff
      )
        end--;
    }
    const rows = await api(bookPath() + "/review", "POST", {
      text: text.slice(start, end),
    });
    if (id !== reviewId) return;
    for (const row of rows) found.push({ ...row, offset: start + row.offset });
    start = end;
    status(
      "Análisis del capítulo · " +
        Math.round((100 * start) / text.length) +
        "%",
    );
  }
  matches = found;
  renderMatches();
  status(matches.length + " observaciones.");
});
bind("applyAll", "click", () => {
  for (const match of [...matches].reverse())
    if (match.choices.length && matches.includes(match))
      applyMatch(match, match.choices[0]);
  renderMatches();
});
bind("saveCorrected", "click", async () => {
  if (!el("book").value) throw new Error("Importa un manuscrito.");
  const result = await api(bookPath() + "/corrected", "POST", {
    chapter: Number(el("chapter").value),
    text: el("corrected").value,
  });
  await books(result.id);
  status("Nueva versión guardada. El original sigue disponible.");
});

async function showPlan() {
  const sub = await api("/api/subscription");
  el("checkout").hidden = !sub.checkout_enabled;
  el("plan").textContent =
    sub.plan +
    " · vigente hasta " +
    new Date(sub.expires * 1000).toLocaleDateString("es-MX");
}
bind("subscribe", "click", async () => {
  await api("/api/subscription/simulate", "POST", {
    event: crypto.randomUUID(),
    plan: el("planChoice").value,
  });
  await showPlan();
  status("Plan simulado activado. Importe cobrado: $0.");
});

for (const button of el("jobControls").querySelectorAll("button")) {
  button.onclick = async () => {
    try {
      await api(activeJob + "/control", "PUT", {
        action: button.dataset.action,
      });
      status("Solicitud recibida: " + button.textContent);
    } catch (error) {
      status(error.message);
    }
  };
}
bind("saveTranslation", "click", async () => {
  const version = el("version").value;
  if (!version) throw new Error("Selecciona una versión traducida.");
  await api(bookPath() + "/versions/" + version + "/revisions", "POST", {
    translated_text: el("translation").value,
  });
  await readChapter();
  status("Revisión guardada.");
});
bind("prepareTranslation", "click", async () => {
  const version = el("version").value;
  if (!version) throw new Error("Selecciona una versión traducida.");
  const item = await api(
    bookPath() + "/versions/" + version + "/prepare",
    "POST",
  );
  await books(item.id);
  location.hash = "publish";
  status("Capítulo guardado como manuscrito en inglés.");
});

bind("forgot", "click", async () => {
  const email = el("credentials").elements.email.value;
  if (!email) throw new Error("Introduce tu correo.");
  status(
    (await api("/api/mail/request", "POST", { email, purpose: "reset" }))
      .message,
  );
});
const mailParams = new URLSearchParams(location.hash.slice(1));
if (mailParams.has("token")) {
  history.replaceState(null, "", location.pathname);
  el("redeem").hidden = false;
  el("newPassword").hidden = mailParams.get("action") !== "reset";
}
bind("redeemForm", "submit", async (e) => {
  const password = e.target.elements.password.value;
  const result = await api("/api/mail/redeem", "POST", {
    token: mailParams.get("token"),
    password: password || null,
  });
  e.target.reset();
  el("redeem").hidden = true;
  mailParams.delete("token");
  status(result.message);
});
let pendingOrder;
bind("checkout", "click", async () => {
  const plan = el("planChoice").value;
  if (!pendingOrder || pendingOrder.plan !== plan)
    pendingOrder = { plan, order_id: crypto.randomUUID() };
  const session = await api("/api/checkout", "POST", pendingOrder);
  const url = new URL(session.url);
  if (url.origin !== "https://checkout.stripe.com")
    throw new Error("Sesión de Stripe inválida.");
  location.assign(url.href);
});

function pdfLink() {
  if (el("layout").value)
    el("pdf").href =
      bookPath() + "/layouts/" + el("layout").value + "/interior.pdf";
  else el("pdf").removeAttribute("href");
}
async function loadLayouts(selected) {
  const path = bookPath();
  let rows = [];
  if (el("book").value) {
    try {
      rows = await api(path + "/layouts");
    } catch (error) {
      if (error.code !== 403) throw error;
    }
  }
  if (path !== bookPath()) return;
  options(
    "layout",
    rows.map((v) => ({
      ...v,
      label: v.title + " · " + v.created.slice(0, 19),
    })),
    "id",
    "label",
    selected,
  );
  pdfLink();
}
bind("layout", "change", pdfLink);
bind("book", "input", () => loadLayouts());
bind("layoutForm", "submit", async (e) => {
  if (!el("book").value) throw new Error("Importa un manuscrito.");
  const data = Object.fromEntries(new FormData(e.target));
  data.margin = Number(data.margin);
  const layout = await api(bookPath() + "/layouts", "POST", data);
  await loadLayouts(layout.id);
  status("Edición guardada. Ya puedes abrir el interior PDF.");
});
