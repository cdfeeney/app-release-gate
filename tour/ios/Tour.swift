import XCTest

// app-release-gate: generic screenshot tour for any iOS app.
//
// This file is COPIED into each app's UI test target unchanged; the gate verifies the copy matches
// the kit (scripts/verify-copy.py). Per-app behaviour lives in Gate/tour.json beside this file.
//
// What it does: launches the app with the fixtures the manifest names, follows the manifest's steps
// (tap, wait, scroll, type), and at every stop writes a PNG screenshot plus the accessibility tree
// (app.debugDescription) to TOUR_OUT. Every tap records whether the screen changed. Deterministic:
// no LLM, no synthetic taps; XCUITest drives real controls.
//
// Paths: TOUR_PATH / TOUR_OUT come from the environment (xcodebuild passes TEST_RUNNER_TOUR_PATH as
// TOUR_PATH); otherwise Gate/tour.json and Gate/out beside this file. On the simulator the test
// runner reads and writes host paths directly (the same mechanism snapshot-testing libraries use
// to write reference images beside the test file via #filePath).
@MainActor
final class TourTests: XCTestCase {
    struct Manifest: Decodable {
        var launchArguments: [String]?
        var launchEnvironment: [String: String]?
        var fixtureEnvKey: String?
        var fixtures: [Fixture]?
        var flows: [Flow]
    }

    struct Fixture: Decodable {
        var name: String
        var file: String
        var setDateKeyToToday: String?
        var week: Int?
    }

    struct Flow: Decodable {
        var name: String
        var steps: [Step]
    }

    struct Step: Decodable {
        var tap: String?
        var tapMatching: String?
        var waitFor: String?
        var scrollToBottom: Bool?
        var swipe: String?
        var shot: String?
        var expectChange: Bool?
        var typeText: String?
        var sleep: Double?
        var optional: Bool?
    }

    private static let maxScrollStops = 25
    private static let maxCandidates = 3   // tapMatching: how many matching identifiers to try to reveal before giving up

    private var outDir: URL!
    private var shotIndex = 0
    private var index: [[String: Any]] = []
    private var taps: [[String: Any]] = []
    private var problems: [String] = []
    /// Identifiers seen at any capture of the current flow, in first-seen (top-to-bottom) order. Lazy lists drop
    /// off-screen rows from the live tree, so `tapMatching` searches this union, not just what is on screen now.
    private var seenIdentifiers: [String] = []
    private var seenIdentifierSet = Set<String>()

    private var gateDir: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Gate")
    }

    func testTour() throws {
        continueAfterFailure = true
        let env = ProcessInfo.processInfo.environment
        let manifestURL = env["TOUR_PATH"].map { URL(fileURLWithPath: $0) } ?? gateDir.appendingPathComponent("tour.json")
        outDir = env["TOUR_OUT"].map { URL(fileURLWithPath: $0) } ?? gateDir.appendingPathComponent("out")
        try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        let manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: manifestURL))

        var fixtures: [Fixture?] = (manifest.fixtures ?? []).map { Optional($0) }
        if fixtures.isEmpty { fixtures = [nil] }
        for fixture in fixtures {
            let app = XCUIApplication()
            app.launchArguments = (manifest.launchArguments ?? []).map { $0.replacingOccurrences(of: "{uuid}", with: UUID().uuidString) }
            var environment = manifest.launchEnvironment ?? [:]
            if let fixture = fixture, let key = manifest.fixtureEnvKey {
                environment[key] = try fixtureJSON(fixture, relativeTo: manifestURL.deletingLastPathComponent())
            }
            app.launchEnvironment = environment
            guard launch(app) else {
                // Never tour a dead app: a capture of nothing would still count as a screen.
                problems.append("\(fixture?.name ?? "default"): the app never reached the foreground after \(Self.launchAttempts) launches")
                app.terminate()
                continue
            }
            for flow in manifest.flows {
                run(flow, fixture: fixture?.name ?? "default", in: app)
            }
            app.terminate()
        }
        if index.isEmpty { problems.append("the tour captured no screens") }
        try write(json: index, name: "index.json")
        try write(json: taps, name: "taps.json")
        try write(json: ["problems": problems, "fixtures": fixtures.map { $0?.name ?? "default" }, "screens": index.count], name: "summary.json")
        XCTAssertTrue(problems.isEmpty, problems.joined(separator: "\n"))
    }

    /// A simulator under load sometimes fails the first launch with "Failed to get background assertion for target
    /// app … Timed out" (ConorHealth runs 1 and 4): a runner condition, not the app. Up to two such failures are
    /// expected and retried; the third attempt counts like any other failure.
    static let launchAttempts = 3
    static let launchFlake = "Timed out while acquiring background assertion"   // the runner's exact wording; a crash reads differently
    private func launch(_ app: XCUIApplication) -> Bool {
        for attempt in 1..<Self.launchAttempts {
            let options = XCTExpectedFailure.Options()
            options.isStrict = false
            options.issueMatcher = { $0.compactDescription.contains(Self.launchFlake) }
            XCTExpectFailure("simulator launch flake, attempt \(attempt)", options: options) { app.launch() }
            if app.state == .runningForeground { return true }
            app.terminate()
            Thread.sleep(forTimeInterval: 5)
        }
        app.launch()
        return app.state == .runningForeground
    }

    // MARK: steps

    private func run(_ flow: Flow, fixture: String, in app: XCUIApplication) {
        seenIdentifiers = []
        seenIdentifierSet = []
        for (i, step) in flow.steps.enumerated() {
            let label = "\(fixture)/\(flow.name)/step\(i)"
            if let id = step.waitFor {
                if !element(id, in: app).waitForExistence(timeout: 15) { note("\(label): \(id) never appeared", optional: step.optional) }
            }
            if let seconds = step.sleep { Thread.sleep(forTimeInterval: seconds) }
            if let swipe = step.swipe {
                if swipe == "down" { app.swipeDown(velocity: .slow) } else { app.swipeUp(velocity: .slow) }
            }
            var target = step.tap
            var resolved = false
            if target == nil, let pattern = step.tapMatching {
                let candidates = matchingIdentifiers(pattern, in: app)
                if candidates.isEmpty {
                    note("\(label): no element matches \(pattern)", optional: step.optional)
                } else {
                    // The element exists in this app: from here on nothing about this step is optional.
                    resolved = true
                    let tried = Array(candidates.prefix(Self.maxCandidates))
                    target = tried.first { reveal(element($0, in: app), in: app) }
                    if target == nil {
                        taps.append(["identifier": tried[0], "step": label, "changed": false, "expected": step.expectChange ?? true, "revealed": false])
                        note("\(label): \(candidates.count) identifier(s) match \(pattern) but none could be revealed: \(tried)", optional: false)
                    }
                }
            }
            if let id = target {
                var optional = step.optional
                if resolved { optional = false }
                tap(id, label: label, expectChange: step.expectChange ?? true, optional: optional, in: app)
            }
            if let text = step.typeText { app.typeText(text) }
            // Every capture names its screen; unnamed scrolls get a unique name so rules never merge two UI states.
            let screen = step.shot ?? "step\(i)"
            if step.scrollToBottom == true {
                scrollToBottom(fixture: fixture, flow: flow.name, screen: screen, label: label, in: app)
            } else if step.shot != nil {
                capture(fixture: fixture, flow: flow.name, screen: screen, name: screen, in: app)
            }
        }
    }

    private func tap(_ id: String, label: String, expectChange: Bool, optional: Bool?, in app: XCUIApplication) {
        let target = element(id, in: app)
        guard reveal(target, in: app) else {
            if optional != true {
                taps.append(["identifier": id, "step": label, "changed": false, "expected": expectChange, "revealed": false])
            }
            note("\(label): \(id) not tappable (exists=\(target.exists))", optional: optional)
            return
        }
        let before = normalized(app.debugDescription)
        // tap() returns once the app is idle again, so a main-thread stall after the tap lands in `ms`
        // (owner 10-17: "buttons take three or four seconds"); the rules compare it with maxTapMillis.
        let started = Date()
        target.tap()
        let idleMs = Int(Date().timeIntervalSince(started) * 1000)   // the app's own response: tap() returns once it is idle again
        let settleMs = settle(in: app)
        var changed = false
        if expectChange {
            for _ in 0..<12 {
                if normalized(app.debugDescription) != before { changed = true; break }
                Thread.sleep(forTimeInterval: 0.25)
            }
        } else {
            changed = normalized(app.debugDescription) != before   // one look: a tap expected to change nothing is not polled for 3 s
        }
        let ms = Int(Date().timeIntervalSince(started) * 1000)   // until the tree first differed: includes one tree snapshot (~1 s on a big screen)
        var entry: [String: Any] = ["identifier": id, "step": label, "changed": changed, "expected": expectChange, "ms": ms, "idleMs": idleMs]
        if let settleMs { entry["settleMs"] = settleMs }
        taps.append(entry)
        if expectChange && !changed { note("\(label): tapping \(id) changed nothing on screen", optional: optional) }
    }

    /// Work an app defers past the tap (a debounced write 700 ms later) escapes `idleMs`, so after `settleDelay` a
    /// harmless tap on the centre of the navigation bar is timed: XCUITest waits for the app to be idle before it
    /// dispatches any event, so that wait is the stall the next real tap would have felt. Nil without a navigation bar.
    static let settleDelay: TimeInterval = 0.8
    private func settle(in app: XCUIApplication) -> Int? {
        let bar = app.navigationBars.firstMatch
        guard bar.exists else { return nil }
        Thread.sleep(forTimeInterval: Self.settleDelay)
        let started = Date()
        bar.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        return Int(Date().timeIntervalSince(started) * 1000)
    }

    /// Capture, swipe up, capture again, until the tree stops changing. Every state that exists is captured.
    private func scrollToBottom(fixture: String, flow: String, screen: String, label: String, in app: XCUIApplication) {
        var last = ""
        var settled = false
        for position in 1...Self.maxScrollStops {
            capture(fixture: fixture, flow: flow, screen: screen, name: "\(screen)-\(String(format: "%02d", position))", in: app)
            let now = normalized(app.debugDescription)
            if now == last { settled = true; break }
            last = now
            app.swipeUp(velocity: .slow)
            Thread.sleep(forTimeInterval: 0.4)
        }
        if !settled { note("\(label): \(screen) never stopped scrolling after \(Self.maxScrollStops) swipes; bottom not captured", optional: false) }
    }

    private func capture(fixture: String, flow: String, screen: String, name: String, in app: XCUIApplication) {
        shotIndex += 1
        let base = String(format: "%03d", shotIndex) + "-\(fixture)-\(flow)-\(name)"
        let png = XCUIScreen.main.screenshot().pngRepresentation
        let tree = app.debugDescription
        remember(identifiers(in: tree))
        do {
            try png.write(to: outDir.appendingPathComponent(base + ".png"))
            try tree.write(to: outDir.appendingPathComponent(base + ".tree.txt"), atomically: true, encoding: .utf8)
        } catch {
            note("capture \(base) failed: \(error)", optional: false)
        }
        if png.isEmpty || tree.isEmpty { note("capture \(base) is empty", optional: false) }
        index.append(["n": shotIndex, "fixture": fixture, "flow": flow, "screen": screen, "name": name,
                      "png": base + ".png", "tree": base + ".tree.txt",
                      "window": ["width": Double(app.frame.width), "height": Double(app.frame.height)]])
    }

    // MARK: helpers

    private func element(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func identifiers(in tree: String) -> [String] {
        var ids: [String] = []
        for line in tree.components(separatedBy: "\n") {
            guard let range = line.range(of: "identifier: '") else { continue }
            let rest = line[range.upperBound...]
            guard let end = rest.firstIndex(of: "'") else { continue }
            ids.append(String(rest[..<end]))
        }
        return ids
    }

    private func remember(_ ids: [String]) {
        for id in ids where !seenIdentifierSet.contains(id) {
            seenIdentifierSet.insert(id)
            seenIdentifiers.append(id)
        }
    }

    /// Identifiers matching the pattern, in order: what is on screen now first (certainly this screen), then
    /// everything this flow has captured so far, top to bottom (lazy lists drop off-screen rows from the live tree).
    private func matchingIdentifiers(_ pattern: String, in app: XCUIApplication) -> [String] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        var ordered: [String] = []
        var seen = Set<String>()
        for id in identifiers(in: app.debugDescription) + seenIdentifiers where !seen.contains(id) {
            seen.insert(id)
            if regex.firstMatch(in: id, range: NSRange(id.startIndex..., in: id)) != nil { ordered.append(id) }
        }
        return ordered
    }

    /// Make the target hittable and say whether it is: if it is not on screen (or not even in the live tree),
    /// scroll back to the top until the tree stops changing, then walk down until it is hittable or the end.
    @discardableResult
    private func reveal(_ target: XCUIElement, in app: XCUIApplication) -> Bool {
        if target.exists && target.isHittable { return true }
        var last = ""
        for _ in 0..<Self.maxScrollStops {
            if target.exists && target.isHittable { return true }
            let now = normalized(app.debugDescription)
            if now == last { break }
            last = now
            app.swipeDown(velocity: .slow)
        }
        last = ""
        for _ in 0..<Self.maxScrollStops {
            if target.exists && target.isHittable { return true }
            let now = normalized(app.debugDescription)
            if now == last { return false }
            last = now
            app.swipeUp(velocity: .slow)
        }
        return target.exists && target.isHittable
    }

    private func normalized(_ tree: String) -> String {
        // Drop object addresses and pids so two dumps of the same screen compare equal.
        tree.replacingOccurrences(of: "0x[0-9a-fA-F]+", with: "0x", options: .regularExpression)
            .replacingOccurrences(of: "pid: [0-9]+", with: "pid", options: .regularExpression)
    }

    private func note(_ problem: String, optional: Bool?) {
        if optional == true { return }
        problems.append(problem)
    }

    private func fixtureJSON(_ fixture: Fixture, relativeTo dir: URL) throws -> String {
        let data = try Data(contentsOf: dir.appendingPathComponent(fixture.file))
        guard let key = fixture.setDateKeyToToday, var object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return String(decoding: data, as: UTF8.self)
        }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone.current
        object[key] = formatter.string(from: Date())
        return String(decoding: try JSONSerialization.data(withJSONObject: object), as: UTF8.self)
    }

    private func write(json: Any, name: String) throws {
        try JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted, .sortedKeys]).write(to: outDir.appendingPathComponent(name))
    }
}
