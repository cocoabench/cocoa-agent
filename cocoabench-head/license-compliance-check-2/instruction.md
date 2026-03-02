Analyze the license compliance of npm package **webpack@5.88.2** for a commercial software project.

Webpack is MIT licensed, but you must audit its full dependency set to confirm legal compatibility for proprietary redistribution.

**Requirements:**
- You must use npm to install the exact version `webpack@5.88.2`
- Research unfamiliar licenses online where needed
- Package names in your answer must not include version numbers

**Tasks:**

1. Install `webpack@5.88.2` and analyze its dependency tree
2. Identify all unique packages and their licenses
3. Check for attribution-oriented licenses and copyleft risk
4. Summarize legal notice requirements

**Answer the following questions:**

1. How many unique packages are in the dependency tree (including webpack itself)?
2. How many distinct license types are used?
3. List all packages using the "Apache-2.0" license (package names only, sorted alphabetically).
4. Which package uses the "CC-BY-4.0" license?
5. Is "CC-BY-4.0" permissive or copyleft?
6. How many packages use "BSD-2-Clause"?
7. Are there any copyleft licenses (GPL, LGPL, AGPL, MPL) in this tree? Answer "yes" or "no"
8. What is the most common license type in this dependency tree?
9. What is the minimum number of distinct notices needed in a NOTICES file?

**Output Format:**

Submit your answer in the following format:

<answer>
```json
{
  "total_packages": packages_num,
  "license_types_count": types_count,
  "apache_packages": ["pkg1", "pkg2", "pkg3"],
  "cc_by_4_package": "package-name",
  "cc_by_4_type": "attribution",
  "bsd2_count": count,
  "has_copyleft": "no",
  "most_common_license": "MIT",
  "min_notices_count": min_notices_count
}
```
</answer>

**Notes:**
- Recommended commands: `npm ls --all --json`, `npx license-checker --json`, `npx license-checker --summary`
