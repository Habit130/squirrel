//
//  composition_finalization_probe.swift
//  Isolated AC-118 seam probe. Compile with:
//  swiftc -parse-as-library sources/CompositionFinalization.swift \
//    probes/composition_finalization_probe.swift -o /tmp/ac118-probe && /tmp/ac118-probe
//

import Foundation

@main
enum CompositionFinalizationProbe {
  static func main() {
    var failures: [String] = []
    func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
      if !condition() {
        failures.append(message)
      }
    }

    // SCN-118-1..4 + AC118-2: valid client commits exactly once, then backend.
    let composing = CompositionFinalizationState(
      hasActiveController: true,
      hasSession: true,
      hasClient: true,
      pendingInput: "你好",
      rimeAvailable: true
    )
    let expectedCommit = CompositionFinalizationPlan(
      clientAction: .commitOnce("你好"),
      hidePanel: true,
      sessionDisposition: .destroyViaRime,
      createdSession: false
    )
    expect(CompositionFinalization.plan(for: composing) == expectedCommit, "composing+client must commit once")

    let backendByOp: [(GlobalLifecycleOperation, BackendFollowUp)] = [
      (.deploy, .shutdownAndReinitialize),
      (.syncUserData, .syncUserData),
      (.terminate, .cleanupAllSessions),
      (.powerOff, .shutdown),
      (.processExit, .shutdown)
    ]
    for (operation, backend) in backendByOp {
      let plan = CompositionFinalization.plan(operation: operation, state: composing)
      expect(plan.composition == expectedCommit, "\(operation.rawValue) must finalize composition first")
      expect(plan.backend == backend, "\(operation.rawValue) backend should be \(backend)")
      expect(!plan.composition.createdSession, "\(operation.rawValue) must not create a session")
    }

    // SCN-118-5 / AC118-3: nil client clears local state only.
    let nilClient = CompositionFinalizationState(
      hasActiveController: true,
      hasSession: true,
      hasClient: false,
      pendingInput: "你好",
      rimeAvailable: true
    )
    let expectedClear = CompositionFinalizationPlan(
      clientAction: .clearLocalState,
      hidePanel: true,
      sessionDisposition: .destroyViaRime,
      createdSession: false
    )
    expect(CompositionFinalization.plan(for: nilClient) == expectedClear, "nil client must clear locally, not insert")
    for operation in GlobalLifecycleOperation.allCases {
      let plan = CompositionFinalization.plan(operation: operation, state: nilClient)
      expect(plan.composition.clientAction == .clearLocalState, "\(operation.rawValue)+nil client must not commit")
    }

    let afterFinalize = CompositionFinalizationState(
      hasActiveController: true,
      hasSession: true,
      hasClient: false,
      pendingInput: "你好",
      rimeAvailable: false
    )
    let expectedForget = CompositionFinalizationPlan(
      clientAction: .clearLocalState,
      hidePanel: true,
      sessionDisposition: .forgetLocally,
      createdSession: false
    )
    expect(
      CompositionFinalization.plan(for: afterFinalize) == expectedForget,
      "after finalize, clear local state without librime session ops"
    )
    for operation in GlobalLifecycleOperation.allCases where operation != .deploy {
      let plan = CompositionFinalization.plan(operation: operation, state: afterFinalize)
      expect(plan.backend == .none, "\(operation.rawValue) after finalize must not call librime")
      expect(plan.composition.sessionDisposition == .forgetLocally, "\(operation.rawValue) after finalize must not destroy via rime")
    }
    expect(
      CompositionFinalization.plan(operation: .deploy, state: afterFinalize).backend == .shutdownAndReinitialize,
      "deploy after finalize still reinitializes"
    )

    // SCN-118-6 / AC118-4: idle / no-session is a no-op and must not create a session.
    let idleStates = [
      CompositionFinalizationState.inactive(rimeAvailable: true),
      CompositionFinalizationState.inactive(rimeAvailable: false),
      CompositionFinalizationState(
        hasActiveController: true,
        hasSession: false,
        hasClient: true,
        pendingInput: "你好",
        rimeAvailable: true
      )
    ]
    let expectedIdle = CompositionFinalizationPlan(
      clientAction: .leaveUnchanged,
      hidePanel: false,
      sessionDisposition: .keep,
      createdSession: false
    )
    for state in idleStates {
      expect(CompositionFinalization.plan(for: state) == expectedIdle, "idle/no-session must no-op: \(state)")
      for operation in GlobalLifecycleOperation.allCases {
        expect(
          !CompositionFinalization.plan(operation: operation, state: state).composition.createdSession,
          "\(operation.rawValue) idle must not create a session"
        )
      }
    }

    // Empty pending input is not a commit.
    let emptyPending = CompositionFinalizationState(
      hasActiveController: true,
      hasSession: true,
      hasClient: true,
      pendingInput: "",
      rimeAvailable: true
    )
    expect(
      CompositionFinalization.plan(for: emptyPending).clientAction == .clearLocalState,
      "empty pending input must not insert text"
    )

    // SCN-118-1..7 via a recording host (order, single commit, recreation).
    func runScenario(
      name: String,
      start: CompositionFinalizationState,
      operations: [GlobalLifecycleOperation],
      recreateAfterDeploy: Bool = false
    ) -> RecordingHost {
      let host = RecordingHost(state: start)
      for operation in operations {
        CompositionFinalization.perform(operation, on: host)
        if recreateAfterDeploy, operation == .deploy {
          host.recreateSession(pendingInput: "")
        }
      }
      expect(!host.events.contains(where: { $0 == "create_session" && host.createdDuringFinalize }), "\(name) created a session during finalize")
      return host
    }

    let deployHost = runScenario(name: "SCN-118-1", start: composing, operations: [.deploy], recreateAfterDeploy: true)
    expect(deployHost.inserted == ["你好"], "SCN-118-1 must insert pending text once, got \(deployHost.inserted)")
    expect(deployHost.rimeAvailable, "SCN-118-1 deploy must leave rime available")
    expect(deployHost.state.hasSession, "SCN-118-1 must allow session recreation")
    expect(deployHost.events.contains("initialize"), "SCN-118-1 must reinitialize")
    expect(deployHost.librimeAfterFinalizeExceptInit.isEmpty, "SCN-118-1 librime after finalize: \(deployHost.librimeAfterFinalizeExceptInit)")

    let syncHost = runScenario(name: "SCN-118-2", start: composing, operations: [.syncUserData])
    expect(syncHost.inserted == ["你好"], "SCN-118-2 must insert once, got \(syncHost.inserted)")
    expect(syncHost.events.contains("sync_user_data"), "SCN-118-2 must sync after finalize")
    expect(index(of: "insert:你好", in: syncHost.events)! < index(of: "sync_user_data", in: syncHost.events)!, "SCN-118-2 commit before sync")

    let quitHost = runScenario(name: "SCN-118-3", start: composing, operations: [.terminate, .processExit])
    expect(quitHost.inserted == ["你好"], "SCN-118-3 must insert once across quit+exit, got \(quitHost.inserted)")
    expect(quitHost.events.contains("cleanup_all_sessions"), "SCN-118-3 must clean sessions after commit")
    expect(quitHost.events.contains("finalize"), "SCN-118-3 process-exit must finalize")
    expect(quitHost.librimeAfterFinalizeExceptInit.isEmpty, "SCN-118-3 librime after finalize: \(quitHost.librimeAfterFinalizeExceptInit)")

    let powerHost = runScenario(name: "SCN-118-4", start: composing, operations: [.powerOff, .processExit])
    expect(powerHost.inserted == ["你好"], "SCN-118-4 must insert once, got \(powerHost.inserted)")
    expect(powerHost.events.contains("finalize"), "SCN-118-4 must finalize")
    expect(powerHost.librimeAfterFinalizeExceptInit.isEmpty, "SCN-118-4 librime after finalize: \(powerHost.librimeAfterFinalizeExceptInit)")

    for operation in GlobalLifecycleOperation.allCases {
      let host = runScenario(name: "SCN-118-5-\(operation.rawValue)", start: nilClient, operations: [operation])
      expect(host.inserted.isEmpty, "SCN-118-5 \(operation.rawValue) must not insert, got \(host.inserted)")
      expect(host.events.contains("clearLocal"), "SCN-118-5 \(operation.rawValue) must clear local state")
      expect(host.events.contains("hidePanel"), "SCN-118-5 \(operation.rawValue) must hide panel")
    }

    for operation in GlobalLifecycleOperation.allCases {
      let host = runScenario(
        name: "SCN-118-6-\(operation.rawValue)",
        start: .inactive(rimeAvailable: true),
        operations: [operation]
      )
      expect(host.inserted.isEmpty, "SCN-118-6 \(operation.rawValue) must not insert")
      expect(!host.events.contains("create_session"), "SCN-118-6 \(operation.rawValue) must not create a session")
      expect(!host.events.contains("destroy_session"), "SCN-118-6 \(operation.rawValue) must not touch a missing session")
    }

    let recreate = runScenario(
      name: "SCN-118-7",
      start: composing,
      operations: [.deploy, .terminate],
      recreateAfterDeploy: true
    )
    expect(recreate.inserted == ["你好"], "SCN-118-7 must not double-commit the first composition, got \(recreate.inserted)")
    expect(recreate.createdAfterDeploy, "SCN-118-7 must allow createSession after deploy")

    // Exhaustive planner matrix: no create, no post-finalize session destroy, no empty commit.
    var matrixCases = 0
    for hasController in [false, true] {
      for hasSession in [false, true] {
        for hasClient in [false, true] {
          for pending in [nil, Optional(""), Optional("词")] {
            for rimeAvailable in [false, true] {
              matrixCases += 1
              let state = CompositionFinalizationState(
                hasActiveController: hasController,
                hasSession: hasSession,
                hasClient: hasClient,
                pendingInput: pending,
                rimeAvailable: rimeAvailable
              )
              let composition = CompositionFinalization.plan(for: state)
              expect(!composition.createdSession, "matrix must never create a session: \(state)")
              if case .commitOnce(let text) = composition.clientAction {
                expect(hasClient && hasSession && rimeAvailable && text == "词" && pending == "词", "unexpected commit \(text) for \(state)")
              }
              if !rimeAvailable {
                expect(composition.sessionDisposition != .destroyViaRime, "no destroyViaRime after finalize: \(state)")
              }
              for operation in GlobalLifecycleOperation.allCases {
                let plan = CompositionFinalization.plan(operation: operation, state: state)
                expect(!plan.composition.createdSession, "\(operation.rawValue) matrix created a session")
                if !state.rimeAvailable && operation != .deploy {
                  expect(plan.backend == .none, "\(operation.rawValue) matrix called librime after finalize")
                }
              }
            }
          }
        }
      }
    }
    expect(matrixCases == 48, "expected 48 legal matrix cells, got \(matrixCases)")

    if failures.isEmpty {
      print("AC-118 composition finalization probe: \(matrixCases) matrix cells + scenario checks passed")
    } else {
      print("AC-118 composition finalization probe FAILED (\(failures.count)):")
      for failure in failures {
        print(" - \(failure)")
      }
      exit(1)
    }
  }
}

private func index(of event: String, in events: [String]) -> Int? {
  events.firstIndex(of: event)
}

private final class RecordingHost: CompositionFinalizationHost {
  var state: CompositionFinalizationState
  var events: [String] = []
  var inserted: [String] = []
  var createdDuringFinalize = false
  var createdAfterDeploy = false
  private var finalized = false

  var rimeAvailable: Bool { state.rimeAvailable }

  var librimeAfterFinalizeExceptInit: [String] {
    var phase = 0
    var unexpected: [String] = []
    for event in events {
      if event == "finalize" {
        phase = 1
        continue
      }
      if event == "initialize" {
        if phase == 1 { phase = 2 }
        continue
      }
      if phase == 1 && isLibrime(event) {
        unexpected.append(event)
      }
    }
    return unexpected
  }

  init(state: CompositionFinalizationState) {
    self.state = state
  }

  func currentCompositionState() -> CompositionFinalizationState {
    state
  }

  func applyCompositionFinalization(_ plan: CompositionFinalizationPlan) {
    if plan.createdSession {
      createdDuringFinalize = true
      events.append("create_session")
    }
    switch plan.clientAction {
    case .leaveUnchanged:
      break
    case .commitOnce(let text):
      events.append("insert:\(text)")
      inserted.append(text)
      state.pendingInput = nil
    case .clearLocalState:
      events.append("clearLocal")
      state.pendingInput = nil
    }
    if plan.hidePanel {
      events.append("hidePanel")
    }
    switch plan.sessionDisposition {
    case .keep:
      break
    case .destroyViaRime:
      events.append("destroy_session")
      state.hasSession = false
      state.pendingInput = nil
    case .forgetLocally:
      events.append("forgetSession")
      state.hasSession = false
    }
  }

  func applyBackendFollowUp(_ followUp: BackendFollowUp) {
    switch followUp {
    case .none:
      break
    case .shutdownAndReinitialize:
      if state.rimeAvailable {
        events.append("finalize")
        finalized = true
        state.rimeAvailable = false
        state.hasSession = false
      }
      events.append("initialize")
      state.rimeAvailable = true
    case .syncUserData:
      events.append("sync_user_data")
      state.hasSession = false
    case .cleanupAllSessions:
      events.append("cleanup_all_sessions")
      state.hasSession = false
    case .shutdown:
      events.append("finalize")
      finalized = true
      state.rimeAvailable = false
      state.hasSession = false
    }
  }

  func recreateSession(pendingInput: String) {
    precondition(state.rimeAvailable, "createSession requires an initialized backend")
    events.append("create_session")
    createdAfterDeploy = true
    state.hasSession = true
    state.pendingInput = pendingInput
  }
}

private func isLibrime(_ event: String) -> Bool {
  switch event {
  case "destroy_session", "sync_user_data", "cleanup_all_sessions", "finalize", "get_input", "clear_composition", "create_session":
    return true
  default:
    return event.hasPrefix("insert:") == false && event != "clearLocal" && event != "hidePanel" && event != "forgetSession" && event != "initialize"
  }
}
