# Style taxonomy — STEP 2

Fifteen named styles, each defined **operationally**: not a mood word, but the
typography, spacing, color, motion, per-source search terms and anti-patterns
that make it reproducible.

A style the user names that is not here is **derived**, not rejected: map their
words onto the six dimensions below and say which named style it lands nearest.

Dimensions every style must answer: **type**, **spacing/scale**, **color**,
**motion**, **search terms per source**, **anti-patterns**.

---

## 1. swiss-minimal
- **Type:** one grotesque (Helvetica Now, Inter, Neue Haas). Tight tracking on display, generous leading on body. Two weights maximum.
- **Spacing:** strict 8pt grid, wide margins, asymmetric columns. Whitespace is the design.
- **Color:** near-monochrome, one accent used under 5% of the surface.
- **Motion:** almost none. Opacity fades under 200ms.
- **Framer:** categories `design`, `agency`, `portfolio` · sort Best
- **Pinterest:** "swiss design website", "grid layout minimal web", chips Layout + Website
- **21st:** "minimal hero", "clean navigation"
- **Anti-patterns:** gradients, drop shadows, rounded corners above 4px, more than one accent.

## 2. brutalist
- **Type:** system or monospace, oversized, deliberately unrefined. Raw HTML defaults embraced.
- **Spacing:** dense, colliding, no comfortable gutters. Content edge-to-edge.
- **Color:** high contrast, unblended primaries, visible borders.
- **Motion:** hard cuts, no easing, instant state changes.
- **Framer:** categories `design`, `artists`, `music` · sort New
- **Pinterest:** "brutalist web design", "raw html aesthetic", chips Web + Creative
- **21st:** "bordered card", "monospace"
- **Anti-patterns:** soft shadows, gradients, decorative illustration, anything that looks "designed".

## 3. neo-brutalist
- **Type:** heavy geometric sans, chunky. Bold weight as the default, not the exception.
- **Spacing:** blocky, generous padding inside hard-bordered containers.
- **Color:** saturated flat blocks, thick black borders, hard offset shadows.
- **Motion:** snappy transforms, elements that shift on hover with no blur.
- **Framer:** categories `apps`, `saas`, `ai` · sort Trending
- **Pinterest:** "neubrutalism ui", "hard shadow card design", chips Web + Layout
- **21st:** "neobrutalist", "offset shadow button"
- **Anti-patterns:** soft blur, glassmorphism, subtle palettes, thin type.

## 4. editorial
- **Type:** a serif for display (Canela, Tiempos, Playfair) against a sans for body. Real typographic hierarchy — kickers, drop caps, pull quotes.
- **Spacing:** magazine column rhythm, measure capped near 70ch, wide vertical breathing.
- **Color:** paper-warm neutrals, ink black, one editorial accent.
- **Motion:** text reveals on scroll, staggered per line.
- **Framer:** categories `publishing`, `magazines`, `blogs`, `fashion` · sort Best
- **Pinterest:** "editorial web layout", "magazine typography website", chips Layout + Aesthetic
- **21st:** "article layout", "typography hero"
- **Anti-patterns:** centered everything, uniform card grids, sans-only hierarchy.

## 5. dark-luxury
- **Type:** high-contrast serif or a refined thin sans, wide letter-spacing on small caps labels.
- **Spacing:** slow, generous. Few elements per viewport.
- **Color:** near-black ground (never pure #000), warm metallic or single jewel accent, low-saturation.
- **Motion:** slow fades, parallax under 20%, nothing bouncy.
- **Framer:** categories `beauty`, `hotels`, `real-estate`, `fashion` · sort Best
- **Pinterest:** "luxury website dark", "premium brand web design", chips Website + Aesthetic
- **21st:** "dark hero", "premium pricing"
- **Anti-patterns:** bright accents, playful motion, dense grids, stock smiling faces.

## 6. cinematic-scroll
- **Type:** display sans set very large, often as an overlay on media.
- **Spacing:** full-viewport sections, pinned stages, deliberate empty frames between beats.
- **Color:** driven by the footage; UI recedes to white/black overlays.
- **Motion:** the point. Scroll-linked timelines, pinned sections, clip-path reveals, video scrubbing, layered parallax depth.
- **Framer:** categories `entertainment`, `music`, `sports`, `travel` · sort Trending
- **Pinterest:** "scrollytelling website", "cinematic web experience", chips Web + Creative
- **21st:** "scroll animation", "video hero"
- **Pexels:** this style REQUIRES video — see `source-pexels.md`.
- **Pairs with:** the `epic-design` skill at handoff.
- **Anti-patterns:** motion without narrative reason, autoplay audio, animation that blocks reading.

## 7. glassmorphism
- **Type:** clean geometric sans, medium weight, high legibility over blur.
- **Spacing:** floating layered panels, soft overlap.
- **Color:** translucent surfaces over a saturated or gradient ground; borders as 1px light strokes.
- **Motion:** soft depth shifts, blur that responds to scroll.
- **Framer:** categories `saas`, `fintech`, `ai` · sort Trending
- **Pinterest:** "glassmorphism ui", "frosted glass web design", chips Web
- **21st:** "glass card", "blur background"
- **Anti-patterns:** low contrast text on busy grounds (check WCAG before choosing), stacking more than two blur layers.

## 8. flat
- **Type:** friendly geometric sans, consistent weight, no typographic drama.
- **Spacing:** even, predictable, card-based.
- **Color:** flat fills, no gradients or shadows, a broad but harmonized palette.
- **Motion:** simple, functional — nothing decorative.
- **Framer:** categories `services`, `education`, `health` · sort Best
- **Pinterest:** "flat design website", "illustration landing page", chips Web + Layout
- **21st:** "feature grid", "icon card"
- **Anti-patterns:** skeuomorphic texture, heavy shadow, over-illustration that dates fast.

## 9. bento
- **Type:** clean sans, small labels, numbers as visual anchors.
- **Spacing:** modular grid of unequal rounded tiles, each holding exactly one idea.
- **Color:** neutral base with per-tile accent.
- **Motion:** tiles lift or reorder on hover; content inside tiles animates independently.
- **Framer:** categories `saas`, `apps`, `ai`, `software` · sort Trending
- **Pinterest:** "bento grid website", "bento ui layout", chips Layout + Web
- **21st:** "bento grid", "feature tiles"
- **Anti-patterns:** tiles of equal size (defeats the point), text-heavy tiles, more than nine tiles per screen.

## 10. retro-print
- **Type:** period-accurate display faces, condensed sans or slab, textured.
- **Spacing:** poster composition — one dominant element, hierarchy by scale not position.
- **Color:** limited ink palette, halftone, paper grain, misregistration.
- **Motion:** minimal; texture does the work.
- **Framer:** categories `food`, `restaurants`, `music`, `events` · sort New
- **Pinterest:** "retro poster web design", "vintage print layout", chips Aesthetic + Creative
- **21st:** rarely applicable — build custom.
- **Anti-patterns:** clean vector gradients, modern shadow, mixing more than two period cues.

## 11. organic
- **Type:** humanist sans or a soft serif, generous leading.
- **Spacing:** flowing, asymmetric, curved section dividers.
- **Color:** earth tones, muted naturals, no pure black.
- **Motion:** slow, eased, breathing. Blob and curve morphs.
- **Framer:** categories `wellness`, `therapy`, `health`, `home` · sort Best
- **Pinterest:** "organic web design", "wellness brand website", chips Website + Aesthetic
- **21st:** "soft card", "rounded hero"
- **Anti-patterns:** hard grids, cold neutrals, sharp corners, fast motion.

## 12. y2k
- **Type:** chrome, bubble, or pixel display faces mixed intentionally badly.
- **Spacing:** cluttered on purpose, overlapping stickers and badges.
- **Color:** iridescent, chrome gradients, acid brights.
- **Motion:** looping GIF energy, cursor effects, marquees.
- **Framer:** categories `music`, `fashion`, `artists` · sort New
- **Pinterest:** "y2k web design", "frutiger aero aesthetic", chips Creative + Aesthetic
- **21st:** rarely applicable — build custom.
- **Anti-patterns:** using it for anything requiring trust (medical, legal, finance).

## 13. corporate-clean
- **Type:** neutral professional sans, restrained scale, clear hierarchy.
- **Spacing:** predictable 12-column grid, consistent section rhythm.
- **Color:** one brand color, ample neutrals, accessible by default.
- **Motion:** subtle fade-up on scroll, nothing more.
- **Framer:** categories `consulting`, `legal`, `fintech`, `management` · sort Best
- **Pinterest:** "corporate website design", "b2b landing page", chips Website + Layout
- **21st:** "hero section", "logo cloud", "testimonial"
- **Anti-patterns:** looking like every other B2B site — this style needs one deliberate distinctive move or it scores zero on distinctiveness.

## 14. maximalist
- **Type:** multiple families deliberately clashing, extreme scale contrast.
- **Spacing:** dense, layered, content on content.
- **Color:** many, saturated, patterned grounds.
- **Motion:** abundant and simultaneous.
- **Framer:** categories `artists`, `entertainment`, `fashion` · sort New
- **Pinterest:** "maximalist web design", "layered graphic website", chips Creative
- **21st:** rarely applicable — build custom.
- **Anti-patterns:** using it where the task is conversion; maximalism costs comprehension.

## 15. technical-industrial
- **Type:** condensed grotesque display in uppercase (Barlow Condensed, Oswald, Archivo/Archivo Black); mono for specs and data (IBM Plex Mono, Red Hat Mono); small-cap labels with tracking.
- **Spacing:** dense engineered grid, visible hairlines / blueprint grid, spec tables as first-class content.
- **Color:** graphite/steel grounds (#15181c–#23272c, never pure #000), off-white text, one safety accent (orange or yellow), no gradients.
- **Motion:** mechanical — linear or strong ease-out, counters, no bounce, no blur.
- **Framer:** categories `construction`, `software`, `ecommerce` · sort Best
- **Pinterest:** "industrial website design dark", "engineering brand website", "spec sheet ui", chips Web + Layout
- **21st:** "spec table", "configurator", "monospace stat"
- **Anti-patterns:** luxury serif, thin type, gold/metallic, soft shadow, slow fades, glass.

---

## Deriving an unnamed style

Ask which of these the user's words imply, then state the mapping out loud:

| If they say | Nearest |
|---|---|
| "clean", "simple", "like Apple" | swiss-minimal, or dark-luxury if premium |
| "modern", "techy" | bento or glassmorphism |
| "expensive", "high-end" | dark-luxury (consumer) or technical-industrial (equipment, B2B, manufacturing) |
| "industrial", "heavy-duty", "built", "engineered", "steel", "like Caterpillar or DeWalt" | technical-industrial |
| "fun", "young" | neo-brutalist or y2k |
| "trustworthy", "serious" | corporate-clean |
| "warm", "handmade" | organic or retro-print |
| "wow", "immersive", "like a movie" | cinematic-scroll |
