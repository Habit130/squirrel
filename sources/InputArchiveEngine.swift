//
//  InputArchiveEngine.swift
//  Squirrel
//
//  Frontend observation state. Admission is a bounded owned snapshot only.
//  Session metadata is content-free and is not an LM request join.
//

import AppKit
import Foundation

final class InputArchiveEngine {
  static let shared = InputArchiveEngine()

  let lock = NSLock()
  let producer = InputArchiveProducer()
  private var sequence = 0
  var processId = InputArchiveTokens.fresh("proc")
  var segmentId = InputArchiveTokens.fresh("seg")
  var updateId = ""
  var parentUpdateId: String?
  var processOpen = false
  var associationValid = false
  private var pendingOperation = "key_update"
  private var configuredSocket = ""
  var measurementSuppressed = false
  private var lastCaptureEnabled = false
  var lastPreedit = ""
  var lastInputLength = 0
  var lastRecordedPreedit = ""
  var compositionUnobserved = false
  var timing = InputArchiveTiming()
  private var metadataPublishedBeforeEngine = false

  private init() {}

  func reloadConfiguration() {
    let socket = NSApp.squirrelAppDelegate.config?.getString(InputArchive.socketConfigKey) ?? ""
    bind(socket: socket)
  }

  // periphery:ignore
  func bind(socket: String) {
    lock.lock()
    let changed = configuredSocket != socket
    configuredSocket = socket
    if changed {
      segmentId = InputArchiveTokens.fresh("seg")
      associationValid = false
      updateId = ""
      parentUpdateId = nil
      lastCaptureEnabled = false
      if processOpen {
        compositionUnobserved = true
      }
    }
    lock.unlock()
    if InputArchivePaths.refusal(for: socket) != nil && !socket.isEmpty {
      producer.bind(socketPath: "")
      return
    }
    producer.bind(socketPath: socket)
  }

  // periphery:ignore
  func setMeasurementSuppressed(_ suppressed: Bool) {
    lock.lock()
    measurementSuppressed = suppressed
    lock.unlock()
  }

  func beginAction(_ name: String, eventTimestamp: TimeInterval?) {
    lock.lock()
    timing = InputArchiveTiming()
    timing.action = name
    timing.entryTicks = InputArchiveClock.now()
    timing.eventQueueWait = Self.queueWait(eventTimestamp)
    metadataPublishedBeforeEngine = false
    lock.unlock()
  }

  func finishAction() {
    lock.lock()
    timing.returnTicks = InputArchiveClock.now()
    lock.unlock()
  }

  func markEndpoint(_ name: String) {
    lock.lock()
    timing.primaryEndTicks = InputArchiveClock.now()
    timing.endpoint = name
    lock.unlock()
  }

  func notePendingOperation(_ operation: String) {
    lock.lock()
    pendingOperation = operation
    lock.unlock()
  }

  func publishMetadata(_ setter: (String, String) -> Void) {
    let started = InputArchiveClock.now()
    lock.lock()
    if updateId.isEmpty {
      updateId = InputArchiveTokens.fresh("upd")
    }
    let fields = [
      (InputArchive.propertySource, producer.sourceId),
      (InputArchive.propertyProcess, processId),
      (InputArchive.propertyUpdate, updateId),
      (InputArchive.propertySegment, segmentId),
      (InputArchive.propertyAssociation, associationValid ? "valid" : "invalid")
    ]
    lock.unlock()
    for (key, value) in fields where InputArchiveTokens.isSafe(value) {
      setter(key, value)
    }
    let elapsed = InputArchiveClock.nanoseconds(from: InputArchiveClock.now() &- started)
    lock.lock()
    timing.metadataNs &+= elapsed
    metadataPublishedBeforeEngine = true
    lock.unlock()
  }

  func invalidateMetadata() {
    lock.lock()
    associationValid = false
    updateId = ""
    lock.unlock()
  }

  func noteContinuityCut(_ reason: String) {
    lock.lock()
    segmentId = InputArchiveTokens.fresh("seg")
    associationValid = false
    updateId = ""
    if reason == "session_recreation" || reason == "deactivation" || reason == "restart" {
      processOpen = false
      processId = InputArchiveTokens.fresh("proc")
      lastPreedit = ""
      lastInputLength = 0
      lastRecordedPreedit = ""
      compositionUnobserved = false
    }
    lock.unlock()
  }

  func observe(_ snapshot: InputArchiveSnapshot) {
    notePolicyEdge()
    let started = InputArchiveClock.now()
    let owned = InputArchiveOwnedPage(snapshot)
    let copyNs = InputArchiveClock.nanoseconds(from: InputArchiveClock.now() &- started)
    let hasContent = !owned.preedit.isEmpty || owned.inputLength > 0 || !owned.candidates.isEmpty
    lock.lock()
    timing.copyNs &+= copyNs
    let operation = pendingOperation
    let previous = lastPreedit
    let previousLength = lastInputLength
    lastPreedit = owned.preedit
    lastInputLength = owned.inputLength
    // An empty observation is the empty/terminal boundary of any composition. A
    // composition whose earlier prefix was never observed stops excluding here,
    // and this boundary is reached before any early return below.
    if !hasContent {
      compositionUnobserved = false
      lastRecordedPreedit = ""
    }
    lock.unlock()
    if !hasContent && operation != "escape" && !processOpen {
      return
    }
    if !mayAdmit(schema: owned.schemaId, clientPresent: owned.clientPresent) {
      // Opt-out, pause, ineligibility or an excluded/unsupported schema. The
      // content of this observation was not recorded, so the composition may
      // carry a prefix that was never observed. It stays excluded unless the
      // next eligible observation continues the recorded prefix exactly, which
      // proves nothing was hidden (E2/E3 no-backfill).
      if hasContent {
        markCompositionUnobserved()
      }
      if shouldExclude(schema: owned.schemaId) {
        admitExclusion()
      }
      return
    }
    lock.lock()
    let unobserved = compositionUnobserved
    lock.unlock()
    // A composition that was ineligible at any observed point stays excluded
    // until its empty/terminal boundary. Continuing the last recorded preedit
    // does not prove that nothing was typed while capture was paused or secure
    // input was active, so it must not resume capture from a full snapshot.
    if unobserved {
      admitExclusion()
      return
    }
    if !processOpen && hasContent {
      openProcess(schema: owned.schemaId)
    }
    let kind = classify(
      operation: operation,
      previous: previous,
      previousLength: previousLength,
      current: owned
    )
    if kind == "cancellation" {
      recordCancellation(schema: owned.schemaId)
      return
    }
    admitPage(kind: kind, outcome: outcome(for: kind), page: owned, operation: operation)
  }

  // periphery:ignore
  func admitFixture(_ observation: [String: Any]) -> InputArchiveAdmission {
    var copy = observation
    copy["source_instance_id"] = producer.sourceId
    if copy["source_local_sequence"] == nil {
      copy["source_local_sequence"] = nextSequence()
    }
    copy["envelope_version"] = InputArchive.envelopeVersion
    copy["content_version"] = InputArchive.contentVersion
    return producer.admit(copy)
  }

  // periphery:ignore
  func contentFreeStatus() -> [String: String] {
    var status = producer.localStatus()
    lock.lock()
    status["configured"] = configuredSocket.isEmpty ? "false" : "true"
    status["measurement_suppressed"] = measurementSuppressed ? "true" : "false"
    status["segment_id"] = segmentId
    status["process_id"] = processId
    status["source_local_sequence"] = String(sequence)
    status["association"] = associationValid ? "valid" : "invalid"
    status["metadata_before_engine"] = metadataPublishedBeforeEngine ? "true" : "false"
    status["composition_unobserved"] = compositionUnobserved ? "true" : "false"
    status["endpoint"] = timing.endpoint
    status["action"] = timing.action
    status["legacy_selection_recording"] = "separately_configured_may_continue"
    status["legacy_switch_changed"] = "false"
    status["globally_effective"] = "false"
    status["content_included"] = "false"
    lock.unlock()
    return status
  }

  // periphery:ignore
  func lastTiming() -> InputArchiveTiming {
    lock.lock()
    defer { lock.unlock() }
    return timing
  }

  // periphery:ignore
  func waitUntilDrained(timeout: TimeInterval) -> Bool {
    producer.waitUntilDrained(timeout: timeout)
  }

  // periphery:ignore
  var sourceInstanceId: String { producer.sourceId }

  private func notePolicyEdge() {
    let enabled = producer.captureEnabled() && !measurementSuppressed
    lock.lock()
    let changed = enabled != lastCaptureEnabled
    lastCaptureEnabled = enabled
    // Losing capture eligibility mid-composition makes that composition's
    // earlier prefix unobserved for the new segment.
    if changed && !enabled {
      compositionUnobserved = true
    }
    lock.unlock()
    if changed {
      noteContinuityCut(enabled ? "resume" : "pause")
    }
  }

  private func mayAdmit(schema: String, clientPresent: Bool) -> Bool {
    if measurementSuppressed || !clientPresent {
      return false
    }
    if InputArchiveSignals.secureEventInputEnabled() {
      return false
    }
    if schema != InputArchive.supportedSchema {
      return false
    }
    return producer.captureEnabled()
  }

  private func shouldExclude(schema: String) -> Bool {
    if measurementSuppressed || !producer.captureEnabled() {
      return false
    }
    return schema != InputArchive.supportedSchema || InputArchiveSignals.secureEventInputEnabled()
  }

  private func openProcess(schema: String) {
    lock.lock()
    processOpen = true
    processId = InputArchiveTokens.fresh("proc")
    associationValid = true
    updateId = InputArchiveTokens.fresh("upd")
    parentUpdateId = nil
    let process = processId
    let segment = segmentId
    lock.unlock()
    var fields = baseFields(kind: "start", outcome: "input_change", process: process, segment: segment, schema: schema)
    fields["payload"] = ["stage": "frontend_process_start", "host_persistence": "unknown"]
    _ = admit(fields)
  }

  private func admitPage(kind: String, outcome: String, page: InputArchiveOwnedPage, operation: String) {
    lock.lock()
    let process = processId
    let segment = segmentId
    let parent = parentUpdateId
    let update = InputArchiveTokens.fresh("upd")
    parentUpdateId = update
    updateId = update
    associationValid = true
    lastRecordedPreedit = page.preedit
    lock.unlock()
    var fields = baseFields(kind: kind, outcome: outcome, process: process, segment: segment, schema: page.schemaId)
    fields["update_id"] = update
    if let parent {
      fields["parent_update_id"] = parent
    }
    fields["stage"] = "frontend_update"
    fields["payload"] = page.payload(operation: operation, timing: lastTiming())
    fields["host_persistence"] = "unknown"
    _ = admit(fields)
  }


  func admit(_ fields: [String: Any]) -> InputArchiveAdmission {
    let started = InputArchiveClock.now()
    let result = producer.admit(fields)
    let elapsed = InputArchiveClock.nanoseconds(from: InputArchiveClock.now() &- started)
    lock.lock()
    timing.admissionNs &+= elapsed
    if !result.admitted && (result.code == "queue_saturated" || result.code == "capacity_stop") {
      segmentId = InputArchiveTokens.fresh("seg")
      associationValid = false
    }
    lock.unlock()
    return result
  }

  func baseFields(kind: String, outcome: String, process: String, segment: String, schema: String) -> [String: Any] {
    [
      "envelope_version": InputArchive.envelopeVersion,
      "content_version": InputArchive.contentVersion,
      "schema_id": schema,
      "source_instance_id": producer.sourceId,
      "source_local_sequence": nextSequence(),
      "observation_kind": kind,
      "process_id": process,
      "continuity_segment_id": segment,
      "outcome": outcome,
      "eligibility": "included",
      "host_persistence": "unknown",
      "clocks": [
        "observation_time": Double(InputArchiveClock.nanoseconds(from: InputArchiveClock.now())) / 1_000_000.0,
        "clock_domain": "mach_absolute_time"
      ]
    ]
  }

  private func nextSequence() -> Int {
    lock.lock()
    defer { lock.unlock() }
    sequence += 1
    return sequence
  }

  private func classify(operation: String, previous: String, previousLength: Int, current: InputArchiveOwnedPage) -> String {
    if operation == "escape" && current.preedit.isEmpty {
      return "cancellation"
    }
    if operation == "backspace" || current.inputLength < previousLength || current.preedit.count < previous.count {
      return "replacement"
    }
    if operation == "number_select" || operation == "mouse_selection" {
      return "temporary_selection"
    }
    return "input_change"
  }

  private func outcome(for kind: String) -> String {
    switch kind {
    case "replacement": return "replacement"
    case "temporary_selection": return "temporary_selection"
    case "cancellation": return "cancelled"
    default: return "input_change"
    }
  }

  private static func queueWait(_ timestamp: TimeInterval?) -> String {
    guard let timestamp, timestamp > 1 else { return "unknown" }
    return "unknown"
  }
}
