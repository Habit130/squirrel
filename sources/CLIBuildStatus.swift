//
//  CLIBuildStatus.swift
//  Squirrel
//

import Foundation

enum CLIBuildStatus {
  static let failureDiagnostic = "Squirrel --build: deployment failed"

  struct Outcome: Equatable {
    var exitStatus: Int32
    var diagnostic: String?
  }

  static func outcome(deploySucceeded: Bool) -> Outcome {
    if deploySucceeded {
      return Outcome(exitStatus: 0, diagnostic: nil)
    }
    return Outcome(exitStatus: 1, diagnostic: failureDiagnostic)
  }

  static func terminateProcess(with outcome: Outcome) -> Never {
    if let diagnostic = outcome.diagnostic {
      fputs(diagnostic + "\n", stderr)
    }
    exit(outcome.exitStatus)
  }
}
