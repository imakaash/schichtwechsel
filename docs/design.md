# Design

## Idea

*Schichtwechsel* is the change of shift. The palette takes its two poles from it: a steel blue for the night shift and an amber for the morning shift, on warm paper in light mode and deep ink in dark mode. Type is Schibsted Grotesk for text and headings, JetBrains Mono for SQL. No logos, no brand colours of any retailer.

## Palette

| Role | Light (surface `#f7f5f0`) | Dark (surface `#141a22`) |
|---|---|---|
| Series 1, "Nacht" | `#1f64b0` | `#3f84d1` |
| Series 2, "Morgen" | `#c7761a` | `#c27a22` |
| Series 3 | `#2a9d8f` | `#2fa595` |
| Sequential (one hue) | `#e3ebf4` to `#153a66`, 7 steps | `#23324a` to `#c9dbf2`, 7 steps |
| Diverging | blue, grey `#e8e3d8` at 100, amber | blue, grey `#2a313b` at 100, amber |

Validated with the dataviz palette checks (lightness band, chroma floor, colour-vision-deficiency separation, normal-vision separation, contrast against the surface):

- The three series colours pass every check under **all pairs**, in both modes, without warnings. They can be used together in any chart form.
- Sequential and diverging arms are single-hue and monotone in lightness with visible steps. Their lightest light-mode step is allowed to fade into the surface: it means "near zero" on a continuous scale.

## Rules the charts follow

- A competitor comparison is one series: bars in one hue, names on the axis, values at the bar ends. Colour is never the only carrier of identity.
- Hiring pressure has a natural midpoint (100 = national rate), so the map is diverging; everything else that measures size is sequential.
- The map is a tile grid of the 16 Bundesländer, equal squares placed roughly where they sit. Bremen and Saarland stay as visible as Bayern, and no map data or licence is needed.
- Text is in ink colours, never in a series colour. Strong blue tiles get light text; amber tiles keep dark ink.
- Every chart has hover details, and the main ones have a table view.
- Numbers follow the UI language: 1.234,5 in German, 1,234.5 in English.
