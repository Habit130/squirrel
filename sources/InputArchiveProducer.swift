//
//  InputArchiveProducer.swift
//  Squirrel
//
//  Native non-blocking admission and background transport for input-archive-v1.
//  The input path never serializes, connects, or changes the process working
//  directory. Longer-than-sun_path sockets are refused rather than worked around.
//

import Darwin
import Foundation

final class InputArchiveProducer {
  private static let maxSendAttempts = 3
  private static let maxPendingLosses = 64

  private let lock = NSLock()
  private let transportCall: (String, String, [String: Any]) -> [String: Any]
  private let beforeDrain: () -> Void
  private var socketPath = ""
  private var bindingGeneration: UInt64 = 0
  private var sourceInstanceId: String
  private var queue: [QueuedObservation] = []
  private var queuedBytes = 0
  private var inFlight = 0
  private var knownRefused = 0
  private var knownDropped = 0
  private var unreportedLossNotices = 0
  private var localLosses: [QueuedObservation] = []
  private var observedRevision: Int?
  private var observedDesired: String?
  private var observedAt: UInt64?
  private var collectorUnavailable = true
  private var lastPoll: UInt64?
  private var stopped = false
  private var sender: Thread?
  private var workingDirectoryAtStart = FileManager.default.currentDirectoryPath

  init(
    transportCall: @escaping (String, String, [String: Any]) -> [String: Any] = { socketPath, op, body in
      InputArchiveSocket.call(socketPath: socketPath, op: op, body: body)
    },
    beforeDrain: @escaping () -> Void = {}
  ) {
    self.transportCall = transportCall
    self.beforeDrain = beforeDrain
    sourceInstanceId = InputArchiveTokens.fresh("src")
  }

  var sourceId: String {
    lock.lock()
    defer { lock.unlock() }
    return sourceInstanceId
  }

  func bind(socketPath: String) {
    lock.lock()
    let changed = socketPath != self.socketPath
    self.socketPath = socketPath
    if changed {
      bindingGeneration &+= 1
      knownDropped += queue.filter { $0.kind != "loss_notice" }.count
      unreportedLossNotices += queue.count + localLosses.count
      queue.removeAll(keepingCapacity: true)
      queuedBytes = 0
      localLosses.removeAll(keepingCapacity: true)
      observedRevision = nil
      observedDesired = nil
      observedAt = nil
      collectorUnavailable = true
      lastPoll = nil
    }
    let shouldStart = !socketPath.isEmpty && sender == nil
    lock.unlock()
    if shouldStart {
      startSender()
    }
  }

  func close() {
    lock.lock()
    stopped = true
    let thread = sender
    lock.unlock()
    thread?.cancel()
    // Management/shutdown only. The input path must not join this thread.
    let deadline = Date().addingTimeInterval(1.0)
    while let thread, thread.isExecuting, Date() < deadline {
      Thread.sleep(forTimeInterval: 0.01)
    }
  }

  func localStatus() -> [String: String] {
    lock.lock()
    defer { lock.unlock() }
    return [
      "source_instance_id": sourceInstanceId,
      "observed_revision": observedRevision.map(String.init) ?? "unknown",
      "observed_desired": observedDesired ?? "unknown",
      "binding_generation": String(bindingGeneration),
      "fresh": cacheFreshLocked(now: InputArchiveClock.now()) ? "true" : "false",
      "collector_unavailable": collectorUnavailable ? "true" : "false",
      "queued": String(queue.count),
      "known_refused": String(knownRefused),
      "known_dropped": String(knownDropped),
      "unreported_loss_notices": String(unreportedLossNotices),
      "cwd_changed": FileManager.default.currentDirectoryPath == workingDirectoryAtStart ? "false" : "true",
      "content_included": "false"
    ]
  }

  func captureEnabled() -> Bool {
    lock.lock()
    defer { lock.unlock() }
    return cacheFreshLocked(now: InputArchiveClock.now()) && observedDesired == "enabled"
  }

  func waitUntilDrained(timeout: TimeInterval) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
      lock.lock()
      let empty = queue.isEmpty && localLosses.isEmpty && inFlight == 0
      lock.unlock()
      if empty {
        return true
      }
      Thread.sleep(forTimeInterval: 0.01)
    }
    return false
  }

  func admit(_ observation: [String: Any]) -> InputArchiveAdmission {
    guard let snapshot = owned(observation) else {
      return refuseInvalid()
    }
    let size = budgetBytes(snapshot)
    if size > InputArchive.maxEventBytes {
      lock.lock()
      knownRefused += 1
      lock.unlock()
      return InputArchiveAdmission.refused("event_too_large")
    }
    if locallyInvalid(snapshot) {
      return refuseInvalid()
    }
    if snapshot["eligibility"] as? String == "excluded" || snapshot["excluded"] as? Bool == true {
      let notice = exclusionNotice(snapshot)
      if locallyInvalid(notice) {
        return refuseInvalid()
      }
      return enqueue(notice, kind: "exclusion_notice", size: budgetBytes(notice))
    }
    let schema = snapshot["schema_id"] as? String ?? "unknown"
    let kind = snapshot["observation_kind"] as? String
    if kind != "loss_notice" && schema != InputArchive.supportedSchema && schema != "unknown" {
      return InputArchiveAdmission.refused("unsupported_schema")
    }
    lock.lock()
    defer { lock.unlock() }
    let fresh = cacheFreshLocked(now: InputArchiveClock.now())
    let desired = observedDesired
    guard fresh && desired == "enabled" else {
      let code = fresh && (desired == "off" || desired == "paused") ? "capture_disabled" : "policy_not_effective"
      return InputArchiveAdmission.refused(code)
    }
    return enqueueLocked(snapshot, kind: kind ?? "unknown_outcome", size: size)
  }
}

extension InputArchiveProducer {
  private func startSender() {
    let thread = Thread { [weak self] in
      self?.senderLoop()
    }
    thread.name = "input-archive-sender"
    lock.lock()
    sender = thread
    lock.unlock()
    thread.start()
  }

  private func senderLoop() {
    while !isStopped {
      pollPolicy()
      beforeDrain()
      let drained = drain(limit: InputArchive.batchSize)
      var retryPending = false
      if !drained.losses.isEmpty {
        let outcomes = send(items: drained.losses)
        retryPending = finishDelivery(drained.losses, outcomes: outcomes, isLossBatch: true)
      }
      if !drained.batch.isEmpty {
        let outcomes = send(items: drained.batch)
        retryPending = finishDelivery(drained.batch, outcomes: outcomes, isLossBatch: false) || retryPending
      }
      if retryPending {
        Thread.sleep(forTimeInterval: 0.05)
      } else if drained.batch.isEmpty && drained.losses.isEmpty {
        Thread.sleep(forTimeInterval: 0.01)
      }
    }
  }

  private var isStopped: Bool {
    lock.lock()
    defer { lock.unlock() }
    return stopped
  }

  private func refuseInvalid() -> InputArchiveAdmission {
    lock.lock()
    knownRefused += 1
    lock.unlock()
    return InputArchiveAdmission.refused("invalid_request")
  }

  private func exclusionNotice(_ snapshot: [String: Any]) -> [String: Any] {
    [
      "envelope_version": InputArchive.envelopeVersion,
      "content_version": InputArchive.contentVersion,
      "source_instance_id": snapshot["source_instance_id"] ?? sourceInstanceId,
      "source_local_sequence": snapshot["source_local_sequence"] ?? 0,
      "observation_kind": "exclusion_notice",
      "process_id": snapshot["process_id"] ?? "excluded",
      "schema_id": "unknown",
      "reason": "deliberate_exclusion",
      "eligibility": "excluded",
      "payload": NSNull()
    ]
  }

  private func cacheFreshLocked(now: UInt64) -> Bool {
    guard let observedAt, observedRevision != nil else { return false }
    let ageNs = InputArchiveClock.nanoseconds(from: now &- observedAt)
    return ageNs <= UInt64(InputArchive.freshnessWindowMs) * 1_000_000
  }

  private func enqueue(_ snapshot: [String: Any], kind: String, size: Int) -> InputArchiveAdmission {
    lock.lock()
    defer { lock.unlock() }
    return enqueueLocked(snapshot, kind: kind, size: size)
  }

  private func enqueueLocked(_ snapshot: [String: Any], kind: String, size: Int) -> InputArchiveAdmission {
    let priority = highPriority(kind) ? "high" : "low"
    let item = QueuedObservation(
      kind: kind,
      priority: priority,
      snapshot: snapshot,
      size: size,
      socketPath: socketPath,
      bindingGeneration: bindingGeneration,
      attempts: 0
    )
    if fitsLocked(size) {
      queue.append(item)
      queuedBytes += size
      return InputArchiveAdmission(admitted: true, code: "admitted", captureSequence: nil, priority: priority)
    }
    if priority == "high" {
      if let index = queue.firstIndex(where: { $0.priority == "low" }) {
        dropLocked(index)
        queue.append(item)
        queuedBytes += size
        return InputArchiveAdmission(admitted: true, code: "admitted", captureSequence: nil, priority: priority)
      }
    }
    knownRefused += 1
    rememberLossLocked(item, reason: "queue_saturated")
    return InputArchiveAdmission(admitted: false, code: "queue_saturated", captureSequence: nil, priority: priority)
  }

  private func fitsLocked(_ size: Int) -> Bool {
    queue.count + 1 <= InputArchive.queueCount && queuedBytes + size <= InputArchive.queueBytes
  }

  private func dropLocked(_ index: Int) {
    let old = queue.remove(at: index)
    queuedBytes -= old.size
    knownDropped += 1
    rememberLossLocked(old, reason: "displaced_for_priority")
  }

  private func rememberLossLocked(_ item: QueuedObservation, reason: String) {
    guard item.kind != "loss_notice",
          item.socketPath == socketPath,
          item.bindingGeneration == bindingGeneration else {
      unreportedLossNotices += 1
      return
    }
    guard localLosses.count < Self.maxPendingLosses else {
      unreportedLossNotices += 1
      knownRefused += 1
      return
    }
    var notice: [String: Any] = [
      "observation_kind": "loss_notice",
      "source_instance_id": item.snapshot["source_instance_id"] ?? sourceInstanceId,
      "source_local_sequence": item.snapshot["source_local_sequence"] ?? 0,
      "process_id": item.snapshot["process_id"] ?? "unknown",
      "payload": NSNull(),
      "schema_id": "unknown",
      "envelope_version": InputArchive.envelopeVersion,
      "content_version": InputArchive.contentVersion
    ]
    if let knownReason = Self.lossReason(reason) {
      notice["reason"] = knownReason
    }
    let size = budgetBytes(notice)
    localLosses.append(QueuedObservation(
      kind: "loss_notice",
      priority: "high",
      snapshot: notice,
      size: size,
      socketPath: socketPath,
      bindingGeneration: bindingGeneration,
      attempts: 0
    ))
  }

  private func drain(limit: Int) -> (batch: [QueuedObservation], losses: [QueuedObservation]) {
    lock.lock()
    defer { lock.unlock() }
    let count = min(limit, queue.count)
    let batch = Array(queue.prefix(count))
    queue.removeFirst(count)
    queuedBytes -= batch.reduce(0) { $0 + $1.size }
    let lossCount = min(limit, localLosses.count)
    let losses = Array(localLosses.prefix(lossCount))
    localLosses.removeFirst(lossCount)
    inFlight += batch.count + losses.count
    return (batch, losses)
  }

  private func finishDelivery(
    _ items: [QueuedObservation],
    outcomes: [DeliveryOutcome],
    isLossBatch: Bool
  ) -> Bool {
    lock.lock()
    defer { lock.unlock() }
    inFlight = max(0, inFlight - items.count)
    var retries: [QueuedObservation] = []
    for (item, outcome) in zip(items, outcomes) {
      let isLoss = isLossBatch || item.kind == "loss_notice"
      switch outcome {
      case .accepted:
        break
      case .retryable(let reason):
        if item.attempts + 1 < Self.maxSendAttempts,
           item.socketPath == socketPath,
           item.bindingGeneration == bindingGeneration {
          var retry = item
          retry.attempts += 1
          retries.append(retry)
        } else {
          recordFailedDeliveryLocked(item, reason: reason, isLossNotice: isLoss)
        }
      case .refused(let reason):
        recordFailedDeliveryLocked(item, reason: reason, isLossNotice: isLoss)
      }
    }
    for item in retries.reversed() {
      if item.kind == "loss_notice" {
        if localLosses.count < Self.maxPendingLosses {
          localLosses.insert(item, at: 0)
        } else {
          unreportedLossNotices += 1
          knownRefused += 1
        }
      } else if fitsLocked(item.size) {
        queue.insert(item, at: 0)
        queuedBytes += item.size
      } else {
        knownDropped += 1
        knownRefused += 1
        rememberLossLocked(item, reason: "requeue_saturated")
      }
    }
    return !retries.isEmpty
  }

  private func recordFailedDeliveryLocked(_ item: QueuedObservation, reason: String, isLossNotice: Bool) {
    knownRefused += 1
    if isLossNotice {
      unreportedLossNotices += 1
      return
    }
    knownDropped += 1
    if reason != "identity_conflict" {
      rememberLossLocked(item, reason: reason)
    }
  }
}

extension InputArchiveProducer {
  private func pollPolicy() {
    let now = InputArchiveClock.now()
    lock.lock()
    let path = socketPath
    let generation = bindingGeneration
    let revision = observedRevision
    let source = sourceInstanceId
    if let lastPoll {
      let age = InputArchiveClock.nanoseconds(from: now &- lastPoll)
      if age < UInt64(InputArchive.heartbeatIntervalMs) * 1_000_000 {
        lock.unlock()
        return
      }
    }
    lastPoll = now
    lock.unlock()
    guard !path.isEmpty else { return }
    var body: [String: Any] = ["source_instance_id": source]
    if let revision {
      body["observed_revision"] = revision
    }
    let response = transportCall(path, "policy_observe", body)
    lock.lock()
    guard generation == bindingGeneration && path == socketPath else {
      lock.unlock()
      return
    }
    if response["ok"] as? Bool != true {
      collectorUnavailable = true
      lock.unlock()
      return
    }
    guard let responseBody = response["body"] as? [String: Any],
          let nextRevision = responseBody["desired_revision"] as? Int,
          nextRevision >= 0,
          let desired = responseBody["desired_policy"] as? String,
          ["off", "enabled", "paused"].contains(desired) else {
      observedRevision = nil
      observedDesired = nil
      observedAt = nil
      collectorUnavailable = true
      lock.unlock()
      return
    }
    collectorUnavailable = false
    observedRevision = nextRevision
    observedDesired = desired
    observedAt = InputArchiveClock.now()
    lock.unlock()
  }

  private func send(items: [QueuedObservation]) -> [DeliveryOutcome] {
    guard let first = items.first else { return [] }
    guard !first.socketPath.isEmpty,
          items.allSatisfy({
            $0.socketPath == first.socketPath && $0.bindingGeneration == first.bindingGeneration
          }) else {
      return items.map { _ in .retryable("invalid_response") }
    }
    let response = transportCall(first.socketPath, "admit_batch", ["observations": items.map(\.snapshot)])
    if response["ok"] as? Bool != true {
      let error = response["error"] as? [String: Any] ?? [:]
      let code = error["code"] as? String ?? "invalid_response"
      lock.lock()
      if first.bindingGeneration == bindingGeneration {
        collectorUnavailable = code == "collector_unavailable"
      }
      lock.unlock()
      let retryable = (error["retryable"] as? Bool == true)
        || code == "collector_unavailable"
        || code == "invalid_response"
      return items.map { _ in retryable ? .retryable(code) : .refused(code) }
    }
    guard let codes = (response["body"] as? [String: Any])?["codes"] as? [String],
          codes.count == items.count,
          codes.allSatisfy(Self.accounted.contains) else {
      return items.map { _ in .retryable("invalid_response") }
    }
    lock.lock()
    if first.bindingGeneration == bindingGeneration {
      collectorUnavailable = false
    }
    lock.unlock()
    return codes.map { code in
      if code == "admitted" || code == "duplicate" || code == "excluded" {
        return .accepted
      }
      if code == "queue_saturated" || code == "storage_failure" {
        return .retryable(code)
      }
      return .refused(code)
    }
  }

  private static func lossReason(_ code: String) -> String? {
    let reasons: Set<String> = [
      "queue_saturated", "displaced_for_priority", "storage_failure",
      "capacity_stop", "requeue_saturated", "collector_queue_saturated"
    ]
    return reasons.contains(code) ? code : nil
  }

  private static let accounted: Set<String> = [
    "admitted", "duplicate", "identity_conflict", "queue_saturated", "capture_disabled",
    "capacity_stop", "storage_failure", "event_too_large", "unsupported_version",
    "unsupported_schema", "invalid_request", "excluded"
  ]

  private func highPriority(_ kind: String) -> Bool {
    [
      "start", "commit_attempt", "raw_finalization", "cancellation",
      "unavailable_client", "unknown_outcome", "loss_notice", "exclusion_notice", "provenance"
    ].contains(kind)
  }

  private func locallyInvalid(_ snapshot: [String: Any]) -> Bool {
    guard InputArchiveTokens.isSafe(snapshot["source_instance_id"] as? String ?? "") else { return true }
    guard InputArchiveTokens.isSafe(snapshot["process_id"] as? String ?? "") else { return true }
    guard let sequence = snapshot["source_local_sequence"] as? Int, sequence >= 0 else { return true }
    guard let kind = snapshot["observation_kind"] as? String, !kind.isEmpty else { return true }
    return false
  }

  private func owned(_ value: Any) -> [String: Any]? {
    value as? [String: Any]
  }

  private func budgetBytes(_ value: Any) -> Int {
    var total = 0
    accumulate(value, into: &total)
    return total
  }

  private func accumulate(_ value: Any, into total: inout Int) {
    if total > InputArchive.maxEventBytes {
      return
    }
    if let text = value as? String {
      total += text.utf8.count
    } else if let dictionary = value as? [String: Any] {
      for (key, item) in dictionary {
        total += key.utf8.count
        accumulate(item, into: &total)
      }
    } else if let list = value as? [Any] {
      for item in list {
        accumulate(item, into: &total)
      }
    } else {
      total += 8
    }
  }

}

private struct QueuedObservation {
  var kind: String
  var priority: String
  var snapshot: [String: Any]
  var size: Int
  var socketPath: String
  var bindingGeneration: UInt64
  var attempts: Int
}

private enum DeliveryOutcome {
  case accepted
  case retryable(String)
  case refused(String)
}

enum InputArchiveSocket {
  static func call(socketPath: String, op: String, body: [String: Any]) -> [String: Any] {
    if let refusal = InputArchivePaths.refusal(for: socketPath) {
      return failure(op: op, code: refusal)
    }
    let requestId = InputArchiveTokens.fresh("req")
    let request: [String: Any] = [
      "interface_version": InputArchive.interfaceVersion,
      "envelope_version": InputArchive.envelopeVersion,
      "content_version": InputArchive.contentVersion,
      "op": op,
      "request_id": requestId,
      "body": body
    ]
    guard let frame = encodeFrame(request) else {
      return failure(op: op, code: "event_too_large")
    }
    let before = FileManager.default.currentDirectoryPath
    guard let fd = connect(socketPath) else {
      return failure(op: op, code: "collector_unavailable")
    }
    defer { close(fd) }
    if FileManager.default.currentDirectoryPath != before {
      // Transport must not keep a mutated working directory. Restore and report.
      FileManager.default.changeCurrentDirectoryPath(before)
      return failure(op: op, code: "invalid_request")
    }
    if !writeAll(fd, frame) {
      return failure(op: op, code: "collector_unavailable")
    }
    guard let response = readFrame(fd),
          let object = try? JSONSerialization.jsonObject(with: response) as? [String: Any] else {
      return failure(op: op, code: "collector_unavailable")
    }
    if object["interface_version"] as? String != InputArchive.interfaceVersion
        || object["envelope_version"] as? Int != InputArchive.envelopeVersion {
      return failure(op: op, code: "unsupported_version")
    }
    if object["op"] as? String != op || object["request_id"] as? String != requestId {
      return failure(op: op, code: "invalid_response")
    }
    return object
  }

  private static func connect(_ path: String) -> Int32? {
    if path.utf8.count > InputArchive.sunPathLimit {
      return nil
    }
    let fd = socket(AF_UNIX, SOCK_STREAM, 0)
    if fd < 0 {
      return nil
    }
    var addr = sockaddr_un()
    addr.sun_family = sa_family_t(AF_UNIX)
    let copied = path.withCString { source -> Bool in
      withUnsafeMutablePointer(to: &addr.sun_path) { destination in
        destination.withMemoryRebound(to: CChar.self, capacity: 104) { rebound in
          strlcpy(rebound, source, 104) < 104
        }
      }
    }
    if !copied {
      close(fd)
      return nil
    }
    let flags = fcntl(fd, F_GETFL, 0)
    _ = fcntl(fd, F_SETFL, flags | O_NONBLOCK)
    let connected = withUnsafePointer(to: &addr) { pointer -> Bool in
      pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sock in
        let size = socklen_t(MemoryLayout<sockaddr_un>.size)
        let result = Darwin.connect(fd, sock, size)
        return result == 0 || errno == EINPROGRESS
      }
    }
    if !connected {
      close(fd)
      return nil
    }
    var pollfd = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
    let waited = poll(&pollfd, 1, Int32(InputArchive.connectTimeoutMs))
    if waited <= 0 {
      close(fd)
      return nil
    }
    var error: Int32 = 0
    var length = socklen_t(MemoryLayout<Int32>.size)
    getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length)
    if error != 0 {
      close(fd)
      return nil
    }
    _ = fcntl(fd, F_SETFL, flags)
    var noSignalPipe: Int32 = 1
    if setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignalPipe, socklen_t(MemoryLayout<Int32>.size)) != 0 {
      close(fd)
      return nil
    }
    var timeout = timeval(tv_sec: 1, tv_usec: 0)
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
    return fd
  }

  private static func encodeFrame(_ object: [String: Any]) -> Data? {
    guard JSONSerialization.isValidJSONObject(object),
          let data = try? JSONSerialization.data(withJSONObject: object) else {
      return nil
    }
    if data.count > 4_194_304 {
      return nil
    }
    var frame = Data(capacity: 4 + data.count)
    var length = UInt32(data.count).bigEndian
    frame.append(Data(bytes: &length, count: 4))
    frame.append(data)
    return frame
  }

  private static func writeAll(_ fd: Int32, _ data: Data) -> Bool {
    data.withUnsafeBytes { raw in
      guard let base = raw.baseAddress else { return false }
      var sent = 0
      while sent < data.count {
        let wrote = Darwin.write(fd, base.advanced(by: sent), data.count - sent)
        if wrote <= 0 {
          return false
        }
        sent += wrote
      }
      return true
    }
  }

  private static func readFrame(_ fd: Int32) -> Data? {
    var header = [UInt8](repeating: 0, count: 4)
    guard readExact(fd, &header, 4) else { return nil }
    let size = header.withUnsafeBytes { $0.load(as: UInt32.self).bigEndian }
    if size > 4_194_304 {
      return nil
    }
    var payload = [UInt8](repeating: 0, count: Int(size))
    guard readExact(fd, &payload, Int(size)) else { return nil }
    return Data(payload)
  }

  private static func readExact(_ fd: Int32, _ buffer: inout [UInt8], _ count: Int) -> Bool {
    var got = 0
    while got < count {
      let read = buffer.withUnsafeMutableBytes { raw -> Int in
        guard let base = raw.baseAddress else { return -1 }
        return Darwin.read(fd, base.advanced(by: got), count - got)
      }
      if read <= 0 {
        return false
      }
      got += read
    }
    return true
  }

  private static func failure(op: String, code: String) -> [String: Any] {
    [
      "interface_version": InputArchive.interfaceVersion,
      "envelope_version": InputArchive.envelopeVersion,
      "op": op,
      "ok": false,
      "error": [
      "code": code,
      "message": "content-free",
      "retryable": code == "collector_unavailable" || code == "invalid_response",
        "content_included": false
      ],
      "content_included": false
    ]
  }
}
