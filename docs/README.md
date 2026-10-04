# MandalaForge Documentation

This folder documents the current generator architecture and the smart-cell rules that keep generated mandalas colorable.

## Documents

- [Cell Composition Contract](CELL_COMPOSITION_CONTRACT.md): proposed guide-independent, multi-motif cells, controlled overflow, and changes needed for the annotated four-ring reference.
- [Architecture](architecture.md): request flow, generator responsibilities, and SVG assembly.
- [Smart Patterns](smart-patterns.md): cell-space coordinates, vector rules, minimum white-space behavior, and fallback generation.
- [Pattern Category Audit](pattern-category-audit.md): active pattern status, dormant legacy inventory, and recommended next patterns.
- [Motif Inventory](motif-inventory.md): motifs extracted from `examples/`, mapped against registered patterns, with the gaps ranked.
- [Local Development](local-development.md): setup, run commands, and quick verification commands.

## Core Terms

- **Cell**: one drawing area in a ring. The app repeats each cell around the center.
- **Segment**: one radial slice from the center toward the outside edge.
- **Ring/layer**: one circular band made of one cell per segment.
- **Design**: the lines and shapes drawn inside one cell.
- **Pattern**: one reusable design element.

## Current Design Rule

Patterns are generated in normalized cell space before they become SVG. A pattern must either connect to the cell boundary in a way that repeats cleanly, connect to another vector, or create a colorable space above the configured minimum size.
