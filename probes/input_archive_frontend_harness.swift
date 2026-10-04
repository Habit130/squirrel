//
//  input_archive_frontend_harness.swift
//  Isolated real-frontend harness for AC-189. Not a second input method.
//

import AppKit
import Darwin
import Foundation
import InputMethodKit

final class RecordingTextClient: NSObject, IMKTextInput {
  var bundle = "com.ac189.fixture"
  var inserts: [String] = []
  var marked: [String] = []
  var insertTicks: [UInt64] = []
  var markedTicks: [UInt64] = []

  func reset() {
    inserts = []
    marked = []
    insertTicks = []
    markedTicks = []
  }

  func insertText(_ string: Any!, replacementRange: NSRange) {
    inserts.append(text(from: string))
    insertTicks.append(InputArchiveClock.now())
  }

  func setMarkedText(_ string: Any!, selectionRange: NSRange, replacementRange: NSRange) {
    marked.append(text(from: string))
    markedTicks.append(InputArchiveClock.now())
  }

  func selectedRange() -> NSRange { NSRange(location: 0, length: 0) }
  func markedRange() -> NSRange { NSRange(location: NSNotFound, length: 0) }
  func attributedSubstring(from range: NSRange) -> NSAttributedString! { nil }
  func characterIndex(for point: NSPoint) -> Int { 0 }

  func firstRect(forCharacterRange range: NSRange, actualRange: NSRangePointer) -> NSRect {
    NSRect(x: 20, y: 20, width: 1, height: 16)
  }

  func attributes(forCharacterIndex index: Int, lineHeightRectangle: NSRectPointer) -> [AnyHashable: Any]! {
    lineHeightRectangle.pointee = NSRect(x: 20, y: 40, width: 1, height: 16)
    return [:]
  }

  func validAttributesForMarkedText() -> [Any]! { [] }
  func overrideKeyboard(withKeyboardNamed keyboard: String!) {}
  func bundleIdentifier() -> String! { bundle }
  func length() -> Int { 0 }
  func characterIndex(for point: NSPoint, tracking mappingMode: IMKLocationToOffsetMappingMode, inMarkedRange: UnsafeMutablePointer<ObjCBool>?) -> Int {
    NSNotFound
  }
  func selectMode(_ modeIdentifier: String!) {}
  func supportsUnicode() -> Bool { true }
  func windowLevel() -> CGWindowLevel { 0 }
  func supportsProperty(_ property: TSMDocumentPropertyTag) -> Bool { false }
  func uniqueClientIdentifierString() -> String! { "ac189-fixture-client" }
  func string(from range: NSRange, actualRange: NSRangePointer!) -> String! { "" }

  private func text(from value: Any?) -> String {
    if let text = value as? String { return text }
    if let text = value as? NSAttributedString { return text.string }
    if let text = value as? NSString { return text as String }
    let described = String(describing: value as Any)
    if described == "nil" || described == "Optional(nil)" { return "" }
    if described.hasPrefix("Optional("), described.hasSuffix(")") {
      return String(described.dropFirst("Optional(".count).dropLast())
        .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
    }
    return described
  }
}

@main
enum InputArchiveFrontendHarness {
  static var failures: [String] = []
  static var client = RecordingTextClient()
  static var controller: SquirrelInputController?
  static var cwdAtStart = FileManager.default.currentDirectoryPath

  static func main() {
    let arguments = parse(CommandLine.arguments)
    guard let shared = arguments["shared"], let user = arguments["user"], let log = arguments["log"] else {
      fail("missing fixture directories")
      emit(arguments["report"])
      return
    }
    SquirrelApp.fixtureUserDirectory = URL(fileURLWithPath: user, isDirectory: true)
    SquirrelApp.fixtureSharedSupportDirectory = URL(fileURLWithPath: shared, isDirectory: true)
    SquirrelApp.fixtureLogDirectory = URL(fileURLWithPath: log, isDirectory: true)
    let scenario = arguments["scenario"] ?? "contract"
    if scenario == "socket-call" {
      runSocketCall(socket: arguments["socket"] ?? "")
      emit(arguments["report"])
      exit(failures.isEmpty ? 0 : 1)
    }
    if scenario == "sender-call" {
      runSenderCall(socket: arguments["socket"] ?? "")
      emit(arguments["report"])
      exit(failures.isEmpty ? 0 : 1)
    }
    if !bootstrap() {
      emit(arguments["report"])
      return
    }
    switch scenario {
    case "contract":
      runContract(socket: arguments["socket"] ?? "")
    case "timing":
      runTiming()
    case "absent":
      runAbsent()
    case "metadata":
      runMetadata()
    case "fixtures":
      runAssociationFixtures()
    case "schema-gate":
      runSchemaGate()
    case "transition-edge":
      runTransitionEdge()
    case "terminal-provenance":
      runTerminalProvenance()
    case "fault-burst":
      runFaultBurst()
    case "concurrent-status":
      runConcurrentStatus()
    case "socket-call":
      runSocketCall(socket: arguments["socket"] ?? "")
    case "sender-call":
      runSenderCall(socket: arguments["socket"] ?? "")
    default:
      fail("unknown scenario \(scenario)")
    }
    expect(FileManager.default.currentDirectoryPath == cwdAtStart, "working directory changed")
    emit(arguments["report"])
    exit(failures.isEmpty ? 0 : 1)
  }

  static func bootstrap() -> Bool {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = SquirrelApplicationDelegate()
    app.delegate = delegate
    delegate.applicationWillFinishLaunching(
      Notification(name: NSApplication.willFinishLaunchingNotification)
    )
    delegate.setupRime()
    delegate.startRime(fullCheck: true)
    let api = rime_get_api_stdbool().pointee
    let deadline = Date().addingTimeInterval(30)
    while api.is_maintenance_mode(), Date() < deadline {
      Thread.sleep(forTimeInterval: 0.05)
    }
    if api.is_maintenance_mode() {
      fail("deploy did not finish")
      return false
    }
    delegate.loadSettings()
    guard delegate.panel != nil else {
      fail("production panel was not created")
      return false
    }
    let server = IMKServer(name: "ac189.frontend", bundleIdentifier: "com.ac189.harness")
    // IMK rejects a local text client during init. Production later assigns the
    // client in activateServer, which is the same assignment handle() uses.
    guard let created = SquirrelInputController(server: server, delegate: nil, client: nil) else {
      fail("production controller init failed")
      return false
    }
    controller = created
    created.activateServer(client)
    return true
  }

  static func runContract(socket: String) {
    expect(!socket.isEmpty, "contract scenario needs a socket")
    expect(waitForPolicy("enabled"), "capture policy did not become locally fresh")
    let off = captureSequence(suppressed: true)
    let on = captureSequence(suppressed: false)
    expect(off.inserts == on.inserts, "capture off/on committed text diverged")
    expect(meaningfulMarked(off.marked) == meaningfulMarked(on.marked), "capture off/on marked text diverged")
    expect(on.inserts.contains { $0.contains("你") }, "engine commit text missing from client")
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
    runEdges()
  }

  static func captureSequence(suppressed: Bool) -> (inserts: [String], marked: [String]) {
    InputArchiveEngine.shared.setMeasurementSuppressed(suppressed)
    client.reset()
    clearComposition()
    type("nihao")
    sendKey(49, " ")
    let inserts = client.inserts
    let marked = client.marked
    clearComposition()
    return (inserts, marked)
  }

  static func runEdges() {
    clearComposition()
    type("ni")
    sendBackspace()
    type("i")
    sendKey(19, "2")
    sendKey(53, "\u{1b}")
    type("ni")
    controller?.commitComposition(client)
    controller?.deactivateServer(client)
    controller?.activateServer(client)
    type("ni")
    _ = controller?.page(up: false)
    _ = controller?.selectCandidate(0)
    client.bundle = "com.ac189.other"
    type("hao")
    client.bundle = "com.ac189.fixture"
    let previous = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { true }
    type("ni")
    InputArchiveSignals.secureEventInputEnabled = previous
    selectOtherSchema()
    type("ni")
    selectLuna()
    let held = client
    client = RecordingTextClient()
    controller?.commitComposition(NSObject())
    client = held
    controller?.activateServer(client)
    let command = keyEvent(keyCode: 0, characters: "a", flags: .command)
    let handled = controller?.handle(command, client: client) ?? true
    expect(!handled, "command shortcut was consumed")
  }

  static func runAbsent() {
    let started = InputArchiveClock.now()
    type("ni")
    let elapsed = InputArchiveClock.nanoseconds(from: InputArchiveClock.now() &- started)
    expect(elapsed < 250_000_000, "absent collector blocked input")
    sendKey(49, " ")
  }

  static func runMetadata() {
    clearComposition()
    type("n")
    guard let controller else {
      fail("no controller")
      return
    }
    let source = controller.archiveSessionProperty(InputArchive.propertySource)
    let association = controller.archiveSessionProperty(InputArchive.propertyAssociation)
    expect(!source.isEmpty, "session metadata source missing")
    expect(association == "valid" || association == "invalid", "association seam missing")
    let status = InputArchiveEngine.shared.contentFreeStatus()
    expect(status["metadata_before_engine"] == "true", "metadata was not published before the engine call")
  }

  static func runAssociationFixtures() {
    let source = InputArchiveEngine.shared.sourceInstanceId
    let first = InputArchiveEngine.shared.admitFixture([
      "schema_id": InputArchive.supportedSchema,
      "source_local_sequence": 900001,
      "observation_kind": "commit_attempt",
      "process_id": "procfixture1",
      "outcome": "observed_attempt",
      "host_persistence": "unknown",
      "payload": ["text": "INV-EQUAL"]
    ])
    let retry = InputArchiveEngine.shared.admitFixture([
      "schema_id": InputArchive.supportedSchema,
      "source_local_sequence": 900001,
      "observation_kind": "commit_attempt",
      "process_id": "procfixture1",
      "outcome": "observed_attempt",
      "host_persistence": "unknown",
      "payload": ["text": "INV-EQUAL"]
    ])
    let conflict = InputArchiveEngine.shared.admitFixture([
      "schema_id": InputArchive.supportedSchema,
      "source_local_sequence": 900001,
      "observation_kind": "commit_attempt",
      "process_id": "procfixture1",
      "outcome": "observed_attempt",
      "host_persistence": "unknown",
      "payload": ["text": "INV-CONFLICT"]
    ])
    let missing = InputArchiveEngine.shared.admitFixture([
      "schema_id": InputArchive.supportedSchema,
      "observation_kind": "input_change",
      "process_id": "procfixture2",
      "parent_update_id": "upd-missing-parent",
      "update_id": "upd-child",
      "outcome": "input_change",
      "payload": ["text": "INV-ORDER"]
    ])
    InputArchiveEngine.shared.recordUnknown(schema: InputArchive.supportedSchema)
    _ = source
    _ = first
    _ = retry
    _ = conflict
    _ = missing
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
  }

  static func runTiming() {
    expect(waitForPolicy("enabled"), "timing policy not fresh")
    // The engine reports the operation's schema; the eligible fixture schema has
    // to be selected before any measured stratum, otherwise every observation
    // would be ineligible and the capture-on arm would archive nothing.
    selectLuna()
    clearComposition()
    expect(InputArchiveEngine.shared.contentFreeStatus()["queued"] != nil, "engine status unavailable")
    let strata = ["short", "long", "backspace", "retype", "number", "space", "mouse", "paging"]
    var rows: [[String: Any]] = []
    for stratum in strata {
      for _ in 0..<100 {
        measurePair(stratum, record: false, into: &rows)
      }
      for pair in 0..<2000 {
        measurePair(stratum, record: true, pair: pair, into: &rows)
      }
    }
    if let raw = parse(CommandLine.arguments)["raw"] {
      let data = try? JSONSerialization.data(withJSONObject: ["rows": rows, "content_included": false])
      try? data?.write(to: URL(fileURLWithPath: raw))
    }
  }

  static func measurePair(_ stratum: String, record: Bool, pair: Int = 0, into rows: inout [[String: Any]]) {
    let order = pair % 2 == 0 ? ["off", "on"] : ["on", "off"]
    var samples: [String: UInt64] = [:]
    for arm in order {
      // Equivalent pre-state reset before the measured operation: capture is
      // eligible while the composition is cleared and the stratum pre-state is
      // composed, so neither arm inherits an unobserved prefix. Only the
      // measured operation itself runs with the arm's eligibility applied.
      InputArchiveEngine.shared.setMeasurementSuppressed(false)
      clearComposition()
      selectLuna()
      prepare(stratum)
      InputArchiveEngine.shared.setMeasurementSuppressed(arm == "off")
      let beforePanel = NSApp.squirrelAppDelegate.panel?.updateCompletionCount ?? 0
      let started = InputArchiveClock.now()
      perform(stratum)
      let returned = InputArchiveClock.now()
      let timing = InputArchiveEngine.shared.lastTiming()
      let panelMoved = (NSApp.squirrelAppDelegate.panel?.updateCompletionCount ?? 0) > beforePanel
      let fullNs = InputArchiveClock.nanoseconds(from: returned &- started)
      let primaryAvailable = timing.primaryEndTicks != 0 && timing.endpoint != "unavailable"
      let primaryNs = primaryAvailable
        ? InputArchiveClock.nanoseconds(from: timing.primaryEndTicks &- timing.entryTicks)
        : 0
      samples[arm] = fullNs
      samples[arm + "_primary"] = primaryNs
      samples[arm + "_primary_available"] = primaryAvailable ? 1 : 0
      samples[arm + "_copy"] = timing.copyNs
      samples[arm + "_admit"] = timing.admissionNs
      samples[arm + "_meta"] = timing.metadataNs
      if record && arm == "on" {
        _ = panelMoved
        _ = timing
      }
    }
    if record, let off = samples["off"], let on = samples["on"] {
      rows.append([
        "stratum": stratum,
        "pair": pair,
        "block": pair / 200,
        "off_ns": off,
        "on_ns": on,
        "delta_ns": Int64(bitPattern: on) &- Int64(bitPattern: off),
        "off_primary_ns": samples["off_primary"] ?? 0,
        "on_primary_ns": samples["on_primary"] ?? 0,
        "primary_available": (samples["on_primary_available"] ?? 0) == 1 && (samples["off_primary_available"] ?? 0) == 1,
        "primary_delta_ns": Int64(bitPattern: samples["on_primary"] ?? 0) &- Int64(bitPattern: samples["off_primary"] ?? 0),
        "copy_ns": samples["on_copy"] ?? 0,
        "admission_ns": samples["on_admit"] ?? 0,
        "metadata_ns": samples["on_meta"] ?? 0,
        "endpoint": (samples["on_primary_available"] ?? 0) == 1 ? "update_call" : "unavailable",
        "event_queue_wait": "unknown",
        "content_included": false
      ])
    }
  }

  static func prepare(_ stratum: String) {
    // The caller has cleared the composition and selected the schema.
    switch stratum {
    case "short", "backspace", "number", "space", "mouse", "paging":
      type("niha")
    case "long":
      type(String(repeating: "n", count: 32))
    case "retype":
      type("niha")
      sendBackspace()
    default:
      break
    }
  }

  static func perform(_ stratum: String) {
    client.reset()
    switch stratum {
    case "short":
      type("o")
    case "long":
      type("i")
    case "backspace":
      sendBackspace()
    case "retype":
      type("o")
    case "number":
      sendKey(19, "2")
    case "space":
      sendKey(49, " ")
    case "mouse":
      _ = controller?.selectCandidate(1)
    case "paging":
      _ = controller?.page(up: false)
    default:
      break
    }
  }

  static func type(_ spelling: String) {
    let codes: [Character: UInt16] = [
      "n": 45, "i": 34, "h": 4, "a": 0, "o": 31
    ]
    for character in spelling {
      sendKey(codes[character] ?? 45, String(character))
    }
  }

  static func sendBackspace() {
    // A real delete event has a character, so production handle reaches processKey.
    // Empty characters are ignored by handle and must not be treated as backspace.
    sendKey(51, "\u{7f}")
  }

  static func sendKey(_ keyCode: UInt16, _ characters: String) {
    let event = keyEvent(keyCode: keyCode, characters: characters, flags: [])
    _ = controller?.handle(event, client: client)
  }

  static func keyEvent(keyCode: UInt16, characters: String, flags: NSEvent.ModifierFlags) -> NSEvent {
    NSEvent.keyEvent(
      with: .keyDown,
      location: .zero,
      modifierFlags: flags,
      timestamp: 0,
      windowNumber: 0,
      context: nil,
      characters: characters,
      charactersIgnoringModifiers: characters,
      isARepeat: false,
      keyCode: keyCode
    )!
  }

  /// Composes under a locally non-eligible state, becomes eligible part way
  /// through, then commits. The client must still receive the text once; the
  /// archive must not admit the prefix that was never observed.
  /// Composes under a locally non-eligible state, becomes eligible part way
  /// through a composition, then commits. The client must still receive the
  /// text exactly once; the archive must not admit the prefix that was never
  /// observed.
  static func runTransitionEdge() {
    expect(waitForPolicy("enabled"), "transition policy not fresh")
    selectLuna()
    clearComposition()
    client.reset()
    let previous = InputArchiveSignals.secureEventInputEnabled
    // An excluded composition is abandoned, then a second composition starts
    // while still ineligible and becomes eligible mid-way at "niha".
    InputArchiveSignals.secureEventInputEnabled = { true }
    typeCode("jiamin")
    clearComposition()
    type("niha")
    InputArchiveSignals.secureEventInputEnabled = previous
    type("o")
    sendKey(49, " ")
    let inserts = client.inserts
    expect(inserts.contains { $0.contains("你好") }, "mid-transition commit missing from client")
    expect(inserts.filter { $0.contains("你好") }.count == 1, "mid-transition commit was not inserted exactly once")
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
    selectLuna()
    clearComposition()
    client.reset()
    typeCode("jiazheng")
    sendKey(49, " ")
    expect(client.inserts.contains { $0.contains("甲正") }, "post-transition eligible commit missing from client")
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
  }

  /// Finalizes a live composition through deactivation so the stored raw
  /// terminal can be compared with the pages it closes.
  static func runTerminalProvenance() {
    expect(waitForPolicy("enabled"), "terminal policy not fresh")
    selectLuna()
    clearComposition()
    client.reset()
    typeCode("jiazheng")
    controller?.deactivateServer(client)
    controller?.activateServer(client)
    expect(client.inserts.contains { $0.contains("jiazheng") }, "deactivation raw finalization missing from client")
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
    clearComposition()
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
  }

  static func runSchemaGate() {
    expect(waitForPolicy("enabled"), "schema gate policy not fresh")
    selectLuna()
    clearComposition()
    typeCode("jiazheng")
    sendKey(49, " ")
    expect(client.inserts.contains { $0.contains("甲正") }, "eligible luna commit missing from client")
    selectOtherSchema()
    clearComposition()
    client.reset()
    typeCode("jiachi")
    sendKey(49, " ")
    expect(client.inserts.contains { $0.contains("甲斥") }, "excluded schema commit missing from client")
    client.reset()
    typeCode("jryuan")
    controller?.commitComposition(client)
    expect(client.inserts.contains { $0.contains("jryuan") }, "excluded raw finalization missing from client")
    selectLuna()
    let previous = InputArchiveSignals.secureEventInputEnabled
    InputArchiveSignals.secureEventInputEnabled = { true }
    client.reset()
    typeCode("jiamin")
    sendKey(49, " ")
    expect(client.inserts.contains { $0.contains("甲敏") }, "sensitive commit missing from client")
    InputArchiveSignals.secureEventInputEnabled = previous
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
  }

  static func typeCode(_ spelling: String) {
    let codes: [Character: UInt16] = [
      "j": 38, "i": 34, "a": 0, "z": 6, "h": 4, "e": 14, "n": 45, "g": 5,
      "c": 8, "r": 15, "y": 16, "u": 32
    ]
    for character in spelling {
      sendKey(codes[character] ?? 45, String(character))
    }
  }

  /// A held/failing collector must not block the real input path. The whole
  /// burst is timed by a separate watchdog bound rather than by the sender.
  static func runFaultBurst() {
    selectLuna()
    clearComposition()
    client.reset()
    let started = InputArchiveClock.now()
    for index in 0..<40 {
      typeCode(index % 2 == 0 ? "jiazheng" : "niha")
      sendKey(49, " ")
    }
    let elapsed = InputArchiveClock.nanoseconds(from: InputArchiveClock.now() &- started)
    expect(elapsed < 5_000_000_000, "held collector blocked the input path")
    expect(client.inserts.count >= 40, "held collector lost client insertions")
    let status = InputArchiveEngine.shared.contentFreeStatus()
    expect(status["content_included"] == "false", "status exposed content")
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 2)
  }

  /// A bounded management query issued while the frontend is working must not
  /// change observable input behavior or expose content.
  static func runConcurrentStatus() {
    selectLuna()
    clearComposition()
    client.reset()
    var statuses: [[String: String]] = []
    for _ in 0..<12 {
      typeCode("jiazheng")
      statuses.append(InputArchiveEngine.shared.contentFreeStatus())
      sendKey(53, "\u{1b}")
    }
    expect(statuses.allSatisfy { $0["content_included"] == "false" }, "management status exposed content")
    expect(statuses.allSatisfy { $0["globally_effective"] == "false" }, "status claimed global effectiveness")
    expect(statuses.allSatisfy { $0["legacy_switch_changed"] == "false" }, "legacy switch was reported changed")
    _ = InputArchiveEngine.shared.waitUntilDrained(timeout: 3)
  }

  static func runSocketCall(socket: String) {
    signal(SIGPIPE, SIG_DFL)
    let payload = String(repeating: "Z", count: 200_000)
    let result = InputArchiveSocket.call(
      socketPath: socket,
      op: "admit_batch",
      body: ["observations": [["payload": payload]]]
    )
    let code = ((result["error"] as? [String: Any])?["code"] as? String) ?? "ok"
    fputs("socket_call=\(code)\n", stderr)
    if result["ok"] as? Bool != true && code != "collector_unavailable" && code != "invalid_request" {
      fail("socket call code \(code)")
    }
  }

  static func runSenderCall(socket: String) {
    signal(SIGPIPE, SIG_DFL)
    InputArchiveEngine.shared.bind(socket: socket)
    Thread.sleep(forTimeInterval: 1.5)
    fputs("sender_call=survived\n", stderr)
  }

  static func meaningfulMarked(_ marked: [String]) -> [String] {
    marked.filter { !$0.isEmpty }
  }

  static func clearComposition() {
    sendKey(53, "\u{1b}")
  }

  static func selectOtherSchema() {
    _ = controller?.archiveSelectSchema("other_schema")
  }

  static func selectLuna() {
    _ = controller?.archiveSelectSchema("luna_pinyin")
  }

  static func waitForPolicy(_ desired: String) -> Bool {
    let deadline = Date().addingTimeInterval(5)
    while Date() < deadline {
      let status = InputArchiveEngine.shared.contentFreeStatus()
      if status["fresh"] == "true" && status["observed_desired"] == desired {
        return true
      }
      Thread.sleep(forTimeInterval: 0.05)
    }
    return false
  }

  static func expect(_ condition: Bool, _ message: String) {
    if !condition {
      failures.append(message)
    }
  }

  static func fail(_ message: String) {
    failures.append(message)
  }

  static func parse(_ arguments: [String]) -> [String: String] {
    var values: [String: String] = [:]
    var index = 1
    while index < arguments.count - 1 {
      let key = arguments[index]
      if key.hasPrefix("--") {
        values[String(key.dropFirst(2))] = arguments[index + 1]
        index += 2
      } else {
        index += 1
      }
    }
    return values
  }

  static func emit(_ path: String?) {
    let report: [String: Any] = [
      "failures": failures,
      "failure_count": failures.count,
      "content_included": false,
      "cwd_unchanged": FileManager.default.currentDirectoryPath == cwdAtStart
    ]
    guard let path, let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted]) else {
      return
    }
    try? data.write(to: URL(fileURLWithPath: path))
  }
}
