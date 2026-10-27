// Frontend del sistema de riesgo de incendios. Consume la API a través del balanceador (mismo origen).
const API = "/api/v1";
const COLORES = { BAJO: "#15803d", MEDIO: "#ca8a04", ALTO: "#ea580c", EXTREMO: "#991b1b" };
let token = sessionStorage.getItem("token");
let rol = sessionStorage.getItem("rol");
let mapa, marcadores = {};

const $ = (id) => document.getElementById(id);

async function api(ruta, opciones = {}) {
  const resp = await fetch(API + ruta, {
    ...opciones,
    headers: { ...(opciones.headers || {}), Authorization: `Bearer ${token}` },
  });
  if (resp.status === 401) { cerrarSesion(); throw new Error("Sesión expirada"); }
  const datos = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(datos.detail || `Error ${resp.status}`);
  return { datos, instancia: resp.headers.get("X-Instancia") };
}

$("form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  const cuerpo = new URLSearchParams({ username: $("usuario").value, password: $("clave").value });
  const resp = await fetch(`${API}/auth/login`, { method: "POST", body: cuerpo });
  const datos = await resp.json().catch(() => ({}));
  if (!resp.ok) { $("error-login").textContent = datos.detail || "Error de autenticación"; return; }
  token = datos.access_token; rol = datos.rol;
  sessionStorage.setItem("token", token); sessionStorage.setItem("rol", rol);
  iniciar();
});

function cerrarSesion() {
  sessionStorage.clear(); token = null;
  $("app").hidden = true; $("login").hidden = false; $("sesion").textContent = "";
}

$("manual").addEventListener("change", () => { $("vars").hidden = !$("manual").checked; });

$("btn-consultar").addEventListener("click", async () => {
  const cuerpo = { comuna: $("comuna").value };
  if ($("manual").checked) {
    cuerpo.variables = {
      temperatura: +$("temperatura").value, humedad: +$("humedad").value,
      viento: +$("viento").value, dias_sin_lluvia: parseInt($("dias").value, 10),
    };
  }
  $("resultado").textContent = "Calculando…";
  try {
    const { datos } = await api("/riesgo", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
    });
    const v = datos.variables;
    $("resultado").innerHTML = "";
    const nivel = document.createElement("p");
    nivel.innerHTML = `<span class="nivel ${datos.nivel}">${datos.nivel}</span>`;
    const detalle = document.createElement("small");
    detalle.textContent = `${datos.comuna} · ${v.temperatura} °C · ${v.humedad} % HR · ${v.viento} km/h · ` +
      `${v.dias_sin_lluvia} días sin lluvia · fuente: ${datos.fuente_clima} · modelo ${datos.modelo_version} · ` +
      `atendido por ${datos.instancia_api}`;
    $("resultado").append(nivel, detalle);
    pintar(datos.comuna, datos.nivel);
    cargarHistorial();
    if (rol === "admin") setTimeout(cargarAlertas, 800);
  } catch (err) { $("resultado").textContent = err.message; }
});

function pintar(comuna, nivel) {
  const m = marcadores[comuna];
  if (m) { m.setStyle({ color: COLORES[nivel], fillColor: COLORES[nivel] }); m.bindPopup(`${comuna}: ${nivel}`).openPopup(); }
}

async function cargarHistorial() {
  const { datos } = await api("/consultas?limite=10");
  $("historial").replaceChildren(...datos.map((c) => {
    const li = document.createElement("li");
    li.textContent = `${new Date(c.creado_en).toLocaleString("es-CL")} · ${c.comuna} · ${c.nivel} (${c.usuario})`;
    return li;
  }));
}

async function cargarAlertas() {
  const { datos } = await api("/alertas?limite=10");
  $("alertas").replaceChildren(...datos.map((a) => {
    const li = document.createElement("li");
    li.textContent = `${new Date(a.creado_en).toLocaleString("es-CL")} · ${a.mensaje}`;
    return li;
  }));
}

async function iniciar() {
  $("login").hidden = true; $("app").hidden = false;
  $("sesion").textContent = `Rol: ${rol}`;
  $("panel-alertas").hidden = rol !== "admin";
  if (!mapa) {
    mapa = L.map("mapa").setView([-33.05, -71.3], 9);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "© OpenStreetMap",
    }).addTo(mapa);
  }
  const { datos: comunas } = await api("/comunas");
  $("comuna").replaceChildren(...comunas.map((c) => new Option(c.nombre, c.nombre)));
  comunas.forEach((c) => {
    if (marcadores[c.nombre]) return;
    marcadores[c.nombre] = L.circleMarker([c.lat, c.lon], { radius: 10, color: "#555", fillOpacity: 0.7 })
      .addTo(mapa).bindTooltip(c.nombre)
      .on("click", () => { $("comuna").value = c.nombre; });
  });
  cargarHistorial();
  if (rol === "admin") cargarAlertas();
}

if (token) iniciar().catch(cerrarSesion);
