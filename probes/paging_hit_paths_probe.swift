//
//  paging_hit_paths_probe.swift
//  Isolated AC-121 seam probe. Compile with:
//  swiftc -parse-as-library sources/PagingHitPaths.swift \
//    probes/paging_hit_paths_probe.swift -o /tmp/ac121-probe && /tmp/ac121-probe
//

import CoreGraphics
import Foundation

@main
enum PagingHitPathsProbe {
  static func main() {
    var failures: [String] = []
    func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
      if !condition() {
        failures.append(message)
      }
    }

    let down = CGPath(rect: CGRect(x: 0, y: 0, width: 10, height: 10), transform: nil)
    let up = CGPath(rect: CGRect(x: 20, y: 0, width: 10, height: 10), transform: nil)
    let downPoint = CGPoint(x: 5, y: 5)
    let upPoint = CGPoint(x: 25, y: 5)
    let candidatePoint = CGPoint(x: 15, y: 5)
    let preeditPoint = CGPoint(x: 15, y: 20)

    var hits = PagingHitPaths()

    hits.synchronize(down: down, up: up)
    expect(hits.downPath != nil, "SCN-121-1 both-controls must set downPath")
    expect(hits.upPath != nil, "SCN-121-1 both-controls must set upPath")
    expect(hits.pagingUp(at: downPoint) == false, "SCN-121-1 down control pages down")
    expect(hits.pagingUp(at: upPoint) == true, "SCN-121-1 up control pages up")
    expect(hits.pagingUp(at: candidatePoint) == nil, "SCN-121-3 candidate region is not paging when both controls exist")
    expect(hits.pagingUp(at: preeditPoint) == nil, "SCN-121-3 preedit region is not paging when both controls exist")

    hits.synchronize(down: down, up: nil)
    expect(hits.downPath != nil, "SCN-121-2 first-page must keep downPath")
    expect(hits.upPath == nil, "SCN-121-2 first-page must clear upPath")
    expect(hits.pagingUp(at: downPoint) == false, "SCN-121-2 first-page down control still pages")
    expect(hits.pagingUp(at: upPoint) == nil, "SCN-121-2 first-page stale up region must not page")
    expect(hits.pagingUp(at: candidatePoint) == nil, "SCN-121-3 first-page candidate region is not paging")

    hits.synchronize(down: down, up: up)
    hits.synchronize(down: nil, up: up)
    expect(hits.downPath == nil, "SCN-121-2 last-page must clear downPath")
    expect(hits.upPath != nil, "SCN-121-2 last-page must keep upPath")
    expect(hits.pagingUp(at: upPoint) == true, "SCN-121-2 last-page up control still pages")
    expect(hits.pagingUp(at: downPoint) == nil, "SCN-121-2 last-page stale down region must not page")
    expect(hits.pagingUp(at: candidatePoint) == nil, "SCN-121-3 last-page candidate region is not paging")

    hits.synchronize(down: down, up: up)
    hits.synchronize(down: nil, up: nil)
    expect(hits.downPath == nil, "SCN-121-2 no-paging must clear downPath")
    expect(hits.upPath == nil, "SCN-121-2 no-paging must clear upPath")
    expect(hits.pagingUp(at: downPoint) == nil, "SCN-121-2 no-paging stale down region must not page")
    expect(hits.pagingUp(at: upPoint) == nil, "SCN-121-2 no-paging stale up region must not page")
    expect(hits.pagingUp(at: candidatePoint) == nil, "SCN-121-3 no-paging candidate region is not paging")
    expect(hits.pagingUp(at: preeditPoint) == nil, "SCN-121-3 no-paging preedit region is not paging")

    if failures.isEmpty {
      print("AC-121 paging hit-path probe: sync + stale-region checks passed")
    } else {
      fputs("AC-121 paging hit-path probe failed:\n", stderr)
      for failure in failures {
        fputs("- \(failure)\n", stderr)
      }
      exit(1)
    }
  }
}
