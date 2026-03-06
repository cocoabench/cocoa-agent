Analyze the license compliance of npm package **jest@29.7.0** for a commercial software project.

Jest is MIT licensed, but your legal team needs a full dependency-tree license audit before shipping proprietary software.

**Requirements:**
- Install the exact package version `jest@29.7.0` using npm
- Research unfamiliar license entries online
- Use package names only (no versions) in the final answer

**Tasks:**

1. Install `jest@29.7.0` and inspect all transitive dependencies
2. Identify unique packages and license distribution
3. Detect attribution and unknown-license risk
4. Evaluate copyleft disclosure risk

**Answer the following questions:**

1. How many unique packages are in the dependency tree (including jest itself)?
2. How many distinct license types are present?
3. List the first 8 packages (alphabetically) using the "BSD-3-Clause" license.
4. Which package uses the "BSD-2-Clause" license?
5. Are there any packages with `UNKNOWN` license metadata? Answer "yes" or "no"
6. Which license expression includes `CC0-1.0` as an option?
7. Are there any copyleft licenses (GPL, LGPL, AGPL, MPL) requiring source disclosure? Answer "yes" or "no"
8. What is the most common license type?
9. What is the minimum number of different license notices required in a NOTICES file?

**Output Format:**

Submit your answer in the following format:

<answer>
```json
{
  "total_packages": packages_num,
  "license_types_count": types_count,
  "bsd3_packages_top8": ["pkg1", "pkg2", "pkg3", "pkg4", "pkg5", "pkg6", "pkg7", "pkg8"],
  "bsd2_package": "package-name",
  "has_unknown_license": "yes",
  "cc0_expression": "LICENSE-EXPRESSION",
  "has_copyleft": "no",
  "most_common_license": "MIT",
  "min_notices_count": min_notices_count
}
```
</answer>

**Notes:**
- Helpful commands: `npm ls --all --json`, `npx license-checker --json`, `npx license-checker --summary`
- Keep package-name answers normalized and version-free.
