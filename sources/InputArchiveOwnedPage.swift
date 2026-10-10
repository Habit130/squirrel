//
//  InputArchiveOwnedPage.swift
//  Squirrel
//
//  Owned copy of one observed frontend page. Values are copied out of librime
//  buffers before those buffers are freed, so a background sender never reads
//  the current mutable engine state.
//

import Foundation

struct InputArchiveOwnedPage {
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

  init(_ snapshot: InputArchiveSnapshot) {
    schemaId = String(snapshot.schemaId)
    preedit = String(snapshot.preedit)
    candidates = snapshot.candidates.map { String($0) }
    comments = snapshot.comments.map { String($0) }
    highlighted = snapshot.highlighted
    page = snapshot.page
    lastPage = snapshot.lastPage
    caretUTF16 = snapshot.caretUTF16
    inputLength = snapshot.inputLength
    application = String(snapshot.application)
    clientPresent = snapshot.clientPresent
  }

  func payload(operation: String, timing: InputArchiveTiming) -> [String: Any] {
    [
      "text": preedit,
      "preedit": preedit,
      "candidates": candidates,
      "comments": comments,
      "highlighted": highlighted,
      "page": page,
      "last_page": lastPage,
      "caret_utf16": caretUTF16,
      "input_length": inputLength,
      "application": InputArchiveTokens.token(application, fallback: "unknown_app"),
      "operation": operation,
      "candidate_order": "frontend_page_as_received",
      "host_persistence": "unknown",
      "clock_domain": timing.clockDomain,
      "endpoint": timing.endpoint,
      "event_queue_wait": timing.eventQueueWait,
      "timebase_numer": Int(InputArchiveClock.timebase.numer),
      "timebase_denom": Int(InputArchiveClock.timebase.denom)
    ]
  }
}
