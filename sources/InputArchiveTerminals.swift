//
//  InputArchiveTerminals.swift
//  Squirrel
//
//  Observed terminal outcomes for one frontend composition. A terminal is
//  recorded from what this frontend actually observed; an insert call returning
//  proves only that observed call, never host persistence.
//

import Foundation

extension InputArchiveEngine {
  func recordCommit(_ text: String, schema: String) {
    admitTerminal(
      kind: "commit_attempt",
      outcome: "observed_attempt",
      text: String(text),
      schema: schema,
      clientPresent: true
    )
  }

  func recordRaw(_ text: String, schema: String) {
    admitTerminal(
      kind: "raw_finalization",
      outcome: "raw_finalized",
      text: String(text),
      schema: schema,
      clientPresent: true
    )
  }

  func recordUnavailable(schema: String) {
    admitTerminal(kind: "unavailable_client", outcome: "unavailable_client", text: nil, schema: schema, clientPresent: false)
  }

  func recordCancellation(schema: String) {
    admitTerminal(kind: "cancellation", outcome: "cancelled", text: nil, schema: schema, clientPresent: true)
  }

  // periphery:ignore
  func recordUnknown(schema: String) {
    admitTerminal(kind: "unknown_outcome", outcome: "unknown", text: nil, schema: schema, clientPresent: true)
  }

  func admitTerminal(kind: String, outcome: String, text: String?, schema: String, clientPresent: Bool) {
    if !clientPresent && kind != "unavailable_client" {
      closeExcludedComposition()
      return
    }
    if measurementSuppressed {
      closeExcludedComposition()
      return
    }
    // Unavailable uses the same capture, secure, and schema gates. It must not
    // open a process or persist a Luna label for a non-Luna or unknown schema.
    if !producer.captureEnabled() {
      closeExcludedComposition()
      return
    }
    if InputArchiveSignals.secureEventInputEnabled() {
      closeExcludedComposition()
      admitExclusion()
      return
    }
    // Cached or hard-coded Luna identity is not proof. Unknown and other schemas exclude without text.
    if schema != InputArchive.supportedSchema {
      closeExcludedComposition()
      admitExclusion()
      return
    }
    lock.lock()
    if compositionUnobserved {
      // The composition that this terminal closes was never observed from its
      // start, so its text is not eligible. The observed terminal outcome is
      // still reported as a content-free exclusion notice.
      lock.unlock()
      closeExcludedComposition()
      admitExclusion()
      return
    }
    if !processOpen {
      processId = InputArchiveTokens.fresh("proc")
    }
    let process = processId
    let segment = segmentId
    let update = InputArchiveTokens.fresh("upd")
    let parent = parentUpdateId
    let commitId = InputArchiveTokens.fresh("cmt")
    processOpen = false
    associationValid = false
    lastPreedit = ""
    lastInputLength = 0
    lastRecordedPreedit = ""
    compositionUnobserved = false
    parentUpdateId = nil
    updateId = ""
    lock.unlock()
    var fields = baseFields(kind: kind, outcome: outcome, process: process, segment: segment, schema: schema)
    fields["update_id"] = update
    fields["commit_id"] = commitId
    if let parent {
      fields["parent_update_id"] = parent
    }
    fields["stage"] = "frontend_commit_call"
    fields["host_persistence"] = "unknown"
    if let text, kind != "unavailable_client" {
      fields["payload"] = [
        "text": text,
        "operation": kind,
        "host_persistence": "unknown",
        "clock_domain": "mach_absolute_time"
      ]
    } else {
      fields["payload"] = [
        "operation": kind,
        "host_persistence": "unknown",
        "client_present": clientPresent
      ]
    }
    _ = admit(fields)
  }

  func admitExclusion() {
    lock.lock()
    let process = processId
    let segment = segmentId
    lock.unlock()
    var fields = baseFields(kind: "exclusion_notice", outcome: "unknown", process: process, segment: segment, schema: "unknown")
    fields["eligibility"] = "excluded"
    fields["reason"] = "deliberate_exclusion"
    fields["schema_id"] = "unknown"
    fields["payload"] = NSNull()
    _ = admit(fields)
  }

  /// A terminal refused for privacy/policy reasons ends a composition that was
  /// never fully observed. Keep the boundary content-free instead of letting a
  /// later admitted snapshot carry the unobserved prefix.
  func markCompositionUnobserved() {
    lock.lock()
    compositionUnobserved = true
    lock.unlock()
  }

  private func closeExcludedComposition() {
    lock.lock()
    processOpen = false
    associationValid = false
    lastPreedit = ""
    lastInputLength = 0
    lastRecordedPreedit = ""
    compositionUnobserved = false
    parentUpdateId = nil
    updateId = ""
    lock.unlock()
  }

  /// An empty pending composition is a boundary, not an unavailable client.
  /// Close the unobserved flag without opening a process or persisting a row.
  func noteEmptyInputBoundary() {
    closeExcludedComposition()
  }
}
