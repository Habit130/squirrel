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

  private let lock = NSLock()
  private let producer = InputArchiveProducer()
  private var sequence = 0
  private var processId = InputArchiveTokens.fresh("proc")
  private var segmentId = InputArchiveTokens.fresh("seg")
  private var updateId = ""
  private var parentUpdateId: String?
  private var processOpen = false
  private var associationValid = false
  private var pendingOperation = "key_update"
  private var configuredSocket = ""
  private var measurementSuppressed = false
  private var lastCaptureEnabled = false
  private var lastPreedit = ""
  private var lastInputLength = 0
  private var timing = InputArchiveTiming()
  private var metadataPublishedBeforeEngine = false

  private init() {}

  func reloadConfiguration() {
    let socket = NSApp.squirrelAppDelegate.config?.getString(InputArchive.socketConfigKey) ?? ""
    bind(socket: socket)
  }

  // periphery:ignore
  func bind(socket: String) {
    lock.lock()
    configuredSocket = socket
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
    }
    lock.unlock()
  }

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

  func observe(_ snapshot: InputArchiveSnapshot) {
    notePolicyEdge()
    let started = InputArchiveClock.now()
    let owned = OwnedPage(snapshot)
    let copyNs = InputArchiveClock.nanoseconds(from: InputArchiveClock.now() &- started)
    lock.lock()
    timing.copyNs &+= copyNs
    let operation = pendingOperation
    let previous = lastPreedit
    let previousLength = lastInputLength
    lastPreedit = owned.preedit
    lastInputLength = owned.inputLength
    lock.unlock()
    if owned.preedit.isEmpty && owned.candidates.isEmpty && operation != "escape" && !processOpen {
      return
    }
    if !mayAdmit(schema: owned.schemaId, clientPresent: owned.clientPresent) {
      if shouldExclude(schema: owned.schemaId) {
        admitExclusion()
      }
      return
    }
    if !processOpen && (!owned.preedit.isEmpty || owned.inputLength > 0 || !owned.candidates.isEmpty) {
      openProcess()
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
    status["association"] = associationValid ? "valid" : "invalid"
    status["metadata_before_engine"] = metadataPublishedBeforeEngine ? "true" : "false"
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

  private func openProcess() {
    lock.lock()
    processOpen = true
    processId = InputArchiveTokens.fresh("proc")
    associationValid = true
    updateId = InputArchiveTokens.fresh("upd")
    parentUpdateId = nil
    let process = processId
    let segment = segmentId
    lock.unlock()
    var fields = baseFields(kind: "start", outcome: "input_change", process: process, segment: segment)
    fields["payload"] = ["stage": "frontend_process_start", "host_persistence": "unknown"]
    _ = admit(fields)
  }

  private func admitPage(kind: String, outcome: String, page: OwnedPage, operation: String) {
    lock.lock()
    let process = processId
    let segment = segmentId
    let parent = parentUpdateId
    let update = InputArchiveTokens.fresh("upd")
    parentUpdateId = update
    updateId = update
    associationValid = true
    lock.unlock()
    var fields = baseFields(kind: kind, outcome: outcome, process: process, segment: segment)
    fields["update_id"] = update
    if let parent {
      fields["parent_update_id"] = parent
    }
    fields["stage"] = "frontend_update"
    fields["payload"] = page.payload(operation: operation, timing: lastTiming())
    fields["host_persistence"] = "unknown"
    _ = admit(fields)
  }

  private func admitTerminal(kind: String, outcome: String, text: String?, schema: String, clientPresent: Bool) {
    if !clientPresent && kind != "unavailable_client" {
      return
    }
    if measurementSuppressed {
      return
    }
    if !producer.captureEnabled() && kind != "unavailable_client" {
      return
    }
    if kind != "unavailable_client" && InputArchiveSignals.secureEventInputEnabled() {
      admitExclusion()
      return
    }
    // Cached or hard-coded Luna identity is not proof. Unknown and other schemas exclude without text.
    if kind != "unavailable_client" && schema != InputArchive.supportedSchema {
      admitExclusion()
      return
    }
    lock.lock()
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
    parentUpdateId = nil
    updateId = ""
    lock.unlock()
    var fields = baseFields(kind: kind, outcome: outcome, process: process, segment: segment)
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

  private func admitExclusion() {
    lock.lock()
    let process = processId
    let segment = segmentId
    lock.unlock()
    var fields = baseFields(kind: "exclusion_notice", outcome: "unknown", process: process, segment: segment)
    fields["eligibility"] = "excluded"
    fields["reason"] = "deliberate_exclusion"
    fields["schema_id"] = "unknown"
    fields["payload"] = NSNull()
    _ = admit(fields)
  }

  private func admit(_ fields: [String: Any]) -> InputArchiveAdmission {
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

  private func baseFields(kind: String, outcome: String, process: String, segment: String) -> [String: Any] {
    [
      "envelope_version": InputArchive.envelopeVersion,
      "content_version": InputArchive.contentVersion,
      "schema_id": InputArchive.supportedSchema,
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

  private func classify(operation: String, previous: String, previousLength: Int, current: OwnedPage) -> String {
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

private struct OwnedPage {
  var schemaId: String
  var preedit: String
  var candidates: [String]
  var comments: [String]
  var highlighted: Int
  var page: Int
  var lastPage: Bool
  var caretUTF16: Int
  var inputLength: Int
  var application: String
  var clientPresent: Bool

  init(_ snapshot: InputArchiveSnapshot) {
    schemaId = String(snapshot.schemaId)
    preedit = String(snapshot.preedit)
    candidates = snapshot.candidates.map { String($0) }
    comments = snapshot.comments.map { String($0) }
    highlighted = snapshot.highlighted
    page = snapshot.page
    lastPage = snapshot.lastPage
    caretUTF16 = snapshot.caretUTF16
    inputLength = snapshot.inputLength
    application = String(snapshot.application)
    clientPresent = snapshot.clientPresent
  }

  func payload(operation: String, timing: InputArchiveTiming) -> [String: Any] {
    [
      "text": preedit,
      "preedit": preedit,
      "candidates": candidates,
      "comments": comments,
      "highlighted": highlighted,
      "page": page,
      "last_page": lastPage,
      "caret_utf16": caretUTF16,
      "input_length": inputLength,
      "application": InputArchiveTokens.token(application, fallback: "unknown_app"),
      "operation": operation,
      "candidate_order": "frontend_page_as_received",
      "host_persistence": "unknown",
      "clock_domain": timing.clockDomain,
      "endpoint": timing.endpoint,
      "event_queue_wait": timing.eventQueueWait,
      "timebase_numer": Int(InputArchiveClock.timebase.numer),
      "timebase_denom": Int(InputArchiveClock.timebase.denom)
    ]
  }
}
