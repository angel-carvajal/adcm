// Recording overlay, injected with addInitScript (every new document) and addScriptTag (the current one).
// Everything is page DOM with pointer-events:none: it shows up in the video and never intercepts a click.
// Optional config set before loading: window.__RECCFG = { blur: [css selector], brand: {accent, bg}, font }.
(() => {
  if (window.top !== window) return;

  const cfg = window.__RECCFG || {};
  const ACCENT = (cfg.brand && cfg.brand.accent) || '#3B82F6';
  const BG = (cfg.brand && cfg.brand.bg) || '#111318';
  const FONT = cfg.font ? `"${cfg.font}",system-ui,sans-serif` : 'system-ui,sans-serif';
  const SUB_BOTTOM = 32;
  const SUB_TOP = 54;
  const BAR_TOP = 14;
  // Only headings that start inside this top strip count: the bar does not chase headings further down.
  const TITLE_STRIP = 160;
  // Breathing room the bar leaves to a heading, a control and the viewport edge when it steps aside.
  const GAP = 16;
  // Besides headings, the bar does not cover header controls, toolbars or side panels in its row.
  const CONTROLS = 'header button, header a, header [role="button"], [role="toolbar"], aside, nav';
  // Corner where the recorder parks the real mouse; the synthetic cursor does not follow it there.
  const PARK = 12;
  const BLUR = cfg.blur || [];

  const CSS = `
  #rec-top{position:fixed;top:${BAR_TOP}px;left:50%;transform:translateX(-50%);z-index:2147483600;pointer-events:none;
    max-width:80vw;box-sizing:border-box;background:rgba(12,12,14,.78);color:#F5F5F5;border-left:4px solid ${ACCENT};
    border-radius:0 8px 8px 0;padding:6px 14px;font:600 15px/1.2 ${FONT};letter-spacing:.06em;
    text-transform:uppercase;white-space:nowrap}
  #rec-top:empty{display:none}
  #rec-sub{position:fixed;left:50%;bottom:${SUB_BOTTOM}px;transform:translateX(-50%);z-index:2147483600;pointer-events:none;
    max-width:72vw;width:max-content;box-sizing:border-box;background:rgba(0,0,0,.6);color:#fff;border-radius:10px;
    padding:10px 20px;font:500 23px/1.35 ${FONT};text-align:center;white-space:pre-line;
    text-shadow:0 1px 2px rgba(0,0,0,.6);transition:bottom .2s}
  #rec-sub:empty{display:none}
  #rec-cur{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;opacity:0;
    transition:transform .45s cubic-bezier(.2,.7,.2,1),opacity .2s;filter:drop-shadow(0 1px 2px rgba(0,0,0,.7))}
  .rec-ring{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;box-sizing:border-box;border:3px solid ${ACCENT};
    border-radius:50%;z-index:2147483646;pointer-events:none;animation:rec-ring .5s ease-out forwards}
  @keyframes rec-ring{from{transform:scale(.3);opacity:1}to{transform:scale(1.4);opacity:0}}
  #rec-hl{position:fixed;left:0;top:0;z-index:2147483645;pointer-events:none;box-sizing:border-box;
    border:3px solid ${ACCENT};border-radius:10px;box-shadow:0 0 0 4px color-mix(in srgb, ${ACCENT} 25%, transparent);
    opacity:0;transition:opacity .2s}
  #rec-card{position:fixed;inset:0;z-index:2147483647;pointer-events:none;background:${BG};display:flex;
    flex-direction:column;align-items:center;justify-content:center;gap:18px;padding:0 10vw;box-sizing:border-box;
    text-align:center;opacity:0;transition:opacity .25s}
  #rec-card .rec-line{width:72px;height:3px;border-radius:2px;background:${ACCENT}}
  #rec-card .rec-kicker{font:600 16px/1 ${FONT};letter-spacing:.2em;text-transform:uppercase;color:${ACCENT}}
  #rec-card .rec-title{font:700 46px/1.15 ${FONT};color:#F5F5F5;max-width:80vw}
  ${BLUR.map((s) => `${s}{filter:blur(6px) !important}`).join('\n  ')}`;

  function install() {
    if (window.__rec || !document.body) return;

    const style = document.createElement('style');
    style.id = 'rec-style';
    style.textContent = CSS;
    document.head.appendChild(style);

    const mk = (id) => {
      const el = document.createElement('div');
      el.id = id;
      document.body.appendChild(el);
      return el;
    };
    const topEl = mk('rec-top');
    const subEl = mk('rec-sub');
    const hlEl = mk('rec-hl');
    const curEl = mk('rec-cur');
    const cardEl = mk('rec-card');

    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    const arrow = document.createElementNS(NS, 'path');
    svg.setAttribute('width', '26');
    svg.setAttribute('height', '26');
    svg.setAttribute('viewBox', '0 0 26 26');
    arrow.setAttribute('d', 'M3 2 L3 21 L8.5 16 L12.5 24 L15.5 22.6 L11.6 14.8 L19 14.8 Z');
    arrow.setAttribute('fill', '#fff');
    arrow.setAttribute('stroke', '#111');
    arrow.setAttribute('stroke-width', '1.6');
    arrow.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(arrow);
    curEl.appendChild(svg);

    const parts = {};
    for (const cls of ['line', 'kicker', 'title']) {
      parts[cls] = document.createElement('div');
      parts[cls].className = 'rec-' + cls;
      cardEl.appendChild(parts[cls]);
    }

    let pos = 'bottom';

    // The subtitle rises above a bottom-center toast stack (24 px offset, 14 px gap, 3 visible). offsetHeight and
    // not getBoundingClientRect: the latter measures a toast halfway through its entry animation.
    const layoutBottom = () => {
      if (pos === 'top') return;
      const toasts = [...document.querySelectorAll('[data-sonner-toast]:not([data-removed="true"])')];
      if (!toasts.length) {
        subEl.style.bottom = SUB_BOTTOM + 'px';
        return;
      }
      const tallest = Math.max(...toasts.map((t) => t.offsetHeight));
      const stack = 24 + tallest + 14 * (Math.min(toasts.length, 3) - 1);
      subEl.style.bottom = Math.max(SUB_BOTTOM, stack + 12) + 'px';
    };

    const visible = (el) => (el.checkVisibility ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) : true);

    // Boxes of the TEXT of each visible heading in the top strip (a Range, not the element): a block h1 spans the
    // full width even when its text sits to one side.
    const titleRects = () =>
      [...document.querySelectorAll('h1, h2, [role="heading"]')]
        .filter(visible)
        .flatMap((el) => {
          const range = document.createRange();
          range.selectNodeContents(el);
          return [...range.getClientRects()];
        })
        .filter((r) => r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < TITLE_STRIP);

    const controlRects = () =>
      [...document.querySelectorAll(CONTROLS)]
        .filter(visible)
        .map((el) => el.getBoundingClientRect())
        .filter((r) => r.width > 0 && r.height > 0);

    // The bar dodges a heading it would cover: first it steps aside within its row (right of the heading if it
    // fits, else left) without leaving the viewport or covering a control; only when neither side fits does it
    // drop just below (+8 px). With no overlap it returns home. center null keeps the CSS centering.
    const placeBar = (h, w) => {
      const home = { barTop: BAR_TOP, center: null };
      if (!h) return home;
      const mid = window.innerWidth / 2;
      const titles = titleRects();
      const inRow = (r, t) => r.bottom > t && r.top < t + h;
      const hits = (t) => titles.filter((r) => inRow(r, t) && r.right > mid - w / 2 && r.left < mid + w / 2);
      const hit = hits(BAR_TOP);
      if (!hit.length) return home;
      const blockers = [...titles, ...controlRects()].filter((r) => inRow(r, BAR_TOP));
      const free = (x0) =>
        x0 >= GAP && x0 + w <= window.innerWidth - GAP && !blockers.some((r) => r.right + GAP > x0 && r.left - GAP < x0 + w);
      const toRight = Math.max(...hit.map((r) => r.right)) + GAP;
      if (free(toRight)) return { barTop: BAR_TOP, center: Math.round(toRight + w / 2) };
      const toLeft = Math.min(...hit.map((r) => r.left)) - GAP - w;
      if (free(toLeft)) return { barTop: BAR_TOP, center: Math.round(toLeft + w / 2) };
      let barTop = BAR_TOP;
      let overlapping = hit;
      while (overlapping.length) {
        barTop = Math.ceil(Math.max(...overlapping.map((r) => r.bottom))) + 8;
        overlapping = hits(barTop);
      }
      return barTop > TITLE_STRIP + 40 ? home : { barTop, center: null };
    };

    // The top subtitle hangs from the bar.
    const layoutTop = () => {
      const h = topEl.offsetHeight;
      const { barTop, center } = placeBar(h, topEl.offsetWidth);
      const left = center === null ? '' : center + 'px';
      if (topEl.style.left !== left) topEl.style.left = left;
      if (topEl.style.top !== barTop + 'px') topEl.style.top = barTop + 'px';
      if (pos === 'top') subEl.style.top = (h ? Math.max(SUB_TOP, barTop + h + 10) : SUB_TOP) + 'px';
    };

    let queued = false;
    const refresh = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        layoutBottom();
        layoutTop();
      });
    };
    new MutationObserver(refresh).observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-removed', 'data-mounted'],
    });
    window.addEventListener('resize', refresh);
    // Scrolling an inner container does not bubble: only a capture listener sees it. The interval covers class
    // changes and animations.
    window.addEventListener('scroll', refresh, true);
    setInterval(refresh, 250);

    let shown = false;
    const moveCursor = (x, y) => {
      const at = `translate(${x - 3}px,${y - 2}px)`;
      if (!shown) {
        shown = true;
        curEl.style.transition = 'none';
        curEl.style.transform = at;
        void curEl.offsetWidth;
        curEl.style.transition = '';
        curEl.style.opacity = '1';
        return;
      }
      curEl.style.transform = at;
    };
    window.addEventListener(
      'mousemove',
      (e) => {
        if (e.clientX >= window.innerWidth - PARK && e.clientY <= PARK) return;
        moveCursor(e.clientX, e.clientY);
      },
      true,
    );
    window.addEventListener(
      'mousedown',
      (e) => {
        const ring = document.createElement('div');
        ring.className = 'rec-ring';
        ring.style.left = e.clientX + 'px';
        ring.style.top = e.clientY + 'px';
        document.body.appendChild(ring);
        setTimeout(() => ring.remove(), 600);
      },
      true,
    );

    // The highlight follows the node while it exists and has a box (a SPA re-renders and moves it). One frame
    // loop at most: it stops by itself once the target is cleared.
    let target = null;
    let following = false;
    const follow = () => {
      if (!target) {
        following = false;
        return;
      }
      const r = target.isConnected ? target.getBoundingClientRect() : null;
      if (!r || !r.width || !r.height) {
        hlEl.style.opacity = '0';
      } else {
        hlEl.style.opacity = '1';
        hlEl.style.transform = `translate(${r.left - 5}px,${r.top - 5}px)`;
        hlEl.style.width = r.width + 10 + 'px';
        hlEl.style.height = r.height + 10 + 'px';
      }
      requestAnimationFrame(follow);
    };

    window.__rec = {
      // top: caption bar text · sub: subtitle · pos: 'bottom' | 'top' (current step only)
      set(p) {
        if ('top' in p) topEl.textContent = p.top || '';
        if ('sub' in p) subEl.textContent = p.sub || '';
        if ('pos' in p) {
          pos = p.pos;
          if (pos === 'top') subEl.style.bottom = 'auto';
          else subEl.style.top = 'auto';
        }
        layoutBottom();
        layoutTop();
      },
      // spec { kicker?, title } shows the card; null hides it. instant: no fade (first frame of the video).
      card(spec, instant) {
        cardEl.style.transition = instant ? 'none' : '';
        if (!spec) {
          cardEl.style.opacity = '0';
          return;
        }
        parts.kicker.textContent = spec.kicker || '';
        parts.kicker.style.display = spec.kicker ? '' : 'none';
        parts.title.textContent = spec.title || '';
        document.body.appendChild(cardEl);
        void cardEl.offsetWidth;
        cardEl.style.opacity = '1';
      },
      highlight(el) {
        target = el || null;
        if (!target) hlEl.style.opacity = '0';
        else if (!following) {
          following = true;
          follow();
        }
      },
    };
  }

  if (document.body) install();
  else document.addEventListener('DOMContentLoaded', install, { once: true });
})();
