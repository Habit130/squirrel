//
//  PagingHitPaths.swift
//  Squirrel
//

import CoreGraphics

struct PagingHitPaths {
  private(set) var downPath: CGPath?
  private(set) var upPath: CGPath?

  mutating func synchronize(down: CGPath?, up: CGPath?) {
    downPath = down.flatMap { $0.copy() }
    upPath = up.flatMap { $0.copy() }
  }

  func pagingUp(at point: CGPoint) -> Bool? {
    if let downPath, downPath.contains(point) {
      return false
    }
    if let upPath, upPath.contains(point) {
      return true
    }
    return nil
  }
}
