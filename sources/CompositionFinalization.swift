//
//  CompositionFinalization.swift
//  Squirrel
//

import Foundation

enum GlobalLifecycleOperation: String, CaseIterable {
  case deploy
  case syncUserData
  case terminate
  case powerOff
  case processExit
}

struct CompositionFinalizationState: Equatable {
  var hasActiveController: Bool
  var hasSession: Bool
  var hasClient: Bool
  var pendingInput: String?
  var rimeAvailable: Bool

  static func inactive(rimeAvailable: Bool) -> CompositionFinalizationState {
    CompositionFinalizationState(
      hasActiveController: false,
      hasSession: false,
      hasClient: false,
      pendingInput: nil,
      rimeAvailable: rimeAvailable
    )
  }
}

enum CompositionClientAction: Equatable {
  case leaveUnchanged
  case commitOnce(String)
  case clearLocalState
}

enum SessionDisposition: Equatable {
  case keep
  case destroyViaRime
  case forgetLocally
}

struct CompositionFinalizationPlan: Equatable {
  var clientAction: CompositionClientAction
  var hidePanel: Bool
  var sessionDisposition: SessionDisposition
  var createdSession: Bool
}

enum BackendFollowUp: Equatable {
  case none
  case shutdownAndReinitialize
  case syncUserData
  case cleanupAllSessions
  case shutdown
}

struct GlobalLifecyclePlan: Equatable {
  var composition: CompositionFinalizationPlan
  var backend: BackendFollowUp
}

protocol CompositionFinalizationHost: AnyObject {
  func currentCompositionState() -> CompositionFinalizationState
  func applyCompositionFinalization(_ plan: CompositionFinalizationPlan)
  func applyBackendFollowUp(_ followUp: BackendFollowUp)
}

enum CompositionFinalization {
  static func plan(for state: CompositionFinalizationState) -> CompositionFinalizationPlan {
    guard state.hasActiveController, state.hasSession else {
      return CompositionFinalizationPlan(
        clientAction: .leaveUnchanged,
        hidePanel: false,
        sessionDisposition: .keep,
        createdSession: false
      )
    }

    if !state.rimeAvailable {
      return CompositionFinalizationPlan(
        clientAction: .clearLocalState,
        hidePanel: true,
        sessionDisposition: .forgetLocally,
        createdSession: false
      )
    }

    let pending = state.pendingInput ?? ""
    let clientAction: CompositionClientAction
    if state.hasClient && !pending.isEmpty {
      clientAction = .commitOnce(pending)
    } else {
      clientAction = .clearLocalState
    }

    return CompositionFinalizationPlan(
      clientAction: clientAction,
      hidePanel: true,
      sessionDisposition: .destroyViaRime,
      createdSession: false
    )
  }

  static func plan(
    operation: GlobalLifecycleOperation,
    state: CompositionFinalizationState
  ) -> GlobalLifecyclePlan {
    let composition = plan(for: state)
    let backend: BackendFollowUp
    switch operation {
    case .deploy:
      backend = .shutdownAndReinitialize
    case .syncUserData:
      backend = state.rimeAvailable ? .syncUserData : .none
    case .terminate:
      backend = state.rimeAvailable ? .cleanupAllSessions : .none
    case .powerOff, .processExit:
      backend = state.rimeAvailable ? .shutdown : .none
    }
    return GlobalLifecyclePlan(composition: composition, backend: backend)
  }

  static func perform(_ operation: GlobalLifecycleOperation, on host: CompositionFinalizationHost) {
    let plan = plan(operation: operation, state: host.currentCompositionState())
    host.applyCompositionFinalization(plan.composition)
    host.applyBackendFollowUp(plan.backend)
  }
}
