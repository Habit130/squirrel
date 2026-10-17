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
  private var actionDepth = 0
  private var actionFrame: InputArchiveActionFrame?
  private var lastCompletedActionId = ""
  private var timingCounters = InputArchiveTimingCounters()

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
      if var frame = actionFrame {
        // The observation admitted for this action must not be replayed at a
        // different collector binding after a rebind.
        frame.excluded = true
        frame.continuityCut = true
        actionFrame = frame
      }
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

  func notePendingOperation(_ operation: String) {
    lock.lock()
    pendingOperation = operation
    // The owning action keeps its own operation; a nested entry (for example a
    // nested raw finalization) must not relabel the action it folds into.
    if var frame = actionFrame, frame.operation == nil {
      frame.operation = operation
      actionFrame = frame
    }
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
    if var frame = actionFrame {
      frame.continuityCut = true
      actionFrame = frame
    }
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
    lock.unlock()
    // Idle empty input is not a cancellation and must not open a process.
    if !hasContent && !processOpen {
      noteEmptyInputBoundary()
      return
    }
    if !mayAdmit(schema: owned.schemaId, clientPresent: owned.clientPresent) {
      // Opt-out, pause, ineligibility or an excluded/unsupported schema. The
      // content of this observation was not recorded, so the composition stays
      // excluded until its empty/terminal boundary (E2/E3 no-backfill).
      if hasContent {
        markCompositionUnobserved()
      }
      if shouldExclude(schema: owned.schemaId) {
        admitExclusion()
      }
      if !hasContent {
        noteEmptyInputBoundary()
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
      if !hasContent {
        noteEmptyInputBoundary()
      }
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
    if !hasContent {
      noteEmptyInputBoundary()
    }
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
    status["timing_actions"] = String(timingCounters.actions)
    status["timing_records"] = String(timingCounters.admitted)
    status["timing_refused_gate"] = String(timingCounters.refusedGate)
    status["timing_refused_no_process"] = String(timingCounters.refusedNoProcess)
    status["timing_refused_no_observation"] = String(timingCounters.refusedNoObservation)
    status["timing_refused_object"] = String(timingCounters.refusedObject)
    status["timing_refused_admission"] = String(timingCounters.refusedAdmission)
    status["timing_unknown_endpoint"] = String(timingCounters.unknownEndpoint)
    status["timing_nested_actions"] = String(timingCounters.nested)
    status["action_depth"] = String(actionDepth)
    status["current_action_id"] = actionFrame?.actionId ?? ""
    status["last_action_id"] = lastCompletedActionId
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
    // earlier prefix unobserved for the new segment, and any action in flight
    // cannot persist a timing sample that spans the excluded state.
    if changed && !enabled {
      compositionUnobserved = true
      if var frame = actionFrame {
        frame.excluded = true
        actionFrame = frame
      }
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
    fields["payload"] = page.payload(operation: operation)
    fields["host_persistence"] = "unknown"
    let result = admit(fields)
    if result.admitted {
      // Only a durable page may contribute owned references. A page refused by
      // queue saturation must not leave an update identity that the archive
      // never stored.
      captureActionReferences(
        process: process,
        segment: segment,
        update: update,
        parent: parent,
        schema: page.schemaId
      )
    }
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

extension InputArchiveEngine {
  func beginAction(_ name: String, eventTimestamp: TimeInterval?) {
    let entry = InputArchiveClock.now()
    lock.lock()
    timing = InputArchiveTiming()
    timing.action = name
    timing.entryTicks = entry
    timing.eventQueueWait = Self.queueWait(eventTimestamp)
    metadataPublishedBeforeEngine = false
    if actionDepth == 0 {
      actionFrame = InputArchiveActionFrame(
        actionId: InputArchiveTokens.fresh("act"),
        action: name,
        entryTicks: entry
      )
      timingCounters.actions += 1
    } else if var frame = actionFrame {
      // A nested declared entry belongs to the active action. It never starts a
      // second sample, and the bound is a count rather than retained history.
      frame.nestedActions = min(frame.nestedActions + 1, InputArchiveTimingConversion.maxNestedActions)
      actionFrame = frame
      timingCounters.nested += 1
    }
    if actionDepth < Int.max {
      actionDepth += 1
    }
    lock.unlock()
  }

  func finishAction() {
    let returned = InputArchiveClock.now()
    let captureEnabled = producer.captureEnabled()
    let secure = InputArchiveSignals.secureEventInputEnabled()
    let suppressed = measurementSuppressed
    lock.lock()
    timing.returnTicks = returned
    if actionDepth > 0 {
      actionDepth -= 1
    }
    var frame: InputArchiveActionFrame?
    if actionDepth == 0 {
      frame = actionFrame
      actionFrame = nil
      if let completed = frame {
        lastCompletedActionId = completed.actionId
      }
    }
    let operation = pendingOperation
    let segment = segmentId
    lock.unlock()
    guard let frame else { return }
    completeAction(
      frame,
      fallbackOperation: operation,
      fallbackSegment: segment,
      captureEnabled: captureEnabled,
      secure: secure,
      suppressed: suppressed
    )
  }

  func markEndpoint(_ name: String) {
    // Only the marked-text and candidate-update calls complete the primary
    // interval. A commit/insertText call is recorded separately.
    guard name == "marked_text" || name == "panel_update" else { return }
    let ticks = InputArchiveClock.now()
    lock.lock()
    timing.primaryEndTicks = ticks
    timing.endpoint = name
    if var frame = actionFrame {
      if name == "marked_text" {
        frame.markedTextTicks = ticks
      } else {
        frame.panelUpdateTicks = ticks
      }
      actionFrame = frame
    }
    lock.unlock()
  }

  func noteCommitCall(start: UInt64, end: UInt64) {
    guard start > 0, end > start else { return }
    lock.lock()
    if var frame = actionFrame {
      frame.commitStartTicks = start
      frame.commitEndTicks = end
      actionFrame = frame
    }
    lock.unlock()
  }

  /// Called by terminal admission paths in another file. The owning action
  /// refuses a timing sample once an exclusion is observed inside it.
  func markActionFrame(excluded: Bool = false, continuityCut: Bool = false) {
    lock.lock()
    if var frame = actionFrame {
      if excluded {
        frame.excluded = true
      }
      if continuityCut {
        frame.continuityCut = true
      }
      actionFrame = frame
    }
    lock.unlock()
  }

  /// Copies owned references from a real observation into the owning action.
  /// References always belong to one process: when an observation belongs to a
  /// replacement process, the previous process's references are dropped rather
  /// than attached to the new one.
  func captureActionReferences(
    process: String,
    segment: String,
    update: String? = nil,
    parent: String? = nil,
    terminalUpdate: String? = nil,
    commit: String? = nil,
    schema: String
  ) {
    lock.lock()
    if var frame = actionFrame {
      if let current = frame.observedProcessId, current != process {
        frame.updateId = nil
        frame.parentUpdateId = nil
        frame.terminalUpdateId = nil
        frame.commitId = nil
      }
      frame.observedProcessId = process
      frame.observedSegmentId = segment
      if let update {
        frame.updateId = update
      }
      if let parent {
        frame.parentUpdateId = parent
      }
      if let terminalUpdate {
        frame.terminalUpdateId = terminalUpdate
      }
      if let commit {
        frame.commitId = commit
      }
      frame.schemaId = schema
      actionFrame = frame
    }
    lock.unlock()
  }

  /// Completes one top-level declared action. At most one timing observation is
  /// admitted; it is content-free and never changes input behavior.
  private func completeAction(
    _ frame: InputArchiveActionFrame,
    fallbackOperation: String,
    fallbackSegment: String,
    captureEnabled: Bool,
    secure: Bool,
    suppressed: Bool
  ) {
    var refusal: String?
    if suppressed {
      refusal = "measurement_suppressed"
    } else if frame.excluded {
      refusal = "excluded_during_action"
    } else if secure {
      refusal = "secure_input"
    } else if !captureEnabled {
      refusal = "policy_not_effective"
    }
    let schema = frame.schemaId ?? ""
    if refusal == nil && schema != InputArchive.supportedSchema {
      refusal = "no_supported_observation"
    }
    let process = frame.observedProcessId ?? ""
    if refusal == nil && !InputArchiveTokens.isSafe(process) {
      refusal = "no_process_association"
    }
    var object: [String: Any]?
    if refusal == nil {
      object = InputArchiveFrontendTimingV1.object(
        frame: frame,
        sourceInstanceId: producer.sourceId,
        processId: process,
        operation: frame.operation ?? fallbackOperation
      )
      if object == nil {
        refusal = "invalid_timing_object"
      }
    }
    guard refusal == nil, let object else {
      lock.lock()
      switch refusal {
      case "no_process_association":
        timingCounters.refusedNoProcess += 1
      case "no_supported_observation":
        timingCounters.refusedNoObservation += 1
      case "invalid_timing_object":
        timingCounters.refusedObject += 1
      default:
        timingCounters.refusedGate += 1
      }
      lock.unlock()
      return
    }
    let segment = frame.observedSegmentId ?? fallbackSegment
    var fields = baseFields(kind: "provenance", outcome: "unknown", process: process, segment: segment, schema: schema)
    if let update = frame.updateId ?? frame.terminalUpdateId {
      fields["update_id"] = update
    }
    if let commit = frame.commitId {
      fields["commit_id"] = commit
    }
    fields["stage"] = "frontend_timing"
    fields["priority_class"] = "metadata"
    fields["payload"] = ["frontend_timing": object]
    let result = admit(fields)
    lock.lock()
    if result.admitted {
      timingCounters.admitted += 1
    } else {
      // Queue saturation or loss is not a policy gate refusal.
      timingCounters.refusedAdmission += 1
    }
    if object["validity"] as? String != "valid" {
      timingCounters.unknownEndpoint += 1
    }
    lock.unlock()
  }
}

private struct InputArchiveTimingCounters {
  var actions = 0
  var admitted = 0
  var refusedGate = 0
  var refusedNoProcess = 0
  var refusedNoObservation = 0
  var refusedObject = 0
  var refusedAdmission = 0
  var unknownEndpoint = 0
  var nested = 0
}
