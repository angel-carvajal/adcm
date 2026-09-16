/* extract-site.mjs — walk a public site with Playwright and extract its design direction.
 *
 * Usage:
 *   PATH=$(ls -d ~/.nvm/versions/node/v2[0-9]* | tail -1)/bin:$PATH \
 *   node extract-site.mjs <playwright-core-dir> <url> [outDir] [--quick]
 *
 *   --quick: desktop viewport screenshot (1440) + JSON only. Skips the
 *   full-page screenshot and the entire mobile pass. Default is unchanged
 *   (both passes, both full-page shots).
 *
 * Why each choice (all learned the hard way — do not "simplify" these):
 *   - Node 20+ required. The machine default may be 18; use an nvm 20/22 path.
 *   - playwright-core lives in the npx cache; find it, don't npm install.
 *   - channel:'chrome' drives the INSTALLED Chrome. The cached ms-playwright
 *     builds drift out of sync with playwright-core and error on launch.
 *   - waitUntil:'networkidle' NEVER settles on Framer/analytics-heavy sites.
 *     Use domcontentloaded, then scroll to the bottom to trigger lazy sections,
 *     then scroll back and let it settle.
 *   - Colors are ranked by PAINTED AREA, not by count: the ground is whatever
 *     covers the most pixels, which is what the eye actually reads as the theme.
 *   - Framer leaves data-framer-name on sections — free, human-readable section map.
 */
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';

const rawArgs = process.argv.slice(2);
const quick = rawArgs.includes('--quick');
const [pwDir, url, outDir = '.'] = rawArgs.filter(a => a !== '--quick');
if (!pwDir || !url) {
  console.error('usage: node extract-site.mjs <playwright-core-dir> <url> [outDir] [--quick]');
  process.exit(1);
}
const require = createRequire(pwDir + '/pkg.js');
const { chromium } = require('playwright-core');

const slug = url.replace(/^https?:\/\//, '').replace(/[^a-z0-9]+/gi, '-').replace(/-+$/, '');
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true, channel: 'chrome' });

async function settle(page) {
  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  if (response && response.status() >= 400) {
    const err = new Error(`HTTP ${response.status()}`); err.http = response.status(); throw err;
  }
  await page.waitForTimeout(4000);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(2500);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(800);
}

const extract = () => {
  const seen = { bg: {}, fg: {}, fonts: {}, type: {}, radius: {}, motion: new Set() };
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const s = getComputedStyle(el), area = r.width * r.height;
    if (s.backgroundColor && s.backgroundColor !== 'rgba(0, 0, 0, 0)')
      seen.bg[s.backgroundColor] = (seen.bg[s.backgroundColor] || 0) + area;
    if (s.borderRadius && s.borderRadius !== '0px')
      seen.radius[s.borderRadius] = (seen.radius[s.borderRadius] || 0) + 1;
    if (s.transitionDuration && s.transitionDuration !== '0s')
      seen.motion.add(`${s.transitionProperty} ${s.transitionDuration} ${s.transitionTimingFunction}`);
    if (!el.childElementCount && el.textContent.trim()) {
      seen.fg[s.color] = (seen.fg[s.color] || 0) + area;
      const fam = s.fontFamily.split(',')[0].replace(/["']/g, '').trim();
      seen.fonts[fam] = (seen.fonts[fam] || 0) + 1;
      const k = `${s.fontSize} w${s.fontWeight} lh:${s.lineHeight} tt:${s.textTransform} ls:${s.letterSpacing} [${fam}]`;
      seen.type[k] = (seen.type[k] || 0) + 1;
    }
  }
  const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n)
    .map(([k, v]) => ({ value: k, weight: Math.round(v) }));
  const sections = [...document.querySelectorAll('section, [data-framer-name], main > div')]
    .map(el => ({
      name: el.getAttribute('data-framer-name') || el.id || el.tagName.toLowerCase(),
      height: Math.round(el.getBoundingClientRect().height),
      text: (el.innerText || '').trim().slice(0, 90).replace(/\s+/g, ' '),
    }))
    .filter(s => s.height > 300)
    .slice(0, 20);
  return {
    ground: top(seen.bg, 8), ink: top(seen.fg, 6), fonts: top(seen.fonts, 5),
    typeScale: top(seen.type, 14), radii: top(seen.radius, 5),
    motion: [...seen.motion].slice(0, 12),
    sections,
    docHeight: Math.round(document.body.scrollHeight),
  };
};

// Desktop pass
let data;
try {
  const desk = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await settle(desk);
  data = await desk.evaluate(extract);
  data.url = url;
  await desk.screenshot({ path: `${outDir}/${slug}-desktop.png` });
  if (!quick) await desk.screenshot({ path: `${outDir}/${slug}-desktop-full.png`, fullPage: true });
  await desk.close();

  if (!quick) {
    // Mobile pass — 390px is the real audience width for most of these projects
    const mob = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
    await settle(mob);
    data.mobileSections = await mob.evaluate(() => [...document.querySelectorAll('section, [data-framer-name]')]
      .map(el => ({ name: el.getAttribute('data-framer-name') || el.tagName.toLowerCase(),
                    height: Math.round(el.getBoundingClientRect().height) }))
      .filter(s => s.height > 200).slice(0, 20));
    await mob.screenshot({ path: `${outDir}/${slug}-mobile.png` });
    await mob.screenshot({ path: `${outDir}/${slug}-mobile-full.png`, fullPage: true });
    await mob.close();
  }
} catch (e) {
  // A dead demo (4xx/5xx) or a navigation failure must not strand a Chrome process.
  process.stderr.write(JSON.stringify({ error: e.http ? `HTTP ${e.http}` : String(e.message), url }) + '\n');
  process.exitCode = 2;
  data = null;
} finally {
  await browser.close();
}
if (data) console.log(JSON.stringify(data, null, 1));
