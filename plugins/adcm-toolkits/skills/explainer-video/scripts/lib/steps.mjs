// The actions of one step, shared by setup (off camera) and recording. Selector calls on `page` are not strict:
// they take the first match, so a selector that matches several nodes still works. `before(selector)` is optional:
// it runs before touching the node and the recorder uses it to glide the cursor there.
import path from 'node:path';
import { stripVTControlCharacters } from 'node:util';
import { Fail, isFail, redact } from './config.mjs';

export const NAV = { waitUntil: 'networkidle', timeout: 45000 };
export const sleep = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms)));

export const firstLines = (e, n = 8) => redact(stripVTControlCharacters(String(e.message)).split('\n').slice(0, n).join(' | '));
// A step that throws becomes a Fail(1) that names where it happened; a Fail passes through untouched.
export const stepFail = (where) => (e) => {
  throw isFail(e) ? e : new Fail(1, `${where}: ${firstLines(e)}`);
};

export const absoluteUrl = (value, baseUrl) => (String(value).startsWith('/') ? baseUrl + value : String(value));

async function pick(page, selector, value) {
  await page.click(selector);
  await page.waitForTimeout(300);
  await page.keyboard.type(String(value), { delay: 40 });
  await page.locator('[role="option"]').first().waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForTimeout(300);
  await page.keyboard.press('Enter');
}

// Mail-catcher HTTP API (GET {url}/api/v1/messages, GET {url}/api/v1/message/{id}): the newest message to `address`
// received since `since` (ms); returns its first link to an allowed host.
async function mailLink(mail, address, since, allowed) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const list = await (await fetch(`${mail.url}/api/v1/messages?limit=20`)).json();
    const mine = (list.messages || [])
      .filter((m) => (m.To || []).some((t) => String(t.Address).toLowerCase() === address.toLowerCase()) && new Date(m.Created).getTime() >= since)
      .sort((a, b) => new Date(b.Created) - new Date(a.Created));
    if (mine.length) {
      const full = await (await fetch(`${mail.url}/api/v1/message/${mine[0].ID}`)).json();
      const urls = `${full.HTML || ''} ${full.Text || ''}`.match(/https?:\/\/[^\s"'<>]+/g) || [];
      const link = urls.map((u) => u.replace(/&amp;/g, '&')).find(allowed);
      if (link) return link;
    }
    await sleep(500);
  }
  return null;
}

async function scroll(page, selector, value) {
  const y = Number(value) || 0;
  // An app often scrolls an inner container, not window: with a selector that container is scrolled.
  if (selector) await page.evaluate(({ target, top }) => { document.querySelector(target).scrollTop = top; }, { target: selector, top: y });
  else await page.evaluate((top) => window.scrollTo(0, top), y);
}

// step.value arrives with its placeholders already filled. ctx: { before?, baseUrl, configDir, mail, allowed, since }
export async function runStep(page, step, ctx) {
  const { selector: sel, value: val } = step;
  const prepare = async () => {
    if (sel && ctx.before) await ctx.before(sel);
  };
  switch (step.action) {
    case 'click':
      await prepare();
      return page.click(sel);
    case 'fill':
      await prepare();
      return page.fill(sel, String(val ?? ''));
    case 'select':
      await prepare();
      return page.selectOption(sel, String(val ?? ''));
    case 'press':
      if (!sel) return page.keyboard.press(String(val));
      await prepare();
      return page.press(sel, String(val));
    case 'type':
      // Typed character by character into the focused node; with a selector it is clicked first to focus it.
      if (sel) {
        await prepare();
        await page.click(sel);
      }
      return page.keyboard.type(String(val ?? ''), { delay: 40 });
    case 'scroll':
      await prepare();
      return scroll(page, sel, val);
    case 'wait':
      return page.waitForTimeout(Number(val) || 500);
    case 'pick':
      await prepare();
      return pick(page, sel, val);
    case 'goto':
      return page.goto(absoluteUrl(val, ctx.baseUrl), NAV);
    case 'mail': {
      const link = await mailLink(ctx.mail, String(val), ctx.since, ctx.allowed);
      if (!link) throw new Error(`no message with a usable link arrived for ${val}`);
      return page.goto(link, NAV);
    }
    case 'upload':
      await prepare();
      return page.setInputFiles(sel, [].concat(val).map((f) => path.resolve(ctx.configDir, f)));
    case 'drag':
      await prepare();
      return page.locator(sel).first().dragTo(page.locator(val).first(), { steps: 25 });
    case 'mock':
      return page.route(val.url, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(val.body) }));
    default:
      return undefined;
  }
}
