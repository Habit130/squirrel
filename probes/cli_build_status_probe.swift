//
//  cli_build_status_probe.swift
//  Isolated AC-123 seam probe. Compile with:
//  swiftc -parse-as-library sources/CLIBuildStatus.swift \
//    probes/cli_build_status_probe.swift -o /tmp/ac123-probe && /tmp/ac123-probe
//

import Foundation

@main
enum CLIBuildStatusProbe {
  static func main() {
    if CommandLine.arguments.count > 2, CommandLine.arguments[1] == "--inject-deploy" {
      let succeeded = CommandLine.arguments[2] == "success"
      CLIBuildStatus.terminateProcess(with: CLIBuildStatus.outcome(deploySucceeded: succeeded))
    }

    var failures: [String] = []
    func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
      if !condition() {
        failures.append(message)
      }
    }

    let failed = CLIBuildStatus.outcome(deploySucceeded: false)
    expect(failed.exitStatus != 0, "SCN-123-1 seam must return nonzero exit status, got \(failed.exitStatus)")
    expect(
      failed.diagnostic == "Squirrel --build: deployment failed",
      "SCN-123-1 seam must emit the stable diagnostic, got \(String(describing: failed.diagnostic))"
    )

    let succeeded = CLIBuildStatus.outcome(deploySucceeded: true)
    expect(succeeded.exitStatus == 0, "SCN-123-2 seam must return exit status 0, got \(succeeded.exitStatus)")
    expect(succeeded.diagnostic == nil, "SCN-123-2 seam must not emit a failure diagnostic")

    let failureProcess = runInjected("failure")
    expect(failureProcess.status != 0, "SCN-123-1 process must exit nonzero, got \(failureProcess.status)")
    expect(
      failureProcess.stderr.contains("Squirrel --build: deployment failed"),
      "SCN-123-1 process must print the stable diagnostic on stderr, got \(failureProcess.stderr)"
    )

    let successProcess = runInjected("success")
    expect(successProcess.status == 0, "SCN-123-2 process must exit 0, got \(successProcess.status)")
    expect(
      !successProcess.stderr.contains("Squirrel --build: deployment failed"),
      "SCN-123-2 process must not print the failure diagnostic, got \(successProcess.stderr)"
    )

    if failures.isEmpty {
      print("AC-123 CLI --build deploy-status probe: seam + process checks passed")
    } else {
      print("AC-123 CLI --build deploy-status probe FAILED (\(failures.count)):")
      for failure in failures {
        print(" - \(failure)")
      }
      exit(1)
    }
  }

  private static func runInjected(_ result: String) -> (status: Int32, stderr: String) {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
    process.arguments = ["--inject-deploy", result]
    let err = Pipe()
    process.standardError = err
    process.standardOutput = FileHandle.nullDevice
    try! process.run()
    process.waitUntilExit()
    let stderr = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    return (process.terminationStatus, stderr)
  }
}
