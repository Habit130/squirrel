//
//  modifier_physical_keys_probe.swift
//  Isolated AC-122 seam probe. Compile with:
//  swiftc -parse-as-library sources/ModifierPhysicalKeys.swift \
//    probes/modifier_physical_keys_probe.swift -o /tmp/ac122-probe && /tmp/ac122-probe
//

import AppKit
import Carbon

@main
enum ModifierPhysicalKeysProbe {
  static func main() {
    var failures: [String] = []
    func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
      if !condition() {
        failures.append(message)
      }
    }

    func events(
      last: NSEvent.ModifierFlags,
      next: NSEvent.ModifierFlags,
      keyCode: UInt16
    ) -> [ModifierPhysicalKeys.Event] {
      ModifierPhysicalKeys.events(lastModifiers: last, modifiers: next, eventKeyCode: keyCode)
    }

    let shiftL = UInt16(kVK_Shift)
    let shiftR = UInt16(kVK_RightShift)
    let commandL = UInt16(kVK_Command)
    let commandR = UInt16(kVK_RightCommand)
    let controlL = UInt16(kVK_Control)
    let optionL = UInt16(kVK_Option)
    let caps = UInt16(kVK_CapsLock)

    // SCN-122-1 single modifier change
    expect(
      events(last: [], next: .shift, keyCode: shiftL) == [
        .init(keyCode: shiftL, isRelease: false, isCapsLock: false)
      ],
      "SCN-122-1 left Shift press uses kVK_Shift"
    )
    expect(
      events(last: .shift, next: [], keyCode: shiftL) == [
        .init(keyCode: shiftL, isRelease: true, isCapsLock: false)
      ],
      "SCN-122-1 left Shift release uses kVK_Shift"
    )
    expect(
      events(last: [], next: .control, keyCode: controlL) == [
        .init(keyCode: controlL, isRelease: false, isCapsLock: false)
      ],
      "SCN-122-1 left Control press uses kVK_Control"
    )

    // AC122-3 L/R preserved when the event names that modifier
    expect(
      events(last: [], next: .shift, keyCode: shiftR) == [
        .init(keyCode: shiftR, isRelease: false, isCapsLock: false)
      ],
      "AC122-3 right Shift press keeps kVK_RightShift"
    )
    expect(
      events(last: [], next: .command, keyCode: commandR) == [
        .init(keyCode: commandR, isRelease: false, isCapsLock: false)
      ],
      "AC122-3 right Command press keeps kVK_RightCommand"
    )

    // SCN-122-2 delayed release + different press must not reuse the press keycode
    let delayed = events(last: .shift, next: .command, keyCode: commandL)
    expect(
      delayed == [
        .init(keyCode: shiftL, isRelease: true, isCapsLock: false),
        .init(keyCode: commandL, isRelease: false, isCapsLock: false)
      ],
      "SCN-122-2 Shift release is inferred left Shift, then Command press; not Command reused for both"
    )
    expect(
      delayed.count == 2 && delayed[0].keyCode != delayed[1].keyCode,
      "SCN-122-2 release and press use distinct key identities"
    )
    expect(
      delayed.first?.isRelease == true && delayed.last?.isRelease == false,
      "AC122-2 / SCN-122-2 releases are emitted before presses"
    )

    let delayedRightCommand = events(last: .shift, next: .command, keyCode: commandR)
    expect(
      delayedRightCommand == [
        .init(keyCode: shiftL, isRelease: true, isCapsLock: false),
        .init(keyCode: commandR, isRelease: false, isCapsLock: false)
      ],
      "AC122-3 unknown Shift side infers left; known right Command is preserved"
    )

    let twoReleasesThenPress = events(last: [.shift, .control], next: .option, keyCode: optionL)
    expect(
      twoReleasesThenPress == [
        .init(keyCode: shiftL, isRelease: true, isCapsLock: false),
        .init(keyCode: controlL, isRelease: true, isCapsLock: false),
        .init(keyCode: optionL, isRelease: false, isCapsLock: false)
      ],
      "AC122-2 multiple releases stay before the press and keep their own identities"
    )

    // SCN-122-3 caps lock stays a special Caps_Lock identity, not a release
    expect(
      events(last: [], next: .capsLock, keyCode: caps) == [
        .init(keyCode: caps, isRelease: false, isCapsLock: true)
      ],
      "SCN-122-3 Caps Lock on uses kVK_CapsLock special event"
    )
    expect(
      events(last: .capsLock, next: [], keyCode: caps) == [
        .init(keyCode: caps, isRelease: false, isCapsLock: true)
      ],
      "SCN-122-3 Caps Lock off is still a special Caps_Lock event, not a release"
    )
    expect(
      events(last: [], next: [.capsLock, .command], keyCode: commandL) == [
        .init(keyCode: caps, isRelease: false, isCapsLock: true),
        .init(keyCode: commandL, isRelease: false, isCapsLock: false)
      ],
      "SCN-122-3 Caps Lock keeps XK_Caps_Lock identity when another modifier is pressed"
    )

    // SCN-122-4 bogus remote key code 0
    expect(
      events(last: [], next: .shift, keyCode: 0) == [
        .init(keyCode: shiftL, isRelease: false, isCapsLock: false)
      ],
      "SCN-122-4 keyCode 0 Shift press infers left Shift"
    )
    expect(
      events(last: .shift, next: .command, keyCode: 0) == [
        .init(keyCode: shiftL, isRelease: true, isCapsLock: false),
        .init(keyCode: commandL, isRelease: false, isCapsLock: false)
      ],
      "SCN-122-4 keyCode 0 delayed Shift+Command infers each modifier separately"
    )
    expect(
      events(last: [], next: .capsLock, keyCode: 0) == [
        .init(keyCode: caps, isRelease: false, isCapsLock: true)
      ],
      "SCN-122-4 keyCode 0 Caps Lock infers kVK_CapsLock"
    )

    // SCN-122-5 no-change duplicate flagsChanged
    expect(
      events(last: .shift, next: .shift, keyCode: shiftL).isEmpty,
      "SCN-122-5 duplicate Shift flagsChanged emits no key events"
    )
    expect(
      events(last: [.shift, .command], next: [.shift, .command], keyCode: 0).isEmpty,
      "SCN-122-5 duplicate multi-modifier flagsChanged emits no key events"
    )

    if failures.isEmpty {
      print("AC-122 modifier physical-keys probe: SCN-122-1..5 passed")
    } else {
      print("AC-122 modifier physical-keys probe FAILED (\(failures.count)):")
      for failure in failures {
        print(" - \(failure)")
      }
      exit(1)
    }
  }
}
