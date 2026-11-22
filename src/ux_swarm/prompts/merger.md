You merge usability findings from many independent test sessions of the same product into a de-duplicated issue list.

Below, as JSON, are findings. Each has an id, the session it came from, the screen/element, the description and the severity.

$findings

Group findings that describe the SAME underlying problem (same screen element and same cause), even if worded differently. Keep different problems on the same screen as separate issues. Every finding id must go into exactly one issue. For each issue write a short neutral title, a one-paragraph description, and the single best concrete fix. List the member finding ids. Don't drop findings with severity 0 or prototype gaps; group them like the rest.
