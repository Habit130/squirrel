import Foundation

@main
enum CandidateLineProbe {
  static let roleKey = NSAttributedString.Key("role")
  static let labelAttrs: [NSAttributedString.Key: Any] = [roleKey: "label"]
  static let candidateAttrs: [NSAttributedString.Key: Any] = [roleKey: "candidate"]
  static let commentAttrs: [NSAttributedString.Key: Any] = [roleKey: "comment"]

  static func fail(_ message: String) -> Never {
    fputs("FAIL: \(message)\n", stderr)
    exit(1)
  }

  static func pass(_ message: String) {
    print("PASS: \(message)")
  }

  static func expect(_ condition: Bool, _ message: String) {
    if condition {
      pass(message)
    } else {
      fail(message)
    }
  }

  static func expectEqual<T: Equatable>(_ actual: T, _ expected: T, _ message: String) {
    if actual == expected {
      pass(message)
    } else {
      fail("\(message) (got \(actual), expected \(expected))")
    }
  }

  static func role(in line: NSAttributedString, at location: Int) -> String? {
    guard location >= 0, location < line.length else { return nil }
    return line.attribute(roleKey, at: location, effectiveRange: nil) as? String
  }

  static func build(
    format: String,
    label: String = "1",
    candidate: String = "候选",
    comment: String = "zhu"
  ) -> (line: NSMutableAttributedString, labeledLine: NSAttributedString) {
    CandidateLine.build(
      format: format,
      label: label,
      candidate: candidate,
      comment: comment,
      labelAttrs: labelAttrs,
      candidateAttrs: candidateAttrs,
      commentAttrs: commentAttrs
    )
  }

  static func main() {
    expectEqual(CandidateLine.resolvedFormat(""), "[candidate]", "empty format falls back to [candidate]")
    expectEqual(CandidateLine.resolvedFormat("[label]"), "[label]", "non-empty format is unchanged")

    expect(CandidateLine.shortLineNoBreakRange(lineLength: 0) == nil, "SCN-127-5 empty line has no no-break range")
    expect(CandidateLine.shortLineNoBreakRange(lineLength: 1) == nil, "SCN-127-5 length-1 line has no no-break range")
    expectEqual(
      CandidateLine.shortLineNoBreakRange(lineLength: 5) ?? NSRange(location: -1, length: -1),
      NSRange(location: 1, length: 4),
      "length-5 short-line no-break matches historical location 1 / length-1"
    )
    expect(CandidateLine.shortLineNoBreakRange(lineLength: 11) == nil, "lines longer than 10 skip short-line no-break")

    expect(
      CandidateLine.interiorNoBreakRange(of: NSRange(location: 0, length: 0), limit: 0) == nil,
      "zero-length [candidate] span has no interior no-break range"
    )
    expect(
      CandidateLine.interiorNoBreakRange(of: NSRange(location: 0, length: 1), limit: 1) == nil,
      "length-1 [candidate] span has no interior no-break range"
    )
    expectEqual(
      CandidateLine.interiorNoBreakRange(of: NSRange(location: 3, length: 11), limit: 20) ?? NSRange(location: -1, length: -1),
      NSRange(location: 4, length: 10),
      "ordinary [candidate] interior no-break is location+1 / length-1"
    )

    let emptyLine = NSMutableAttributedString(string: "")
    if let range = CandidateLine.shortLineNoBreakRange(lineLength: emptyLine.length) {
      emptyLine.addAttribute(.noBreak, value: true, range: range)
    }
    pass("applying optional no-break to empty line does not throw")

    let oneLine = NSMutableAttributedString(string: "x")
    if let range = CandidateLine.shortLineNoBreakRange(lineLength: oneLine.length) {
      oneLine.addAttribute(.noBreak, value: true, range: range)
    }
    pass("applying optional no-break to length-1 line does not throw")

    let empty = build(format: "")
    expectEqual(empty.line.string, "候选", "SCN-127-1 empty format renders candidate text")
    expectEqual(role(in: empty.line, at: 0), "candidate", "SCN-127-1 fallback candidate keeps candidate attributes")

    let labelOnly = build(format: "[label]", label: "2")
    expectEqual(labelOnly.line.string, "2", "SCN-127-2 label-only format renders the label")
    expectEqual(role(in: labelOnly.line, at: 0), "label", "SCN-127-2 label keeps label attributes")

    let candidateOnly = build(format: "[candidate]")
    expectEqual(candidateOnly.line.string, "候选", "SCN-127-3 candidate-only format renders the candidate")
    expectEqual(role(in: candidateOnly.line, at: 0), "candidate", "SCN-127-3 candidate keeps candidate attributes")

    let ordinary = build(format: "[label]. [candidate] [comment]", label: "1", candidate: "啊", comment: "a")
    expectEqual(ordinary.line.string, "1. 啊 a", "SCN-127-4 ordinary format replacement is unchanged")
    expectEqual(role(in: ordinary.line, at: 0), "label", "SCN-127-4 label span keeps label attributes")
    expectEqual(role(in: ordinary.line, at: 3), "candidate", "SCN-127-4 candidate span keeps candidate attributes")
    expectEqual(role(in: ordinary.line, at: 5), "comment", "SCN-127-4 comment span keeps comment attributes")

    let commentOnly = build(format: "[comment]", comment: "注")
    expectEqual(commentOnly.line.string, "注", "comment-only format renders the comment")

    let emptyComment = build(format: "[comment]", comment: "")
    expectEqual(emptyComment.line.string, "", "empty comment-only line stays empty without throwing")

    print("All candidate-line probes passed.")
  }
}
