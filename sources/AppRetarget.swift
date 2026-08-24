//
//  AppRetarget.swift
//  Squirrel
//

import Foundation

struct ResolvedAppIdentity: Equatable {
  var name: String
  var nextUnknownIndex: UInt
  var appChanged: Bool
}

enum AppOptionMutationKind: Equatable {
  case restoreDefault
  case applyIncoming
}

struct AppOptionMutation: Equatable {
  var key: String
  var value: Bool
  var kind: AppOptionMutationKind
}

enum AppRetargetSessionAction: Equatable {
  case keep
}

enum AppRetargetCompositionAction: Equatable {
  case leaveUnchanged
}

struct AppRetargetState: Equatable {
  var currentApp: String
  var incomingBundleID: String?
  var nextUnknownIndex: UInt
  var appliedOptions: [String: Bool]?
  var schemaDefaults: [String: Bool]
  var incomingOptions: [String: Bool]
  var currentOptionValues: [String: Bool]
  var hasSession: Bool
}

struct AppRetargetPlan: Equatable {
  var appName: String
  var nextUnknownIndex: UInt
  var appChanged: Bool
  var sessionAction: AppRetargetSessionAction
  var compositionAction: AppRetargetCompositionAction
  var mutations: [AppOptionMutation]
  var nextApplied: [String: Bool]?
  var nextDefaults: [String: Bool]
  var refreshInline: Bool
}

struct InlinePresentation: Equatable {
  var inlinePreedit: Bool
  var inlineCandidate: Bool
  var softCursor: Bool
}

enum AppRetarget {
  static let unknownPrefix = "UnknownApp"

  static func resolveApp(
    bundleIdentifier: String?,
    currentApp: String,
    nextUnknownIndex: UInt
  ) -> ResolvedAppIdentity {
    if let bundle = bundleIdentifier, !bundle.isEmpty {
      return ResolvedAppIdentity(
        name: bundle,
        nextUnknownIndex: nextUnknownIndex,
        appChanged: bundle != currentApp
      )
    }
    if currentApp.hasPrefix(unknownPrefix) {
      return ResolvedAppIdentity(
        name: currentApp,
        nextUnknownIndex: nextUnknownIndex,
        appChanged: false
      )
    }
    let next = nextUnknownIndex &+ 1
    return ResolvedAppIdentity(
      name: "\(unknownPrefix)\(next)",
      nextUnknownIndex: next,
      appChanged: true
    )
  }

  static func capturedDefaults(
    existing: [String: Bool],
    incoming: [String: Bool],
    currentValues: [String: Bool]
  ) -> [String: Bool] {
    var defaults = existing
    for key in incoming.keys where defaults[key] == nil {
      defaults[key] = currentValues[key] ?? false
    }
    return defaults
  }

  static func optionMutations(
    previousApplied: [String: Bool],
    incoming: [String: Bool],
    schemaDefaults: [String: Bool]
  ) -> [AppOptionMutation] {
    var mutations: [AppOptionMutation] = []
    for key in previousApplied.keys.sorted() where incoming[key] == nil {
      mutations.append(
        AppOptionMutation(
          key: key,
          value: schemaDefaults[key] ?? false,
          kind: .restoreDefault
        )
      )
    }
    for (key, value) in incoming.sorted(by: { $0.key < $1.key }) {
      mutations.append(
        AppOptionMutation(
          key: key,
          value: value,
          kind: .applyIncoming
        )
      )
    }
    return mutations
  }

  static func apply(mutations: [AppOptionMutation], to options: inout [String: Bool]) {
    for mutation in mutations {
      options[mutation.key] = mutation.value
    }
  }

  static func inlinePresentation(
    panelInlinePreedit: Bool,
    panelInlineCandidate: Bool,
    noInline: Bool,
    inline: Bool
  ) -> InlinePresentation {
    let inlinePreedit = (panelInlinePreedit && !noInline) || inline
    let inlineCandidate = panelInlineCandidate && !noInline
    return InlinePresentation(
      inlinePreedit: inlinePreedit,
      inlineCandidate: inlineCandidate,
      softCursor: !inlinePreedit
    )
  }

  static func plan(for state: AppRetargetState) -> AppRetargetPlan {
    let identity = resolveApp(
      bundleIdentifier: state.incomingBundleID,
      currentApp: state.currentApp,
      nextUnknownIndex: state.nextUnknownIndex
    )
    let defaults = capturedDefaults(
      existing: state.schemaDefaults,
      incoming: state.incomingOptions,
      currentValues: state.currentOptionValues
    )
    let previousApplied = state.appliedOptions
    let applyNeeded = state.hasSession && (identity.appChanged || previousApplied == nil)
    let mutations = applyNeeded
      ? optionMutations(
        previousApplied: previousApplied ?? [:],
        incoming: state.incomingOptions,
        schemaDefaults: defaults
      )
      : []
    return AppRetargetPlan(
      appName: identity.name,
      nextUnknownIndex: identity.nextUnknownIndex,
      appChanged: identity.appChanged,
      sessionAction: .keep,
      compositionAction: .leaveUnchanged,
      mutations: mutations,
      nextApplied: applyNeeded ? state.incomingOptions : previousApplied,
      nextDefaults: applyNeeded ? defaults : state.schemaDefaults,
      refreshInline: applyNeeded
    )
  }
}
