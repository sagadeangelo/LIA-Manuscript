const form = document.querySelector("form");
const status = document.querySelector("[role=status]");
const list = document.querySelector("dl");
form.onsubmit = async (event) => {
  event.preventDefault();
  list.replaceChildren();
  const token = form.querySelector("input").value;
  const tool = form.elements.tool.value,
    limit = form.elements.allowance.value;
  form.querySelector("input[type=password]").value = "";
  try {
    if (event.submitter.value === "update") {
      if (limit === "") throw new Error("Indica el nuevo límite.");
      const saved = await fetch("/api/admin/limits", {
        method: "PUT",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tool, allowance: Number(limit) }),
      });
      if (!saved.ok) throw new Error("No se pudo guardar el límite.");
    }
    const response = await fetch("/api/admin/summary", {
      headers: { Authorization: "Bearer " + token },
    });
    if (!response.ok)
      throw new Error(
        response.status === 401
          ? "Inicia sesión en Writer Studio."
          : "Acceso administrativo denegado.",
      );
    const data = await response.json();
    for (const [key, value] of Object.entries({
      Cuentas: data.accounts,
      "Operaciones simuladas": data.simulated_events,
      "Ingresos reales (MXN)": data.live_revenue,
      ...data.active_plans,
    })) {
      const term = document.createElement("dt"),
        count = document.createElement("dd");
      term.textContent = key;
      count.textContent = value;
      list.append(term, count);
    }
    for (const [tool, limit] of Object.entries(data.daily_limits)) {
      const term = document.createElement("dt"),
        value = document.createElement("dd");
      term.textContent = "Límite diario de " + tool;
      value.textContent =
        limit +
        " por cuenta · " +
        (data.usage[tool] || 0) +
        " operaciones históricas";
      list.append(term, value);
    }
    status.textContent = "Actividad actualizada.";
  } catch (error) {
    status.textContent = error.message;
  }
};
