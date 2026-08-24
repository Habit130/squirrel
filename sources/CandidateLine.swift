//
//  CandidateLine.swift
//  Squirrel
//

import Foundation

extension NSAttributedString.Key {
  static let noBreak = NSAttributedString.Key("noBreak")
}

enum CandidateLine {
  static let emptyFormatFallback = "[candidate]"

  static func resolvedFormat(_ format: String) -> String {
    format.isEmpty ? emptyFormatFallback : format
  }

  static func ranges(of needle: String, in haystack: String) -> [Range<String.Index>] {
    var result: [Range<String.Index>] = []
    var searchStart = haystack.startIndex
    while searchStart < haystack.endIndex, let found = haystack.range(of: needle, range: searchStart..<haystack.endIndex) {
      result.append(found)
      searchStart = found.upperBound
    }
    return result
  }

  static func convert(range: Range<String.Index>, in string: String) -> NSRange {
    let startPos = range.lowerBound.utf16Offset(in: string)
    let endPos = range.upperBound.utf16Offset(in: string)
    return NSRange(location: startPos, length: endPos - startPos)
  }

  static func containedRange(location: Int, length: Int, limit: Int) -> NSRange? {
    guard location >= 0, length > 0, location <= limit, location + length <= limit else {
      return nil
    }
    return NSRange(location: location, length: length)
  }

  static func interiorNoBreakRange(of span: NSRange, limit: Int) -> NSRange? {
    containedRange(location: span.location + 1, length: span.length - 1, limit: limit)
  }

  static func shortLineNoBreakRange(lineLength: Int) -> NSRange? {
    guard lineLength <= 10 else { return nil }
    return containedRange(location: 1, length: lineLength - 1, limit: lineLength)
  }

  static func build(
    format: String,
    label: String,
    candidate: String,
    comment: String,
    labelAttrs: [NSAttributedString.Key: Any],
    candidateAttrs: [NSAttributedString.Key: Any],
    commentAttrs: [NSAttributedString.Key: Any]
  ) -> (line: NSMutableAttributedString, labeledLine: NSAttributedString) {
    let template = resolvedFormat(format)
    let line = NSMutableAttributedString(string: template, attributes: labelAttrs)
    for range in ranges(of: "[candidate]", in: line.string) {
      let convertedRange = convert(range: range, in: line.string)
      line.addAttributes(candidateAttrs, range: convertedRange)
      if candidate.count <= 5, let noBreak = interiorNoBreakRange(of: convertedRange, limit: line.length) {
        line.addAttribute(.noBreak, value: true, range: noBreak)
      }
    }
    for range in ranges(of: "[comment]", in: line.string) {
      let convertedRange = convert(range: range, in: line.string)
      line.addAttributes(commentAttrs, range: convertedRange)
    }
    line.mutableString.replaceOccurrences(of: "[label]", with: label, range: NSRange(location: 0, length: line.length))
    let labeledLine = line.copy() as! NSAttributedString
    line.mutableString.replaceOccurrences(of: "[candidate]", with: candidate, range: NSRange(location: 0, length: line.length))
    line.mutableString.replaceOccurrences(of: "[comment]", with: comment, range: NSRange(location: 0, length: line.length))
    if let noBreak = shortLineNoBreakRange(lineLength: line.length) {
      line.addAttribute(.noBreak, value: true, range: noBreak)
    }
    return (line, labeledLine)
  }
}
