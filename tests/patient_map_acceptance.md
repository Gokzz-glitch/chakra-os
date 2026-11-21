# Doctor history map acceptance cases

Target CHAKRA OS in project girpolypposframesrealcolon, Mumbai. Use invented records only. Run the cloud checks with `python3 cloud_console_checks.py`. Exit 1 means at least one release criterion failed. A missing CLI login or permission is an environment error. The checks read service metadata, the invoker policy and the advertised doctor page. They do not exercise inference or generate a report.

## First version

In the doctor screen, add **History** beside the active procedure. Show the selected patient, hospital and encounter above the map. Start with visits ordered by clinical date. Expand a visit into findings. Selecting a finding opens its frame and time, review decision, and pathology status. A late signed report gets its own event and source. Keep an equivalent keyboard-accessible list, a text legend, filters for pending results and a link back to the procedure. Use the PMB map's selection, search, zoom and legend as interaction references. Keep the personal memory service and its records outside the clinical system.

Persist events in the existing cloud stack, addressed by hospital, patient, encounter, finding and immutable event ID. Record observed time, recorded time, source record version, authenticated actor and event type. Link corrected results to the event they supersede. Resolve media through the same authorization policy as the encounter. Build map nodes and edges on the server from those records. Use explicit relationships such as “observed in”, “reviewed by” and “amends”. A deterministic timeline with expandable links is sufficient for the first two visits. A graph database or an LLM-generated relationship is unnecessary for that query.

The current OS source uses an in-process patient registry and a caller-supplied hospital header. A history read creates an unknown patient's record. The pathology handler replaces the prior result and accepts the signer from the submitted data. The demo assembles follow-up intervals using diagnosis text matching. Keep those intervals out of the proposed map until a clinician independently verifies a recommendation against the source record. The existing Review Studio Cloud Storage adapter is a useful reference, but it belongs to a separate service.

## Acceptance matrix

| Case | Setup and action | Expected result | Current evidence |
|---|---|---|---|
| Find the evidence | Give the doctor two synthetic visits. Ask them to find the image behind an accepted finding. | Correct visit, frame, timestamp and clinician decision open together. Back returns to the same finding. | Existing history fixture includes an evidence URL. Map interaction untested. |
| Identify missing pathology | Open a reviewed finding before the lab has signed a result. | Pending is visible as text. No tissue diagnosis or follow-up interval is inferred. | API workflow tested locally. Visual and recommendation checks pending. |
| Reconcile a late result | Add a signed synthetic report and then a corrected version in a test deployment. Reload. | Both versions, dates and signers remain inspectable. The original review decision is preserved. | First reconciliation tested. Source currently overwrites the previous result. |
| Preserve disagreement | Dismiss a candidate and open the history with and without the audit filter. | Dismissal stays in the audit view and contributes zero confirmed findings. | Local dismissed fixture passed. Map filter untested. |
| Establish identity and access | Use two approved synthetic clinician accounts from different hospitals with the same local patient number. Check the server's authorization decisions for the chart and media. | Only the assigned clinician can read the correct record. Signing requires the appropriate role. The audit entry identifies the authenticated actor. | Header mismatch covered by a fixture. Authenticated identity, permissions and media access remain release gates. |
| Handle absent evidence | Use a test record with an unavailable frame. Open its finding. | Show “Source unavailable”, keep the recorded decision visible and avoid substituting another frame. | Proposed. |
| Unknown patient | Look up an unregistered synthetic patient in the fixture. | Read-only empty result or 404. The registry size remains unchanged. | Current OS source creates a record on read. |
| Persist and retry | Submit the same synthetic signed event twice, restart the test instance and reopen the visit. | One event, stable identity, same original source and decision after restart. Conflicting edits require an explicit amendment. | OS history uses process memory. Pending. |
| Accessible review | Use keyboard only, at 200% zoom and with reduced motion. Open a finding and return. | Focus is restored. Text distinguishes pending, signed and dismissed. The list provides the same sources as the map. | Proposed. |
| Source disagreement | Give a synthetic draft a statement with a missing or superseded source. | The UI identifies the affected sentence and offers the underlying signed record. No unsupported sentence becomes a chart fact. | Proposed for OS. |
| Cost and privacy | Open the map and expand an existing finding. Inspect service telemetry with synthetic data. | No GPU warmup or Gemini call for ordinary navigation. Analytics contain aggregate counts. Logs omit patient text and media URLs with credentials. | CPU scale settings checked. Navigation telemetry and log minimization pending. |

## Mentor demonstration

Give a clinician two tasks without coaching: “Which finding is waiting for pathology?” and “Show me what changed after the lab signed.” Record time to the correct source, wrong-patient or wrong-visit selections, and whether they can distinguish a model suggestion from a signed conclusion. Compare with the existing timeline on equivalent cases. State the observed result and sample size. A clickable history establishes the provenance of the clinical record. Detector accuracy and the model's internal reasoning require separate evidence.
