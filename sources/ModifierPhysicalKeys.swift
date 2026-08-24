//
//  ModifierPhysicalKeys.swift
//  Squirrel
//

import AppKit
import Carbon

enum ModifierPhysicalKeys {
  struct Event: Equatable {
    var keyCode: UInt16
    var isRelease: Bool
    var isCapsLock: Bool
  }

  private static let trackedFlags: [NSEvent.ModifierFlags] = [.shift, .control, .option, .command]

  static func events(
    lastModifiers: NSEvent.ModifierFlags,
    modifiers: NSEvent.ModifierFlags,
    eventKeyCode: UInt16
  ) -> [Event] {
    let changes = lastModifiers.symmetricDifference(modifiers)
    var result: [Event] = []

    if changes.contains(.capsLock) {
      result.append(Event(keyCode: UInt16(kVK_CapsLock), isRelease: false, isCapsLock: true))
    }

    var releases: [Event] = []
    var presses: [Event] = []
    for flag in trackedFlags where changes.contains(flag) {
      let event = Event(
        keyCode: physicalKeyCode(for: flag, eventKeyCode: eventKeyCode),
        isRelease: !modifiers.contains(flag),
        isCapsLock: false
      )
      if event.isRelease {
        releases.append(event)
      } else {
        presses.append(event)
      }
    }
    return result + releases + presses
  }

  private static func physicalKeyCode(for flag: NSEvent.ModifierFlags, eventKeyCode: UInt16) -> UInt16 {
    if matches(flag, eventKeyCode: eventKeyCode) {
      return eventKeyCode
    }
    return inferredLeftKeyCode(for: flag)
  }

  private static func matches(_ flag: NSEvent.ModifierFlags, eventKeyCode: UInt16) -> Bool {
    switch Int(eventKeyCode) {
    case kVK_Shift, kVK_RightShift:
      return flag.contains(.shift)
    case kVK_Control, kVK_RightControl:
      return flag.contains(.control)
    case kVK_Option, kVK_RightOption:
      return flag.contains(.option)
    case kVK_Command, kVK_RightCommand:
      return flag.contains(.command)
    case kVK_CapsLock:
      return flag.contains(.capsLock)
    default:
      return false
    }
  }

  private static func inferredLeftKeyCode(for flag: NSEvent.ModifierFlags) -> UInt16 {
    if flag.contains(.capsLock) {
      return UInt16(kVK_CapsLock)
    }
    if flag.contains(.shift) {
      return UInt16(kVK_Shift)
    }
    if flag.contains(.control) {
      return UInt16(kVK_Control)
    }
    if flag.contains(.option) {
      return UInt16(kVK_Option)
    }
    return UInt16(kVK_Command)
  }
}
