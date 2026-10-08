# Local Development

## Setup

From PowerShell:

```powershell
cd C:\Users\thana\code-repos\HusteDev-Projects\MandalaForge

py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install flask svgwrite
```

If `py` is unavailable, use a known Python executable instead.

## Run The App

```powershell
python -m flask --app app run --host 127.0.0.1 --port 5003 --debug
```

Open:

```text
http://127.0.0.1:5003/
```

The browser bypasses Firebase login on localhost.

## API Smoke Test

```powershell
$body = @{
  seed = 12345
  num_rings = 4
  num_divisions = 12
  complexity = 0.5
  min_pattern_size = 12
  categories = @("botanical","geometric","celtic","art_deco","abstract")
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:5003/generate `
  -ContentType "application/json" `
  -Body $body
```

Expected validation shape:

```json
{
  "is_valid": true,
  "issue_count": 0,
  "unconnected_shape_count": 0,
  "tiny_region_count": 0,
  "issues": []
}
```

## Compile Check

```powershell
python -m compileall app.py coloring_generator.py composer.py placement.py assembler.py resolver.py motifs
```

## Generation Stress Check

This checks generation failures without running the slower full post-generation validator:

```powershell
@'
from coloring_generator import DesignGenerator
import contextlib
import io

cats_all = ["botanical", "geometric", "celtic", "art_deco", "abstract"]
failures = []

for seed in range(1, 101):
    cats = [cats_all[(seed + i) % len(cats_all)] for i in range(1 + (seed % 5))]
    rings = 2 + (seed % 6)
    divs = 6 + 2 * (seed % 10)
    complexity = 0.2 + ((seed * 37) % 9) / 10
    min_size = 5 + (seed * 17) % 36

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            generator = DesignGenerator(
                seed=seed,
                num_rings=rings,
                num_divisions=divs,
                complexity=complexity,
                min_pattern_size=min_size,
                categories=cats,
            )
            generator.generate(validate=False)
    except Exception as exc:
        failures.append((seed, str(exc)))
        print("FAIL", seed, exc)

print("FAIL_COUNT", len(failures))
'@ | python -
```

Expected:

```text
FAIL_COUNT 0
```

## Common Local Port Issue

If `5000` is already occupied, run on another port:

```powershell
python -m flask --app app run --host 127.0.0.1 --port 5004 --debug
```

Use the same port in the browser and API smoke test.
