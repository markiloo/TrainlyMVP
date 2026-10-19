# Trainly MVP visual identity

**Direction:** Deep navy, warm gold, and Poppins. The visual tone should feel focused and credible while making lesson progress and quiz actions easy to spot.

## Palette

| Role | Hex | Use |
| --- | --- | --- |
| Midnight | `#0B1F3A` | Navigation, hero, primary text on light surfaces |
| Deep blue | `#132E50` | Dark cards and hover surfaces |
| Gold | `#D8AD54` | Primary buttons, active progress, key highlights |
| Light gold | `#E7C275` | Hover and focus emphasis |
| Warm ivory | `#F7F5EF` | Page surfaces and text on navy |
| Mist | `#B9C6D6` | Secondary text on navy |
| Slate | `#52647A` | Secondary text on ivory |

The [HTML preview](./color_preview.html) shows these colors in a sample creator dashboard and learner player.

## Typography

- **Font family:** Poppins, with a sans serif fallback.
- **Poppins Bold (700):** page titles, section headings, important numbers, and primary button labels.
- **Poppins Light (300):** body copy, lesson descriptions, and supporting text. Use at least 16 px for normal reading text with generous line spacing.
- Use sentence case for interface labels. Avoid long lines of all caps or gold body text.

## Component rules

- Use navy for the app header and key framing. Use ivory for reading and editing surfaces so longer transcripts remain comfortable to scan.
- Use gold for the primary action and active learning state. Keep secondary actions outlined or text only.
- Use navy text on gold buttons and ivory backgrounds. Use ivory or mist text on navy backgrounds.
- Use a visible light gold focus ring for keyboard navigation. Status meaning also needs text or an icon; color alone is insufficient.
- Keep gold sparse: one primary action per screen, progress cues, and a few key highlights.

## CSS tokens

```css
:root {
  --color-midnight: #0b1f3a;
  --color-deep-blue: #132e50;
  --color-gold: #d8ad54;
  --color-gold-light: #e7c275;
  --color-ivory: #f7f5ef;
  --color-mist: #b9c6d6;
  --color-slate: #52647a;
  --font-ui: "Poppins", Arial, sans-serif;
  --font-light: 300;
  --font-bold: 700;
}
```

The key text pairings have contrast ratios above 4.5:1: ivory on midnight 15.15:1, gold on midnight 7.89:1, mist on midnight 9.53:1, and slate on ivory 5.56:1. These values cover color contrast; the final interface still needs review for font size, focus, and interactive states.
