# Shared editor fonts

These font files ship with the editor so Windows and macOS do not select
different installed fonts.

- Fio UI is derived from Selawik 1.01, Microsoft's open replacement for Segoe UI, from
  https://github.com/microsoft/Selawik/releases/tag/1.01
  (license in Selawik-OFL.txt). The modified fonts are renamed in accordance
  with the reserved font name requirement. Their hhea and OS/2 typographic
  ascent/descent are set to the original Windows ascent/descent, line gaps
  are zero, and USE_TYPO_METRICS is enabled. CoreText and Windows therefore
  use the same line metrics instead of two different sets within one font.
- IBM Plex Mono Regular and Bold: from
  https://github.com/google/fonts/tree/main/ofl/ibmplexmono
  (unmodified font files; license in IBMPlexMono-OFL.txt).

Both use the SIL Open Font License 1.1. The application loads the fonts
directly through Qt; installation on the operating system is unnecessary.
