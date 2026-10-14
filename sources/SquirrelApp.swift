//
//  SquirrelApp.swift
//  Squirrel
//
//  Process-wide paths. Fixture overrides exist so an isolated harness can call
//  the production setup path without touching ~/Library/Rime. Production launch
//  never sets them.
//

import Foundation

struct SquirrelApp {
  // periphery:ignore
  static var fixtureUserDirectory: URL?
  // periphery:ignore
  static var fixtureSharedSupportDirectory: URL?
  // periphery:ignore
  static var fixtureLogDirectory: URL?

  static var userDir: URL {
    fixtureUserDirectory ?? defaultUserDirectory
  }

  static let appDir = "/Library/Input Library/Squirrel.app".withCString { dir in
    URL(fileURLWithFileSystemRepresentation: dir, isDirectory: false, relativeTo: nil)
  }

  static var logDir: URL {
    fixtureLogDirectory
      ?? FileManager.default.temporaryDirectory.appending(component: "rime.squirrel", directoryHint: .isDirectory)
  }

  private static var defaultUserDirectory: URL {
    if let pwuid = getpwuid(getuid()) {
      return URL(
        fileURLWithFileSystemRepresentation: pwuid.pointee.pw_dir,
        isDirectory: true,
        relativeTo: nil
      ).appending(components: "Library", "Rime")
    }
    return try! FileManager.default.url(
      for: .libraryDirectory,
      in: .userDomainMask,
      appropriateFor: nil,
      create: false
    ).appendingPathComponent("Rime", isDirectory: true)
  }
}
