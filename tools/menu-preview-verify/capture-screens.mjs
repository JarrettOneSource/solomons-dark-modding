// Open the staged webgame in headless Chrome (CDP :9223), wait for the shell
// to finish booting, and screenshot each requested screen at exactly 1600x900.
// usage: node capture-screens.mjs <baseUrl> <outDir> <screenSpec>...
//   screenSpec = <layoutId>[:focus0]   e.g. beta-notice  beta-notice:focus0
import { writeFileSync } from "node:fs";

const [, , baseUrl, outDir, ...specs] = process.argv;
if (!baseUrl || !outDir || specs.length === 0) {
  console.error("usage: node capture-screens.mjs <baseUrl> <outDir> <screenSpec>...");
  process.exit(1);
}

async function attach(url) {
  const created = await (await fetch(
    `http://127.0.0.1:9223/json/new?${encodeURIComponent(url)}`,
    { method: "PUT" },
  )).json();
  const ws = new WebSocket(created.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  let nextId = 1;
  const pending = new Map();
  ws.onmessage = (event) => {
    const msg = JSON.parse(typeof event.data === "string" ? event.data : event.data.toString());
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    }
  };
  const cdp = (method, params = {}) => {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  };
  return { ws, cdp, targetId: created.id };
}

async function evalJson(cdp, expression) {
  const { result, exceptionDetails } = await cdp("Runtime.evaluate", {
    expression, returnByValue: true, awaitPromise: true,
  });
  if (exceptionDetails) {
    throw new Error(`page threw: ${JSON.stringify(exceptionDetails).slice(0, 400)}`);
  }
  return result.value;
}

for (const spec of specs) {
  const [layoutId, flag] = spec.split(":");
  const focusOff = flag === "focus0";
  const url = `${baseUrl}/?screen=${layoutId}${focusOff ? "&focus=0" : ""}`;
  const { ws, cdp, targetId } = await attach(url);
  await cdp("Emulation.setDeviceMetricsOverride", {
    width: 1600, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  await cdp("Runtime.enable");
  await cdp("Page.enable");

  const deadline = Date.now() + 60000;
  let state = null;
  while (Date.now() < deadline) {
    state = await evalJson(cdp, `(() => {
      const shell = window.__webshell;
      if (!shell || shell.ready !== true) return { phase: "booting", body: document.body.textContent.slice(0, 200) };
      return { phase: "ready", layoutId: shell.renderPlan().layoutId };
    })()`);
    if (state.phase === "ready" && state.layoutId === layoutId) break;
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!state || state.phase !== "ready" || state.layoutId !== layoutId) {
    console.error(`TIMEOUT waiting for ${layoutId}: ${JSON.stringify(state).slice(0, 400)}`);
    ws.close();
    process.exit(1);
  }
  // Let the rAF loop draw a few presented frames before capturing.
  await new Promise((r) => setTimeout(r, 700));
  const shot = await cdp("Page.captureScreenshot", { format: "png" });
  const path = `${outDir}/${layoutId}${focusOff ? "-nofocus" : ""}.png`;
  writeFileSync(path, Buffer.from(shot.data, "base64"));
  console.log(`${path} ${Buffer.from(shot.data, "base64").length} bytes (layout ${state.layoutId})`);
  ws.close();
  await fetch(`http://127.0.0.1:9223/json/close/${targetId}`);
}
