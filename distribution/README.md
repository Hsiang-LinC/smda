# SMDA Plugin Distribution

Private installable releases of the SMDA Automation plugin for macOS arm64 and
x86_64.

```bash
codex plugin marketplace add git@github.com:Hsiang-LinC/smda-plugin-dist.git
codex plugin add smda-automation@smda
```

The SMDA executable bundles Python 3.12 and its Python dependencies. Python and
uv are not consumer prerequisites. The bundled Sandcastle runner still
requires a compatible Node runtime.
