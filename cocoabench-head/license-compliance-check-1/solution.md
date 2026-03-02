# Solution

### Step 1: Install and inspect dependency tree

```bash
mkdir eslint-audit && cd eslint-audit
npm init -y
npm install eslint@8.57.0
npm ls --all --json > tree.json
```

### Step 2: Collect package/license mapping

Use `license-checker` or parse `node_modules/*/package.json` licenses and normalize SPDX strings.

```bash
npx license-checker --json > licenses.json
npx license-checker --summary
```

### Step 3: Compute required outputs

- Total unique packages (including `eslint`): **99**
- Distinct license types: **7**
- ISC packages sorted alphabetically, first five:
  - `@ungap/structured-clone`
  - `fastq`
  - `flatted`
  - `fs.realpath`
  - `glob`
- `Python-2.0` package: `argparse`
- `Python-2.0` classification: permissive
- Expression containing `CC0-1.0`: `(MIT OR CC0-1.0)`
- Copyleft present (GPL/LGPL/AGPL/MPL): `no`
- Most common license: `MIT`
- Minimum notices = number of license types: `7`

### Final Answer

```json
{
  "total_packages": 99,
  "license_types_count": 7,
  "isc_packages_top5": ["@ungap/structured-clone", "fastq", "flatted", "fs.realpath", "glob"],
  "python2_package": "argparse",
  "python2_type": "permissive",
  "cc0_expression": "(MIT OR CC0-1.0)",
  "has_copyleft": "no",
  "most_common_license": "MIT",
  "min_notices_count": 7
}
```
