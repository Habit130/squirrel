//
//  InputArchiveTiming.swift
//  Squirrel
//
//  Version 1 frontend timing observation. Ticks come from the frontend clock;
//  this file never derives a duration from backend, text, or wall-clock state.
//

import Darwin
import Foundation

enum InputArchiveTimingConversion {
  /// Nesting is folded into the owning action. The count is bounded so a
  /// pathological entry chain cannot grow history-sized state.
  static let maxNestedActions = 255

  /// Overflow-safe mach tick conversion. Returns nil rather than a wrapped or
  /// truncated value when the timebase or multiplication cannot be represented.
  static func nanoseconds(ticks: UInt64, timebase: mach_timebase_info_data_t) -> UInt64? {
    guard timebase.numer != 0, timebase.denom != 0 else { return nil }
    let numer = UInt64(timebase.numer)
    let denom = UInt64(timebase.denom)
    let whole = ticks / denom
    let remainder = ticks % denom
    let (high, highOverflow) = whole.multipliedReportingOverflow(by: numer)
    guard !highOverflow else { return nil }
    let (scaledRemainder, remainderOverflow) = remainder.multipliedReportingOverflow(by: numer)
    guard !remainderOverflow else { return nil }
    let (total, totalOverflow) = high.addingReportingOverflow(scaledRemainder / denom)
    guard !totalOverflow else { return nil }
    return total
  }

  /// A primary interval needs a real start and a strictly later completion.
  /// Zero-length, nonmonotone, and absent endpoints stay unknown instead of
  /// becoming zero or underflowed successful samples.
  static func interval(start: UInt64, end: UInt64, timebase: mach_timebase_info_data_t) -> UInt64? {
    guard start > 0, end > start else { return nil }
    return nanoseconds(ticks: end - start, timebase: timebase)
  }

  static func timestamp(_ ticks: UInt64) -> Int64? {
    Int64(exactly: ticks)
  }
}

/// One top-level declared controller action. Nested entries are folded into
/// this frame and counted; they never produce a second sample.
struct InputArchiveActionFrame {
  var actionId: String
  var action: String
  var operation: String?
  var entryTicks: UInt64
  var markedTextTicks: UInt64 = 0
  var panelUpdateTicks: UInt64 = 0
  var commitStartTicks: UInt64 = 0
  var commitEndTicks: UInt64 = 0
  var observedProcessId: String?
  var observedSegmentId: String?
  var updateId: String?
  var parentUpdateId: String?
  var terminalUpdateId: String?
  var commitId: String?
  var schemaId: String?
  var continuityCut = false
  var excluded = false
  var nestedActions = 0

  var primaryEndpoint: String {
    if panelUpdateTicks > 0 && panelUpdateTicks >= markedTextTicks {
      return "panel_update"
    }
    if markedTextTicks > 0 {
      return "marked_text"
    }
    return "unavailable"
  }

  var primaryEndTicks: UInt64 {
    max(markedTextTicks, panelUpdateTicks)
  }

  var updateCalls: [[String: Any]] {
    var calls: [[String: Any]] = []
    if let ticks = InputArchiveTimingConversion.timestamp(markedTextTicks), markedTextTicks > 0 {
      calls.append(["endpoint": "marked_text", "ticks": ticks])
    }
    if let ticks = InputArchiveTimingConversion.timestamp(panelUpdateTicks), panelUpdateTicks > 0 {
      calls.append(["endpoint": "panel_update", "ticks": ticks])
    }
    return calls
  }
}

enum InputArchiveFrontendTimingV1 {
  static let version = 1

  /// Builds the self-identifying payload object. Identity comes only from owned
  /// action state; a missing observation or interval is reported as unknown.
  static func object(
    frame: InputArchiveActionFrame,
    sourceInstanceId: String,
    processId: String,
    operation: String
  ) -> [String: Any]? {
    guard InputArchiveTokens.isSafe(frame.actionId),
          InputArchiveTokens.isSafe(frame.action),
          InputArchiveTokens.isSafe(sourceInstanceId),
          InputArchiveTokens.isSafe(processId) else {
      return nil
    }
    let timebase = InputArchiveClock.timebase
    guard timebase.numer != 0, timebase.denom != 0 else { return nil }

    var association: [String: Any] = [
      "source_instance_id": sourceInstanceId,
      "process_id": processId
    ]
    if let segment = frame.observedSegmentId, InputArchiveTokens.isSafe(segment) {
      association["continuity_segment_id"] = segment
    }
    if let update = frame.updateId, InputArchiveTokens.isSafe(update) {
      association["update_id"] = update
    }
    if let parent = frame.parentUpdateId, InputArchiveTokens.isSafe(parent) {
      association["parent_update_id"] = parent
    }
    if let terminalUpdate = frame.terminalUpdateId, InputArchiveTokens.isSafe(terminalUpdate) {
      association["terminal_update_id"] = terminalUpdate
    }
    if let commit = frame.commitId, InputArchiveTokens.isSafe(commit) {
      association["commit_id"] = commit
    }

    var object: [String: Any] = [
      "version": version,
      "action_id": frame.actionId,
      "action": frame.action,
      "operation": InputArchiveTokens.token(operation, fallback: "unknown"),
      "clock": [
        "domain": "mach_absolute_time",
        "unit": "nanoseconds",
        "timebase_numer": Int(timebase.numer),
        "timebase_denom": Int(timebase.denom)
      ],
      "event_queue_wait": "unknown",
      "nested_actions": min(frame.nestedActions, InputArchiveTimingConversion.maxNestedActions),
      "continuity_cut": frame.continuityCut,
      "association": association
    ]

    let endpoint = frame.primaryEndpoint
    let updateCalls = frame.updateCalls
    if !updateCalls.isEmpty {
      object["update_calls"] = updateCalls
    }
    object["endpoint"] = endpoint

    if let entry = InputArchiveTimingConversion.timestamp(frame.entryTicks), frame.entryTicks > 0 {
      object["entry_ticks"] = entry
    }
    var validity = "unknown"
    var unknownReason = "no_update_call"
    if endpoint == "unavailable" {
      validity = "unknown"
      unknownReason = "no_update_call"
    } else if frame.entryTicks == 0 {
      validity = "invalid"
      unknownReason = "missing_entry"
    } else if let end = InputArchiveTimingConversion.timestamp(frame.primaryEndTicks) {
      object["endpoint_ticks"] = end
      if let duration = InputArchiveTimingConversion.interval(
        start: frame.entryTicks,
        end: frame.primaryEndTicks,
        timebase: timebase
      ) {
        validity = "valid"
        object["duration_ns"] = duration
        unknownReason = ""
      } else {
        validity = "invalid"
        unknownReason = "nonmonotone_endpoint"
      }
    } else {
      validity = "invalid"
      unknownReason = "unrepresentable_endpoint"
    }
    object["validity"] = validity
    if !unknownReason.isEmpty {
      object["unknown_reason"] = unknownReason
    }

    if frame.commitEndTicks > 0 {
      var call: [String: Any] = ["endpoint": "insert_text"]
      if let start = InputArchiveTimingConversion.timestamp(frame.commitStartTicks) {
        call["start_ticks"] = start
      }
      if let end = InputArchiveTimingConversion.timestamp(frame.commitEndTicks) {
        call["end_ticks"] = end
      }
      if let duration = InputArchiveTimingConversion.interval(
        start: frame.commitStartTicks,
        end: frame.commitEndTicks,
        timebase: timebase
      ) {
        call["duration_ns"] = duration
        call["validity"] = "valid"
      } else {
        call["validity"] = "invalid"
        call["unknown_reason"] = "nonmonotone_commit_call"
      }
      object["commit_call"] = call
    }

    return object
  }
}
