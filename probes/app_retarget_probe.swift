//
//  app_retarget_probe.swift
//  Isolated AC-119 seam probe. Compile with:
//  swiftc -parse-as-library sources/AppRetarget.swift \
//    probes/app_retarget_probe.swift -o /tmp/ac119-probe && /tmp/ac119-probe
//

import Foundation

@main
enum AppRetargetProbe {
  static func main() {
    var failures: [String] = []
    func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
      if !condition() {
        failures.append(message)
      }
    }

    let schemaDefaults: [String: Bool] = [
      "ascii_mode": false,
      "no_inline": false,
      "inline": false,
      "vim_mode": false
    ]
    let appA: [String: Bool] = [
      "ascii_mode": true,
      "no_inline": true,
      "vim_mode": true
    ]
    let appB: [String: Bool] = [
      "ascii_mode": true,
      "inline": true
    ]
    let appBAsciiOff: [String: Bool] = [
      "ascii_mode": false
    ]

    func state(
      currentApp: String,
      incoming: String?,
      applied: [String: Bool]?,
      defaults: [String: Bool] = schemaDefaults,
      incomingOptions: [String: Bool],
      currentValues: [String: Bool]? = nil,
      nextUnknownIndex: UInt = 0,
      hasSession: Bool = true
    ) -> AppRetargetState {
      AppRetargetState(
        currentApp: currentApp,
        incomingBundleID: incoming,
        nextUnknownIndex: nextUnknownIndex,
        appliedOptions: applied,
        schemaDefaults: defaults,
        incomingOptions: incomingOptions,
        currentOptionValues: currentValues ?? defaults,
        hasSession: hasSession
      )
    }

    func options(after plan: AppRetargetPlan, startingFrom start: [String: Bool]) -> [String: Bool] {
      var options = start
      AppRetarget.apply(mutations: plan.mutations, to: &options)
      return options
    }

    // SCN-119-1 / AC119-1: A has keys B lacks → restore schema defaults.
    let aOptions = schemaDefaults.merging(appA) { _, applied in applied }
    let aToB = AppRetarget.plan(
      for: state(
        currentApp: "com.apple.Terminal",
        incoming: "com.google.Chrome",
        applied: appA,
        incomingOptions: appB,
        currentValues: aOptions
      )
    )
    expect(aToB.appChanged, "SCN-119-1 must detect app change")
    expect(aToB.sessionAction == .keep, "SCN-119-1 must keep the session")
    expect(aToB.compositionAction == .leaveUnchanged, "SCN-119-1 must not finalize")
    expect(aToB.refreshInline, "SCN-119-1 must recompute inline after option change")
    expect(aToB.nextApplied == appB, "SCN-119-1 next applied must be B only")
    let restored = Set(aToB.mutations.filter { $0.kind == .restoreDefault }.map(\.key))
    expect(restored == ["no_inline", "vim_mode"], "SCN-119-1 must restore A-only keys, got \(restored)")
    expect(
      aToB.mutations.contains(where: { $0.key == "no_inline" && $0.value == false && $0.kind == .restoreDefault }),
      "SCN-119-1 no_inline must return to schema default false"
    )
    expect(
      aToB.mutations.contains(where: { $0.key == "vim_mode" && $0.value == false && $0.kind == .restoreDefault }),
      "SCN-119-1 vim_mode must return to schema default false"
    )
    let afterAB = options(after: aToB, startingFrom: aOptions)
    expect(afterAB["ascii_mode"] == true, "SCN-119-1 ascii_mode stays B's true")
    expect(afterAB["no_inline"] == false, "SCN-119-1 no_inline restored")
    expect(afterAB["vim_mode"] == false, "SCN-119-1 vim_mode restored")
    expect(afterAB["inline"] == true, "SCN-119-1 inline takes B's value")

    // Configured → unconfigured (empty incoming options).
    let aToUnconfigured = AppRetarget.plan(
      for: state(
        currentApp: "com.apple.Terminal",
        incoming: "com.apple.Safari",
        applied: appA,
        incomingOptions: [:],
        currentValues: aOptions
      )
    )
    expect(aToUnconfigured.nextApplied?.isEmpty == true, "unconfigured B must apply no app options")
    let afterUnconfigured = options(after: aToUnconfigured, startingFrom: aOptions)
    expect(afterUnconfigured["ascii_mode"] == false, "unconfigured must restore ascii_mode")
    expect(afterUnconfigured["no_inline"] == false, "unconfigured must restore no_inline")
    expect(afterUnconfigured["vim_mode"] == false, "unconfigured must restore vim_mode")

    // SCN-119-2: same key, B's value wins.
    let aToBOff = AppRetarget.plan(
      for: state(
        currentApp: "com.apple.Terminal",
        incoming: "com.apple.dt.Xcode",
        applied: appA,
        incomingOptions: appBAsciiOff,
        currentValues: aOptions
      )
    )
    expect(
      !aToBOff.mutations.contains(where: { $0.key == "ascii_mode" && $0.kind == .restoreDefault }),
      "SCN-119-2 must not restore a key B still owns"
    )
    expect(
      aToBOff.mutations.contains(where: { $0.key == "ascii_mode" && $0.value == false && $0.kind == .applyIncoming }),
      "SCN-119-2 B's ascii_mode=false must win"
    )
    let afterBOff = options(after: aToBOff, startingFrom: aOptions)
    expect(afterBOff["ascii_mode"] == false, "SCN-119-2 effective ascii_mode is B's")

    // SCN-119-3: unknown/empty bundle restores A-only keys; naming is deterministic.
    let knownToUnknown = AppRetarget.plan(
      for: state(
        currentApp: "com.apple.Terminal",
        incoming: nil,
        applied: appA,
        incomingOptions: [:],
        currentValues: aOptions,
        nextUnknownIndex: 3
      )
    )
    expect(knownToUnknown.appName == "UnknownApp4", "SCN-119-3 first unknown name must be UnknownApp\(4), got \(knownToUnknown.appName)")
    expect(knownToUnknown.nextUnknownIndex == 4, "SCN-119-3 must increment the unknown counter once")
    expect(knownToUnknown.appChanged, "SCN-119-3 known→unknown is an app change")
    let afterUnknown = options(after: knownToUnknown, startingFrom: aOptions)
    expect(afterUnknown["ascii_mode"] == false, "SCN-119-3 unknown must not keep A's ascii_mode")
    expect(afterUnknown["no_inline"] == false, "SCN-119-3 unknown must not keep A's no_inline")
    expect(afterUnknown["vim_mode"] == false, "SCN-119-3 unknown must not keep A's vim_mode")

    let emptyBundle = AppRetarget.resolveApp(
      bundleIdentifier: "",
      currentApp: "com.apple.Terminal",
      nextUnknownIndex: 7
    )
    expect(emptyBundle.name == "UnknownApp8", "empty bundle must use the unknown-app name")
    expect(emptyBundle.nextUnknownIndex == 8, "empty bundle must increment once")

    let stayUnknown = AppRetarget.plan(
      for: state(
        currentApp: "UnknownApp4",
        incoming: nil,
        applied: [:],
        incomingOptions: [:],
        nextUnknownIndex: 4
      )
    )
    expect(stayUnknown.appName == "UnknownApp4", "repeat unknown must keep the same name")
    expect(stayUnknown.nextUnknownIndex == 4, "repeat unknown must not increment")
    expect(!stayUnknown.appChanged, "repeat unknown is not an app change")
    expect(stayUnknown.mutations.isEmpty, "repeat unknown must not rewrite options")
    expect(!stayUnknown.refreshInline, "repeat unknown must not refresh inline")
    expect(stayUnknown.sessionAction == .keep, "unknown naming must not recreate the session")

    let freshUnknownSession = AppRetarget.plan(
      for: state(
        currentApp: "UnknownApp4",
        incoming: nil,
        applied: nil,
        incomingOptions: [:],
        nextUnknownIndex: 4
      )
    )
    expect(freshUnknownSession.nextApplied?.isEmpty == true, "new session on unknown applies an empty option set")
    expect(freshUnknownSession.refreshInline, "new session must refresh inline after first apply")
    expect(freshUnknownSession.sessionAction == .keep, "new session apply must not recreate again")

    let unknownToKnown = AppRetarget.plan(
      for: state(
        currentApp: "UnknownApp4",
        incoming: "com.google.Chrome",
        applied: nil,
        incomingOptions: appB,
        currentValues: schemaDefaults,
        nextUnknownIndex: 4
      )
    )
    expect(unknownToKnown.appName == "com.google.Chrome", "SCN-119-3 unknown→known uses the real bundle ID")
    expect(unknownToKnown.nextUnknownIndex == 4, "unknown→known must not increment")
    expect(unknownToKnown.nextApplied == appB, "unknown→known applies B")
    let afterKnown = options(after: unknownToKnown, startingFrom: schemaDefaults)
    expect(afterKnown["inline"] == true, "unknown→known must set B's inline")
    expect(afterKnown["ascii_mode"] == true, "unknown→known must set B's ascii_mode")

    // SCN-119-4 / AC119-4: same-client activation does not reset.
    let sameClient = AppRetarget.plan(
      for: state(
        currentApp: "com.apple.Terminal",
        incoming: "com.apple.Terminal",
        applied: appA,
        incomingOptions: appA,
        currentValues: aOptions
      )
    )
    expect(!sameClient.appChanged, "SCN-119-4 same client is not an app change")
    expect(sameClient.sessionAction == .keep, "SCN-119-4 must keep the session")
    expect(sameClient.compositionAction == .leaveUnchanged, "SCN-119-4 must not finalize")
    expect(sameClient.mutations.isEmpty, "SCN-119-4 must not rewrite options")
    expect(!sameClient.refreshInline, "SCN-119-4 must not recompute inline")
    expect(sameClient.nextApplied == appA, "SCN-119-4 must leave applied options unchanged")
    expect(sameClient.nextDefaults == schemaDefaults, "SCN-119-4 must leave captured defaults unchanged")

    // SCN-119-5 / AC119-2: inline/soft_cursor recompute without schema-id change.
    let inlineFromA = AppRetarget.inlinePresentation(
      panelInlinePreedit: true,
      panelInlineCandidate: true,
      noInline: true,
      inline: false
    )
    expect(!inlineFromA.inlinePreedit, "Terminal no_inline disables inline preedit")
    expect(!inlineFromA.inlineCandidate, "Terminal no_inline disables inline candidate")
    expect(inlineFromA.softCursor, "soft_cursor is the inverse of inline preedit")

    expect(aToB.refreshInline, "SCN-119-5 app-option change must request inline refresh")
    let inlineFromB = AppRetarget.inlinePresentation(
      panelInlinePreedit: true,
      panelInlineCandidate: true,
      noInline: afterAB["no_inline"] ?? true,
      inline: afterAB["inline"] ?? false
    )
    expect(inlineFromB.inlinePreedit, "SCN-119-5 Chrome inline=true enables inline preedit")
    expect(inlineFromB.inlineCandidate, "SCN-119-5 restored no_inline re-enables inline candidate")
    expect(!inlineFromB.softCursor, "SCN-119-5 soft_cursor follows the new inline preedit")

    let unconfiguredInline = AppRetarget.inlinePresentation(
      panelInlinePreedit: true,
      panelInlineCandidate: true,
      noInline: afterUnconfigured["no_inline"] ?? true,
      inline: afterUnconfigured["inline"] ?? true
    )
    expect(unconfiguredInline.inlinePreedit, "schema default inline follows the panel")
    expect(unconfiguredInline.inlineCandidate, "schema default candidate follows the panel")
    expect(!unconfiguredInline.softCursor, "schema default soft_cursor is off when inline preedit is on")

    // SCN-119-6 / AC119-3: isolation never recreates the session, even with pending input.
    for plan in [aToB, aToUnconfigured, aToBOff, knownToUnknown, unknownToKnown, sameClient] {
      expect(plan.sessionAction == .keep, "SCN-119-6 \(plan.appName) must keep the session")
      expect(plan.compositionAction == .leaveUnchanged, "SCN-119-6 \(plan.appName) must not finalize")
    }

    // Recording walk: A → B → unconfigured → same-client, options stay isolated.
    var live = schemaDefaults
    var applied: [String: Bool]?
    var defaults = [String: Bool]()
    var currentApp = ""
    var unknownIndex: UInt = 0

    func step(bundle: String?, incomingOptions: [String: Bool]) -> AppRetargetPlan {
      let plan = AppRetarget.plan(
        for: AppRetargetState(
          currentApp: currentApp,
          incomingBundleID: bundle,
          nextUnknownIndex: unknownIndex,
          appliedOptions: applied,
          schemaDefaults: defaults,
          incomingOptions: incomingOptions,
          currentOptionValues: live,
          hasSession: true
        )
      )
      AppRetarget.apply(mutations: plan.mutations, to: &live)
      currentApp = plan.appName
      unknownIndex = plan.nextUnknownIndex
      applied = plan.nextApplied
      defaults = plan.nextDefaults
      return plan
    }

    let first = step(bundle: "com.apple.Terminal", incomingOptions: appA)
    expect(first.appChanged, "first attach is an app change")
    expect(live["ascii_mode"] == true && live["no_inline"] == true && live["vim_mode"] == true, "first attach applies A")

    let second = step(bundle: "com.google.Chrome", incomingOptions: appB)
    expect(second.refreshInline, "A→B must refresh inline")
    expect(live["ascii_mode"] == true, "walk A→B keeps B ascii_mode")
    expect(live["no_inline"] == false, "walk A→B restores no_inline")
    expect(live["vim_mode"] == false, "walk A→B restores vim_mode")
    expect(live["inline"] == true, "walk A→B applies inline")

    _ = step(bundle: "com.apple.Safari", incomingOptions: [:])
    expect(live["ascii_mode"] == false && live["inline"] == false, "walk B→unconfigured restores schema defaults")
    expect(applied?.isEmpty == true, "unconfigured applied set is empty")

    let fourth = step(bundle: "com.apple.Safari", incomingOptions: [:])
    expect(!fourth.appChanged && fourth.mutations.isEmpty && fourth.sessionAction == .keep, "same Safari activation is a no-op")
    expect(live["ascii_mode"] == false && live["inline"] == false, "same-client walk must not resurrect A/B options")

    // User toggled ascii_mode on an unconfigured app before any app option used that key.
    // Session-start snapshots must win over the live user value when restoring.
    live["ascii_mode"] = true
    let afterUserToggle = AppRetarget.plan(
      for: AppRetargetState(
        currentApp: "com.apple.Safari",
        incomingBundleID: "com.apple.Terminal",
        nextUnknownIndex: 0,
        appliedOptions: [:],
        schemaDefaults: schemaDefaults,
        incomingOptions: appA,
        currentOptionValues: live,
        hasSession: true
      )
    )
    expect(afterUserToggle.nextDefaults["ascii_mode"] == false, "must not recapture a user toggle as the schema default")
    AppRetarget.apply(mutations: afterUserToggle.mutations, to: &live)
    let backToSafari = AppRetarget.plan(
      for: AppRetargetState(
        currentApp: "com.apple.Terminal",
        incomingBundleID: "com.apple.Safari",
        nextUnknownIndex: 0,
        appliedOptions: afterUserToggle.nextApplied,
        schemaDefaults: afterUserToggle.nextDefaults,
        incomingOptions: [:],
        currentOptionValues: live,
        hasSession: true
      )
    )
    var restoredLive = live
    AppRetarget.apply(mutations: backToSafari.mutations, to: &restoredLive)
    expect(restoredLive["ascii_mode"] == false, "restore must use the session-start schema default, not the user toggle")

    if failures.isEmpty {
      print("AC-119 app-retarget probe: option-diff + inline recompute passed")
    } else {
      print("AC-119 app-retarget probe FAILED (\(failures.count)):")
      for failure in failures {
        print(" - \(failure)")
      }
      exit(1)
    }
  }
}
