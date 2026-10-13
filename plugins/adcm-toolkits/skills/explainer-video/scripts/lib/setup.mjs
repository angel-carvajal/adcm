// Off-camera preparation: the host guard, the config/profile setup steps, the fonts check and the overlay.
import { fillPlaceholders, hostAllowed } from './config.mjs';
import { runStep, stepFail } from './steps.mjs';

const GUARDED = new Set(['http:', 'https:', 'ws:', 'wss:']);
const guarded = (url) => {
  try {
    return GUARDED.has(new URL(url).protocol);
  } catch {
    return false;
  }
};

// Every request the page makes (HTTP and WebSocket) to a host outside allowHosts is aborted and ends the run:
// recordings only ever run against a local stack, never production. An allowed request is fetched here without
// following redirects, so a 3xx that points outside is stopped before the outside host is contacted and each
// allowed hop comes back through this route. EventSource streams cannot be buffered: they pass through, and the
// request listener ends the run on any hop that leaves the list.
export async function guardHosts(context, allowHosts, onBlocked) {
  const blocked = (url) => guarded(url) && !hostAllowed(url, allowHosts);
  // The run ends first: the abort makes the page's own navigation fail, and that failure must not win the exit code.
  const stop = (route, url) => {
    const ended = onBlocked(url);
    route.abort('blockedbyclient').catch(() => {});
    return ended;
  };
  const redirectsOutside = (response, url) => {
    const location = response.headers().location;
    if (!location || response.status() < 300 || response.status() >= 400) return null;
    try {
      const next = new URL(location, url).href;
      return blocked(next) ? next : null;
    } catch {
      return null;
    }
  };
  await context.route('**/*', async (route) => {
    const request = route.request();
    const url = request.url();
    if (blocked(url)) return stop(route, url);
    if (request.resourceType() === 'eventsource') return route.fallback();
    const response = await route.fetch({ maxRedirects: 0 }).catch(() => null);
    if (!response) return route.abort('failed').catch(() => {});
    const outside = redirectsOutside(response, url);
    if (outside) return stop(route, outside);
    return route.fulfill({ response }).catch(() => {});
  });
  context.on('request', (request) => {
    if (blocked(request.url())) onBlocked(request.url());
  });
  await context.routeWebSocket(/.*/, async (ws) => {
    if (!blocked(ws.url())) return ws.connectToServer();
    await ws.close({ code: 1008, reason: 'host not allowed' }).catch(() => {});
    return onBlocked(ws.url());
  });
}

// A guion's profile replaces the default setup; a profile without setup records with no setup at all.
export const setupFor = (config, guion) =>
  guion.profile === undefined ? config.setup : config.profiles[guion.profile].setup ?? [];

async function setupStep(page, step, config, ctx) {
  await runStep(page, { ...step, value: fillPlaceholders(step.value, config.timezone) }, ctx);
  if (step.waitFor) await page.locator(step.waitFor).first().waitFor({ state: 'visible', timeout: 15000 });
}

export async function runSetup(page, steps, config) {
  const ctx = { baseUrl: config.baseUrl, configDir: config.dir };
  for (const [i, step] of steps.entries()) {
    const where = `setup[${i}] (${step.action}${step.selector ? ' ' + step.selector : ''})`;
    await setupStep(page, step, config, ctx).catch(stepFail(where));
  }
}

// fonts.check() says true with no network: only a FontFace actually loaded counts.
export function fontsLoaded(page, families) {
  return page.evaluate(async (wanted) => {
    const clean = (f) => f.replace(/["']/g, '');
    await Promise.all(wanted.map((family) => document.fonts.load(`16px "${family}"`, 'AaBbÁáÉéÍíÓóÚúÑñ0123456789').catch(() => [])));
    return wanted.every((family) => [...document.fonts].some((f) => clean(f.family) === family && f.status === 'loaded'));
  }, families);
}

export async function installOverlay(context, page, overlayPath, cfg) {
  await context.addInitScript((c) => { window.__RECCFG = c; }, cfg);
  await context.addInitScript({ path: overlayPath });
  await page.evaluate((c) => { window.__RECCFG = c; }, cfg);
  await page.addScriptTag({ path: overlayPath });
  await page.waitForFunction(() => Boolean(window.__rec));
}
