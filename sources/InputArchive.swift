//
//  InputArchive.swift
//  Squirrel
//
//  Content-free session metadata and bounded admission types for the accepted
//  input-archive-v1 Interface. This file does not open archive storage.
//

import Carbon
import Darwin
import Foundation

enum InputArchive {
  static let interfaceVersion = "input-archive-v1"
  static let envelopeVersion = 1
  static let contentVersion = 1
  static let supportedSchema = "luna_pinyin"
  static let socketConfigKey = "input_archive/socket"

  static let propertySource = "squirrel_archive_source"
  static let propertyProcess = "squirrel_archive_process"
  static let propertyUpdate = "squirrel_archive_update"
  static let propertySegment = "squirrel_archive_segment"
  static let propertyAssociation = "squirrel_archive_association"

  static let queueCount = 256
  static let queueBytes = 1_048_576
  static let maxEventBytes = 65_536
  static let batchSize = 64
  static let freshnessWindowMs = 2_000
  static let heartbeatIntervalMs = 500
  static let connectTimeoutMs = 1_000
  static let sunPathLimit = 103

  static let safeTokenCharacters = CharacterSet(
    charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
  )

  static let synchronizedPathParts = [
    "CloudStorage", "Dropbox", "OneDrive", "Mobile Documents", "iCloud",
    "Google Drive", "com~apple~CloudDocs", "Box Sync", "SynologyDrive"
  ]
}

enum InputArchiveSignals {
  /// Production reads the platform secure-input flag. The isolated harness may
  /// replace this closure to prove the exclusion mapping without enabling
  /// system-wide secure input, which is not allocated.
  // periphery:ignore
  static var secureEventInputEnabled: () -> Bool = {
    IsSecureEventInputEnabled()
  }
}

struct InputArchiveAdmission {
  var admitted: Bool
  var code: String
  var captureSequence: Int?
  var priority: String

  static func refused(_ code: String) -> InputArchiveAdmission {
    InputArchiveAdmission(admitted: false, code: code, captureSequence: nil, priority: "low")
  }
}

struct InputArchiveTiming {
  var action = ""
  var entryTicks: UInt64 = 0
  var primaryEndTicks: UInt64 = 0
  var returnTicks: UInt64 = 0
  var endpoint = "unavailable"
  var metadataNs: UInt64 = 0
  var copyNs: UInt64 = 0
  var admissionNs: UInt64 = 0
  var eventQueueWait = "unknown"
  var clockDomain = "mach_absolute_time"
}

enum InputArchiveClock {
  static let timebase: mach_timebase_info_data_t = {
    var info = mach_timebase_info_data_t()
    mach_timebase_info(&info)
    return info
  }()

  static func now() -> UInt64 {
    mach_absolute_time()
  }

  static func nanoseconds(from ticks: UInt64) -> UInt64 {
    guard timebase.denom != 0 else { return 0 }
    return ticks * UInt64(timebase.numer) / UInt64(timebase.denom)
  }
}

enum InputArchiveTokens {
  static func isSafe(_ value: String) -> Bool {
    !value.isEmpty && value.count <= 128 && value.unicodeScalars.allSatisfy {
      InputArchive.safeTokenCharacters.contains($0)
    }
  }

  static func token(_ value: String?, fallback: String) -> String {
    guard let value, isSafe(value) else { return fallback }
    return value
  }

  static func fresh(_ prefix: String) -> String {
    let raw = UUID().uuidString.replacingOccurrences(of: "-", with: "")
    return String((prefix + raw).prefix(128))
  }
}

enum InputArchivePaths {
  static func refusal(for socketPath: String) -> String? {
    if !socketPath.hasPrefix("/") || socketPath.contains("\0") {
      return "invalid_request"
    }
    if socketPath.utf8.count > InputArchive.sunPathLimit {
      return "invalid_request"
    }
    let parts = socketPath.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
    if parts.contains("..") {
      return "invalid_request"
    }
    if parts.contains(where: InputArchive.synchronizedPathParts.contains) {
      return "unsafe_root"
    }

    var current = "/"
    for (index, part) in parts.enumerated() {
      if part == "." {
        continue
      }
      current = current == "/" ? current + part : current + "/" + part
      var info = stat()
      let result = current.withCString { lstat($0, &info) }
      if result != 0 {
        if errno == ENOENT {
          break
        }
        return "unsafe_root"
      }
      let fileType = info.st_mode & mode_t(S_IFMT)
      if fileType == mode_t(S_IFLNK) {
        return "unsafe_root"
      }
      if index < parts.count - 1 && fileType != mode_t(S_IFDIR) {
        return "invalid_request"
      }
      let url = URL(fileURLWithPath: current)
      if let values = try? url.resourceValues(forKeys: [.isAliasFileKey]),
         values.isAliasFile == true {
        return "unsafe_root"
      }
    }
    return nil
  }
}

struct InputArchiveSnapshot {
  var schemaId: String
  var preedit: String
  var candidates: [String]
  var comments: [String]
  var highlighted: Int
  var page: Int
  var lastPage: Bool
  var caretUTF16: Int
  var inputLength: Int
  var application: String
  var clientPresent: Bool
  var operation: String
}
