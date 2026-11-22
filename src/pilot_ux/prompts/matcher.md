You compare an automated usability tool's issue list against a reference list of known issues for the same product.

Reference issues (from human reviewers):
$truth

Issues the tool reported:
$issues

For each reference issue, give the id of the tool issue that reports the same underlying problem, or null. Matching needs the same problem in the same area, not just the same screen. A broader tool issue that clearly includes it counts.
For each tool issue, give a label:
- "matches_truth": it reports one of the reference issues.
- "stale": it matches a reference issue marked stale (already fixed). Reporting it is an error.
- "novel": it is not in the reference list. Also judge plausible=true if a careful human reviewer looking at the evidence would likely agree it's a real problem, false if it looks like a hallucination, a misreading or pure taste.
