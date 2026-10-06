# MandalaForge Documentation

This folder documents the generator architecture and the motif rules that keep generated mandalas colourable.

## Documents

- [Motif Authoring Guide](motifs.md): cell space and limits, the three-layer parametric model, the measured declaration, positions, closure, overflow and reaches, archetypes, traps, and how to add a motif.
- [Architecture](architecture.md): request flow, composer, two-pass assembly, validation, and the API response shape.
- [Cell Composition Contract](CELL_COMPOSITION_CONTRACT.md): proposed guide-independent, multi-motif cells, controlled overflow, and changes needed for the annotated four-ring reference.
- [Pattern Category Audit](pattern-category-audit.md): active pattern status, dormant legacy inventory, and recommended next patterns.
- [Motif Inventory](motif-inventory.md): motifs extracted from `examples/`, mapped against registered patterns, with the gaps ranked.
- [Local Development](local-development.md): setup, run commands, and quick verification commands.

## Core Terms

- **Ring**: one circular band of the design. Each ring has its own division count.
- **Cell**: one ring times one division, a wedge-shaped drawing area.
- **Position**: where a motif sits in a cell, on its centreline (`centre`) or on its clockwise edge (`divider`).
- **Motif**: one parametric drawing placed in a cell: a base, a slot child nested inside an enclosing motif, or an attachment that reaches toward the ring inside.
- **Plan**: the composer's decision, from the seed, of what every ring contains, before anything is drawn.

## Current Design Rule

Motifs are generated in normalised cell space before they become SVG. Ring boundaries and division lines are never drawn, so every open end of every motif must land on ink, and every base motif must be connected to the rest of the design. Every enclosed space must be large enough to colour at the configured minimum size.
